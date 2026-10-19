#include "http.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <optional>
#include <set>
#include <stdexcept>
#include <thread>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace bridge {
namespace {
using Clock = std::chrono::steady_clock;
constexpr size_t max_headers = 32768, max_body = 1024 * 1024;
#ifdef _WIN32
using Socket = SOCKET;
constexpr Socket invalid = INVALID_SOCKET;
void close_socket(Socket s) { closesocket(s); }
struct Networking { Networking() { WSADATA d{}; if (WSAStartup(MAKEWORD(2,2), &d)) throw std::runtime_error("Socket initialization failed"); } ~Networking() { WSACleanup(); } };
#else
using Socket = int;
constexpr Socket invalid = -1;
void close_socket(Socket s) { close(s); }
struct Networking {};
#endif
void initialize() { static Networking network; (void)network; }
struct Connection {
    Socket socket = invalid;
    Clock::time_point deadline = Clock::now() + std::chrono::seconds(30);
    std::string buffer;
    explicit Connection(Socket s) : socket(s) {}
    ~Connection() { if (socket != invalid) close_socket(socket); }
    Connection(const Connection&) = delete;
    Connection& operator=(const Connection&) = delete;
};
std::string lower(std::string_view s) {
    std::string value(s);
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}
std::string trim(std::string_view s) {
    auto start = s.find_first_not_of(" \t");
    if (start == s.npos) return {};
    return std::string(s.substr(start, s.find_last_not_of(" \t") - start + 1));
}
void nonblocking(Socket s) {
#ifdef _WIN32
    u_long flag = 1; if (ioctlsocket(s, FIONBIO, &flag)) throw std::runtime_error("Socket mode failure");
    SetHandleInformation(reinterpret_cast<HANDLE>(s), HANDLE_FLAG_INHERIT, 0);
#else
    if (fcntl(s, F_SETFL, fcntl(s, F_GETFL, 0) | O_NONBLOCK) < 0 || fcntl(s, F_SETFD, FD_CLOEXEC) < 0)
        throw std::runtime_error("Socket mode failure");
#ifdef SO_NOSIGPIPE
    int one = 1; setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
#endif
#endif
}
void ready(Connection& c, bool writing) {
    auto left = std::chrono::duration_cast<std::chrono::microseconds>(c.deadline - Clock::now()).count();
    if (left <= 0) throw std::runtime_error("HTTP request deadline exceeded");
    timeval tv{};
    tv.tv_sec = static_cast<decltype(tv.tv_sec)>(left / 1000000);
    tv.tv_usec = static_cast<decltype(tv.tv_usec)>(left % 1000000);
    fd_set set; FD_ZERO(&set); FD_SET(c.socket, &set);
    if (select(static_cast<int>(c.socket + 1), writing ? nullptr : &set, writing ? &set : nullptr, nullptr, &tv) <= 0)
        throw std::runtime_error("HTTP socket wait failed");
}
void write(Connection& c, std::string_view text) {
    while (!text.empty()) {
        ready(c, true);
#ifdef MSG_NOSIGNAL
        constexpr int flags = MSG_NOSIGNAL;
#else
        constexpr int flags = 0;
#endif
        auto count = send(c.socket, text.data(), static_cast<int>(std::min<size_t>(text.size(), 65536)), flags);
        if (count <= 0) throw std::runtime_error("HTTP send failed");
        text.remove_prefix(static_cast<size_t>(count));
    }
}
bool read_more(Connection& c, size_t bound) {
    ready(c, false);
    std::array<char, 8192> bytes{};
    auto n = recv(c.socket, bytes.data(), static_cast<int>(bytes.size()), 0);
    if (n == 0) return false;
    if (n < 0) throw std::runtime_error("HTTP receive failed");
    if (c.buffer.size() + static_cast<size_t>(n) > bound) throw std::runtime_error("HTTP message exceeds bound");
    c.buffer.append(bytes.data(), static_cast<size_t>(n)); return true;
}
std::string read_head(Connection& c) {
    for (;;) {
        auto end = c.buffer.find("\r\n\r\n");
        if (end != c.buffer.npos) {
            if (end + 4 > max_headers) throw std::runtime_error("HTTP headers exceed bound");
            auto head = c.buffer.substr(0, end + 4); c.buffer.erase(0, end + 4); return head;
        }
        if (c.buffer.size() > max_headers || !read_more(c, max_headers + 8192)) throw std::runtime_error("Incomplete HTTP headers");
    }
}
size_t length(std::string_view value, int base = 10, bool payload = true) {
    size_t n = 0; auto [end, ec] = std::from_chars(value.data(), value.data() + value.size(), n, base);
    if (value.empty() || ec != std::errc{} || end != value.data() + value.size() || (payload && n > max_body))
        throw std::runtime_error("Invalid HTTP body size");
    return n;
}
std::string exact(Connection& c, size_t n) {
    while (c.buffer.size() < n) if (!read_more(c, max_body + max_headers)) throw std::runtime_error("Truncated HTTP body");
    auto result = c.buffer.substr(0, n); c.buffer.erase(0, n); return result;
}
std::string line(Connection& c, size_t& budget) {
    for (;;) {
        auto end = c.buffer.find("\r\n");
        if (end != c.buffer.npos) {
            if (end + 2 > budget) throw std::runtime_error("HTTP framing exceeds bound");
            budget -= end + 2; auto result = c.buffer.substr(0, end); c.buffer.erase(0, end + 2); return result;
        }
        if (c.buffer.size() > budget || !read_more(c, max_body + max_headers)) throw std::runtime_error("Truncated HTTP chunk");
    }
}
Headers parse_headers(std::string_view text) {
    Headers out;
    while (text != "\r\n" && !text.empty()) {
        auto end = text.find("\r\n"), colon = text.find(':');
        if (end == text.npos || colon == text.npos || colon == 0 || colon >= end || out.size() >= 100)
            throw std::runtime_error("Malformed HTTP headers");
        auto name = text.substr(0, colon);
        for (unsigned char c : name)
            if (!(std::isalnum(c) || std::string_view("!#$%&'*+-.^_`|~").find(c) != std::string_view::npos))
                throw std::runtime_error("Malformed HTTP header name");
        auto value = trim(text.substr(colon + 1, end - colon - 1));
        for (unsigned char c : value) if ((c < 32 && c != '\t') || c == 127) throw std::runtime_error("Malformed HTTP header value");
        out.emplace_back(std::string(name), std::move(value)); text.remove_prefix(end + 2);
    }
    for (auto special : {"host", "content-length", "transfer-encoding"}) {
        if (std::count_if(out.begin(), out.end(), [&](const auto& kv) { return lower(kv.first) == special; }) > 1)
            throw std::runtime_error("Duplicate HTTP framing header");
    }
    auto has = [&](std::string_view name) { return std::any_of(out.begin(), out.end(), [&](const auto& kv) { return lower(kv.first) == name; }); };
    if ((has("content-length") && header(out, "content-length").empty()) ||
        (has("transfer-encoding") && header(out, "transfer-encoding").empty()))
        throw std::runtime_error("Empty HTTP body framing header");
    if (has("content-length") && has("transfer-encoding"))
        throw std::runtime_error("Ambiguous HTTP body framing");
    return out;
}
std::string read_body(Connection& c, const Headers& headers, bool response, bool no_body = false) {
    if (no_body) return {};
    auto encoding = lower(header(headers, "transfer-encoding"));
    if (!encoding.empty()) {
        if (encoding != "chunked") throw std::runtime_error("Unsupported HTTP transfer encoding");
        std::string result; size_t budget = max_headers;
        for (;;) {
            auto chunk = line(c, budget); auto semicolon = chunk.find(';');
            auto n = length(std::string_view(chunk).substr(0, semicolon), 16);
            if (!n) { while (!line(c, budget).empty()) {} return result; }
            if (n > max_body - result.size()) throw std::runtime_error("HTTP body exceeds bound");
            result += exact(c, n);
            if (exact(c, 2) != "\r\n") throw std::runtime_error("Malformed HTTP chunk ending");
        }
    }
    auto size = header(headers, "content-length");
    if (!size.empty()) return exact(c, length(size));
    if (!response) return {};
    while (read_more(c, max_body)) {}
    return std::move(c.buffer);
}
std::string render_headers(const Headers& headers, std::optional<size_t> body_size) {
    std::set<std::string> skip{"connection", "keep-alive", "proxy-connection", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length"};
    auto connection = header(headers, "connection");
    while (!connection.empty()) {
        auto comma = connection.find(','); skip.insert(lower(trim(std::string_view(connection).substr(0, comma))));
        if (comma == connection.npos) break; connection.erase(0, comma + 1);
    }
    std::string text;
    for (const auto& [name, value] : headers)
        if (!skip.contains(lower(name))) text += name + ": " + value + "\r\n";
    text += "Connection: close\r\n";
    if (body_size) text += "Content-Length: " + std::to_string(*body_size) + "\r\n";
    return text + "\r\n";
}
sockaddr_in endpoint(const std::string& address, uint16_t port) {
    if (!loopback_address(address)) throw std::runtime_error("HTTP endpoints must be loopback");
    sockaddr_in out{}; out.sin_family = AF_INET; out.sin_port = htons(port);
    if (inet_pton(AF_INET, address.c_str(), &out.sin_addr) != 1) throw std::runtime_error("Invalid HTTP endpoint");
    return out;
}
HttpResponse fixed_error(int code) { return {code, {{"Content-Type", "application/json"}}, "{\"error\":\"bridge_request_failed\"}"}; }
}
std::string header(const Headers& headers, std::string_view name) {
    for (const auto& [key, value] : headers) if (lower(key) == lower(name)) return value;
    return {};
}
std::string api_group(const std::string& value) {
    auto host = lower(value);
    // The pinned native host preserves the SDK authority marker in Host.
    // It is an adapter field, not a TCP port or a second destination.
    const bool sdk = host.starts_with("sdk:");
    if (sdk) host.erase(0, 4);
    auto colon = host.find(':');
    if (colon != host.npos) {
        auto port = std::string_view(host).substr(colon + 1); unsigned number = 0;
        auto [end, error] = std::from_chars(port.data(), port.data() + port.size(), number);
        if (port.empty() || error != std::errc{} || end != port.data() + port.size() || !number || number > 65535)
            throw std::runtime_error("Invalid HTTP authority port");
        host.resize(colon);
    }
    constexpr std::string_view suffix = ".np.community.playstation.net";
    if (!host.ends_with(suffix)) {
        if (sdk) throw std::runtime_error("Unsupported SDK authority");
        return {};
    }
    auto group = host.substr(0, host.size() - suffix.size());
    if (group.empty() || group.find('.') != group.npos || group.size() > 64) throw std::runtime_error("Invalid platform API host");
    for (unsigned char c : group) if (!std::isalnum(c) && c != '-') throw std::runtime_error("Invalid platform API group");
    return group;
}
HttpRequest parse_request_head(std::string_view head) {
    if (head.size() > max_headers || !head.ends_with("\r\n\r\n")) throw std::runtime_error("Invalid HTTP header block");
    auto end = head.find("\r\n"), first = head.find(' '), second = head.find(' ', first + 1);
    if (first == head.npos || second == head.npos || second > end) throw std::runtime_error("Malformed HTTP request line");
    auto version = head.substr(second + 1, end - second - 1);
    if (version != "HTTP/1.1" && version != "HTTP/1.0") throw std::runtime_error("Unsupported HTTP version");
    HttpRequest request{std::string(head.substr(0, first)), std::string(head.substr(first + 1, second - first - 1)), parse_headers(head.substr(end + 2)), {}};
    if (request.method.empty() || request.method.size() > 16 || request.path.empty() || request.path[0] != '/' || request.path.size() > 8192)
        throw std::runtime_error("Invalid HTTP method or path");
    for (unsigned char c : request.method) if (c < 'A' || c > 'Z') throw std::runtime_error("Invalid HTTP method");
    for (unsigned char c : request.path) if (c <= 32 || c == 127) throw std::runtime_error("Invalid HTTP path");
    auto host = header(request.headers, "host");
    if (host.empty() || host.size() > 255 || host.find_first_of(" /\\@\t") != host.npos) throw std::runtime_error("Invalid HTTP Host");
    if (!header(request.headers, "expect").empty()) throw std::runtime_error("HTTP Expect is unsupported");
    return request;
}
HttpResponse proxy_request(const HttpRequest& request, const std::string& address, uint16_t port) {
    initialize(); Connection c(socket(AF_INET, SOCK_STREAM, IPPROTO_TCP));
    if (c.socket == invalid) throw std::runtime_error("Cannot create server connection");
    nonblocking(c.socket); auto target = endpoint(address, port);
    connect(c.socket, reinterpret_cast<sockaddr*>(&target), sizeof(target)); ready(c, true);
    int error = 0;
#ifdef _WIN32
    int size = sizeof(error);
#else
    socklen_t size = sizeof(error);
#endif
    if (getsockopt(c.socket, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &size) || error)
        throw std::runtime_error("Server connection failed");
    write(c, request.method + " " + request.path + " HTTP/1.1\r\n" + render_headers(request.headers, request.body.size()));
    write(c, request.body);
    auto head = read_head(c); auto end = head.find("\r\n");
    if ((!head.starts_with("HTTP/1.0 ") && !head.starts_with("HTTP/1.1 ")) || head.size() < 14 || head[12] != ' ')
        throw std::runtime_error("Invalid server response");
    int status = 0; auto [last, ec] = std::from_chars(head.data() + 9, head.data() + 12, status);
    if (ec != std::errc{} || last != head.data() + 12 || status < 200 || status > 599) throw std::runtime_error("Invalid server status");
    auto headers = parse_headers(std::string_view(head).substr(end + 2));
    auto body = read_body(c, headers, true, request.method == "HEAD" || status == 204 || status == 304);
    return {status, std::move(headers), std::move(body)};
}
struct HttpServer::Impl {
    Socket listener = invalid;
    Handler handler;
    std::atomic<bool> stopping = false;
    std::mutex mutex; std::condition_variable cv; std::deque<Socket> queued;
    std::vector<std::thread> workers; std::thread acceptor;
    void serve(Socket s) {
        Connection c(s);
        try {
            nonblocking(s); auto request = parse_request_head(read_head(c));
            request.body = read_body(c, request.headers, false);
            HttpResponse response;
            try { response = handler(request); } catch (...) { response = fixed_error(502); }
            if (response.status < 200 || response.status > 599 || response.body.size() > max_body) response = fixed_error(502);
            std::optional<size_t> framed_size = response.body.size();
            if (response.status == 204 || response.status == 304) framed_size.reset();
            if ((request.method == "HEAD" || response.status == 304) && response.status != 204) {
                auto advertised = header(response.headers, "content-length");
                if (!advertised.empty()) framed_size = length(advertised, 10, false);
            }
            write(c, "HTTP/1.1 " + std::to_string(response.status) + " Bridge\r\n" + render_headers(response.headers, framed_size));
            if (request.method != "HEAD" && response.status != 204 && response.status != 304) write(c, response.body);
        } catch (...) {
            try { auto r = fixed_error(400); write(c, "HTTP/1.1 400 Bad Request\r\n" + render_headers(r.headers, r.body.size()) + r.body); } catch (...) {}
        }
    }
    void stop() {
        stopping = true; cv.notify_all();
        if (acceptor.joinable()) acceptor.join();
        if (listener != invalid) { close_socket(listener); listener = invalid; }
        for (auto& worker : workers) if (worker.joinable()) worker.join();
        for (auto s : queued) close_socket(s); queued.clear();
    }
    ~Impl() { stop(); }
};
HttpServer::HttpServer(const std::string& address, uint16_t port, Handler handler) : impl_(std::make_unique<Impl>()) {
    initialize(); auto& p = *impl_; p.handler = std::move(handler);
    p.listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (p.listener == invalid) throw std::runtime_error("Cannot create HTTP listener");
#ifdef _WIN32
    BOOL exclusive = TRUE; setsockopt(p.listener, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<char*>(&exclusive), sizeof(exclusive));
#endif
    nonblocking(p.listener); auto target = endpoint(address, port);
    if (bind(p.listener, reinterpret_cast<sockaddr*>(&target), sizeof(target)) || listen(p.listener, 16))
        throw std::runtime_error("HTTP loopback listener unavailable (address or port in use)");
    for (int i = 0; i < 8; ++i) p.workers.emplace_back([&p] {
        for (;;) {
            Socket client;
            { std::unique_lock lock(p.mutex); p.cv.wait(lock, [&] { return p.stopping || !p.queued.empty(); });
              if (p.stopping) return; client = p.queued.front(); p.queued.pop_front(); }
            p.serve(client);
        }
    });
    p.acceptor = std::thread([&p] {
        while (!p.stopping) {
            fd_set reads; FD_ZERO(&reads); FD_SET(p.listener, &reads); timeval interval{0, 100000};
            if (select(static_cast<int>(p.listener + 1), &reads, nullptr, nullptr, &interval) <= 0) continue;
            sockaddr_in source{};
#ifdef _WIN32
            int len = sizeof(source);
#else
            socklen_t len = sizeof(source);
#endif
            auto client = accept(p.listener, reinterpret_cast<sockaddr*>(&source), &len);
            if (client == invalid) continue;
            if ((ntohl(source.sin_addr.s_addr) >> 24) != 127) { close_socket(client); continue; }
            { std::lock_guard lock(p.mutex); if (p.queued.size() >= 16) { close_socket(client); continue; } p.queued.push_back(client); }
            p.cv.notify_one();
        }
    });
}
HttpServer::~HttpServer() = default;
}
