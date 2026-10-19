// From-scratch fake host: HTTP and UDP fixtures only, no guest or game code.
#include <nlohmann/json.hpp>
#include <array>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
using Socket = SOCKET;
constexpr Socket invalid_socket = INVALID_SOCKET;
void close_socket(Socket s) { closesocket(s); }
unsigned process_id() { return GetCurrentProcessId(); }
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
using Socket = int;
constexpr Socket invalid_socket = -1;
void close_socket(Socket s) { close(s); }
unsigned process_id() { return static_cast<unsigned>(getpid()); }
#endif
namespace {
using Json = nlohmann::json;
std::string env(const char* name) { const auto p = std::getenv(name); return p ? p : ""; }
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
void save(const std::filesystem::path& file, const Json& data) { std::ofstream(file) << data.dump(2) << '\n'; }
struct Connection {
    Socket value;
    explicit Connection(int type) : value(socket(AF_INET, type, 0)) {
        require(value != invalid_socket, "socket creation");
#ifdef _WIN32
        DWORD timeout = 5000;
#else
        timeval timeout{5, 0};
#endif
        setsockopt(value, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
        setsockopt(value, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&timeout), sizeof(timeout));
    }
    ~Connection() { close_socket(value); }
};
sockaddr_in address(const std::string& ip, unsigned port) {
    sockaddr_in result{}; result.sin_family = AF_INET; result.sin_port = htons(static_cast<uint16_t>(port));
    require(inet_pton(AF_INET, ip.c_str(), &result.sin_addr) == 1, "invalid fixture address"); return result;
}
void send_all(Socket s, const std::string& bytes) {
    size_t offset = 0;
    while (offset < bytes.size()) {
        auto n = send(s, bytes.data() + offset, static_cast<int>(bytes.size() - offset), 0);
        require(n > 0, "HTTP send"); offset += static_cast<size_t>(n);
    }
}
struct Response { int status; std::string head, body; };
Response request(const std::string& host, const std::string& path, const std::string& body) {
    Connection s(SOCK_STREAM);
    auto target = address(env("BB_ONLINE_SERVER"), std::stoul(env("BB_ONLINE_HTTP_PORT")));
    require(connect(s.value, reinterpret_cast<sockaddr*>(&target), sizeof(target)) == 0, "HTTP connect");
    auto wire = "POST " + path + " HTTP/1.1\r\nHost: " + host + "\r\n"
        "Content-Type: application/octet-stream\r\nAccept-Language: it\r\n"
        "X-SacredFire-Scheme: https\r\nX-Fixture-Header: retained\r\n"
        "Connection: close, X-Fixture-Hop\r\nX-Fixture-Hop: remove-me\r\n"
        "Content-Length: " + std::to_string(body.size()) + "\r\n\r\n" + body;
    send_all(s.value, wire);
    std::string response; std::array<char, 4096> buffer{};
    for (;;) {
        auto n = recv(s.value, buffer.data(), static_cast<int>(buffer.size()), 0);
        require(n >= 0, "HTTP receive"); if (!n) break;
        response.append(buffer.data(), static_cast<size_t>(n)); require(response.size() <= 65536, "HTTP response bound");
    }
    auto split = response.find("\r\n\r\n");
    require(response.starts_with("HTTP/1.1 ") && split != std::string::npos, "HTTP response framing");
    return {std::stoi(response.substr(9, 3)), response.substr(0, split), response.substr(split + 4)};
}
unsigned descendant(const char* exe) {
#ifdef _WIN32
    std::wstring path = std::filesystem::path(exe).wstring();
    std::wstring command = L"\"" + path + L"\" --fixture-child";
    STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION child{};
    require(CreateProcessW(path.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                           nullptr, nullptr, &startup, &child), "descendant launch");
    CloseHandle(child.hThread); CloseHandle(child.hProcess); return child.dwProcessId;
#else
    auto pid = fork(); require(pid >= 0, "descendant fork");
    if (!pid) { execl(exe, exe, "--fixture-child", static_cast<char*>(nullptr)); _exit(127); }
    return static_cast<unsigned>(pid);
#endif
}
}
int main(int argc, char** argv) {
    const auto root = std::filesystem::path(env("TEST_CASE_ROOT"));
    try {
        if (argc > 1 && std::string(argv[1]) == "--fixture-child") {
            save(root / "descendant.json", {{"pid", process_id()}});
            // A fixture watchdog bounds failed supervision tests, never a game session.
            std::this_thread::sleep_for(std::chrono::seconds(45)); return 0;
        }
#ifdef _WIN32
        WSADATA data{}; require(WSAStartup(MAKEWORD(2,2), &data) == 0, "Winsock startup");
#endif
        Json report{{"pid", process_id()}, {"arguments", Json::array()}};
        for (int i = 1; i < argc; ++i) report["arguments"].push_back(argv[i]);
        report["online_id"] = env("BB_ONLINE_ID"); report["user_name"] = env("BB_USER_NAME");
        report["saves"] = env("BB_USER_DIR"); report["gpu_user"] = env("BB_GPU_USER_DIR");
        report["game_profile"] = env("BB_GAME_PROFILE");
        report["account_matches_fixture"] = env("BB_ONLINE_ACCOUNT_ID") == "123456789";
        report["private_inheritance_removed"] = env("BB_OSW_STALE_FIXTURE").empty() && env("CTR_STALE_FIXTURE").empty();
        save(root / "host.json", report);
        auto mode = env("TEST_HOST_MODE");
        if (mode == "early") return 7;
        if (mode == "delayed") std::this_thread::sleep_for(std::chrono::milliseconds(300));
        Connection udp(SOCK_DGRAM);
        auto local = address(mode == "wrong-address" ? "127.0.0.2" : "127.0.0.1", 0);
        require(bind(udp.value, reinterpret_cast<sockaddr*>(&local), sizeof(local)) == 0, "UDP bind");
#ifdef _WIN32
        int local_size = sizeof(local);
#else
        socklen_t local_size = sizeof(local);
#endif
        require(getsockname(udp.value, reinterpret_cast<sockaddr*>(&local), &local_size) == 0, "UDP bound endpoint");
        report["udp_port"] = ntohs(local.sin_port);
        std::unique_ptr<Connection> extra;
        if (mode == "ambiguous") {
            extra = std::make_unique<Connection>(SOCK_DGRAM);
            auto other = address("127.0.0.1", 0);
            require(bind(extra->value, reinterpret_cast<sockaddr*>(&other), sizeof(other)) == 0, "Second UDP bind");
        }
        save(root / "host.json", report);
        if (mode == "hold" || mode == "ambiguous" || mode == "wrong-address") {
            auto child = descendant(argv[0]); report["child_pid"] = child;
            save(root / "host.json", report);
            std::this_thread::sleep_for(std::chrono::seconds(45)); return 0;
        }
        auto ready_end = std::chrono::steady_clock::now() + std::chrono::seconds(8);
        for (;;) {
            if (request("sdk:userProfile.np.community.playstation.net", "/fixture-ready", "").status == 204) break;
            require(std::chrono::steady_clock::now() < ready_end, "Endpoint readiness deadline");
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        if (mode == "delayed") { report["endpoint_ready"] = true; save(root / "host.json", report); return 0; }
        if (mode == "closed" || mode == "changed") {
            if (mode == "changed") {
                extra = std::make_unique<Connection>(SOCK_DGRAM);
                auto other = address("127.0.0.1", 0);
                require(bind(extra->value, reinterpret_cast<sockaddr*>(&other), sizeof(other)) == 0, "Changed UDP bind");
                require(getsockname(extra->value, reinterpret_cast<sockaddr*>(&other), &local_size) == 0, "Changed UDP endpoint");
                report["changed_udp_port"] = ntohs(other.sin_port);
            }
            close_socket(udp.value); udp.value = invalid_socket;
            report["endpoint_ready"] = true; save(root / "host.json", report);
            std::this_thread::sleep_for(std::chrono::seconds(45)); return 0;
        }
        const std::string payload("fixture\0binary", 14);
        auto web = request("sdk:userProfile.np.community.playstation.net", "/fixture?x=1", payload);
        require(web.status == 201, "WebAPI status");
        require(web.head.find("application/vnd.bridge-fixture+json") != std::string::npos, "WebAPI content type");
        auto result = Json::parse(web.body);
        require(result["metadata"]["api_group"] == "userprofile", "WebAPI group");
        require(result["metadata"]["method"] == "POST" && result["metadata"]["path"] == "/fixture?x=1", "WebAPI method/path");
        require(result["metadata"]["content_type"] == "application/octet-stream", "WebAPI request type");
        require(result["metadata"]["headers"]["Accept-Language"] == "it", "WebAPI header");
        require(result["body_bytes"] == Json(std::vector<uint8_t>(payload.begin(), payload.end())), "WebAPI binary body");
        auto publisher = request("private-auth.fixture.invalid", "/auth/fixture", payload);
        require(publisher.status == 202, "Publisher status");
        auto echo = Json::parse(publisher.body);
        require(echo["host"] == "private-auth.fixture.invalid", "Publisher original Host");
        require(echo["path"] == "/auth/fixture" && echo["scheme"] == "https", "Publisher metadata");
        require(echo["header"] == "retained" && echo["hop_header_absent"] == true, "Publisher header handling");
        require(echo["body_bytes"] == Json(std::vector<uint8_t>(payload.begin(), payload.end())), "Publisher binary body");
        auto unsupported = request("userProfile.np.community.playstation.net", "/unsupported", "");
        require(unsupported.status == 503, "Unsupported provider operation is explicit");
        auto target = address("127.0.0.1", std::stoul(env("TEST_UDP_PORT")));
        require(sendto(udp.value, payload.data(), static_cast<int>(payload.size()), 0,
                       reinterpret_cast<sockaddr*>(&target), sizeof(target)) == static_cast<int>(payload.size()), "UDP send");
        std::array<char, 64> reply{};
        auto count = recv(udp.value, reply.data(), static_cast<int>(reply.size()), 0);
        require(count == static_cast<int>(payload.size()) && std::string(reply.data(), payload.size()) == payload, "UDP echo");
        report["http_and_udp_passed"] = true; save(root / "host.json", report);
        return 0;
    } catch (const std::exception& error) {
        save(root / "host-error.json", {{"error", error.what()}}); return 9;
    }
}
