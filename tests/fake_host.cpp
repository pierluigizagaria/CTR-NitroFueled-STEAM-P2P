// From-scratch fake launcher and game: HTTP and UDP fixtures only, no guest or game code.
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
#include <sys/wait.h>
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
// A started fixture process; the launcher waits for its game like the real one.
struct Child {
    unsigned pid = 0;
#ifdef _WIN32
    HANDLE handle = nullptr;
#endif
};
Child spawn(const char* exe, const char* flag) {
#ifdef _WIN32
    std::wstring path = std::filesystem::path(exe).wstring();
    std::wstring command = L"\"" + path + L"\" " + std::filesystem::path(flag).wstring();
    STARTUPINFOW startup{}; startup.cb = sizeof(startup); PROCESS_INFORMATION child{};
    require(CreateProcessW(path.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                           nullptr, nullptr, &startup, &child), "fixture process launch");
    CloseHandle(child.hThread); return {child.dwProcessId, child.hProcess};
#else
    auto pid = fork(); require(pid >= 0, "fixture process fork");
    if (!pid) { execl(exe, exe, flag, static_cast<char*>(nullptr)); _exit(127); }
    return {static_cast<unsigned>(pid)};
#endif
}
int wait_for(Child child) {
#ifdef _WIN32
    WaitForSingleObject(child.handle, INFINITE);
    DWORD code = 1; GetExitCodeProcess(child.handle, &code); CloseHandle(child.handle);
    return static_cast<int>(code);
#else
    int status = 0; waitpid(static_cast<pid_t>(child.pid), &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
#endif
}
void set_env(const char* name, const std::string& value) {
#ifdef _WIN32
    SetEnvironmentVariableA(name, value.c_str());
#else
    setenv(name, value.c_str(), 1);
#endif
}
// Sockets are owned through a pointer: Connection closes its socket on destruction.
std::unique_ptr<Connection> bound_udp(const char* ip, unsigned port, Json& report, const char* field) {
    auto udp = std::make_unique<Connection>(SOCK_DGRAM);
    auto local = address(ip, port);
    require(bind(udp->value, reinterpret_cast<sockaddr*>(&local), sizeof(local)) == 0, "UDP bind");
#ifdef _WIN32
    int local_size = sizeof(local);
#else
    socklen_t local_size = sizeof(local);
#endif
    require(getsockname(udp->value, reinterpret_cast<sockaddr*>(&local), &local_size) == 0, "UDP bound endpoint");
    report[field] = ntohs(local.sin_port);
    return udp;
}
void wait_endpoint_ready() {
    auto ready_end = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    for (;;) {
        if (request("sdk:userProfile.np.community.playstation.net", "/fixture-ready", "").status == 204) break;
        require(std::chrono::steady_clock::now() < ready_end, "Endpoint readiness deadline");
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}
// Stands in for the native launcher: records what the bridge passed, then starts
// the game as the player would and stays open (or closes) when it ends.
int launcher(const std::filesystem::path& root, const char* exe, int argc, char** argv) {
    Json report{{"pid", process_id()}, {"arguments", Json::array()}, {"cwd", std::filesystem::current_path().string()}};
    for (int i = 1; i < argc; ++i) report["arguments"].push_back(argv[i]);
    for (auto [field, name] : std::initializer_list<std::pair<const char*, const char*>>{{"online_server", "BB_ONLINE_SERVER"}, {"http_port", "BB_ONLINE_HTTP_PORT"},
                               {"online_id", "BB_ONLINE_ID"}, {"user_name", "BB_USER_NAME"}, {"allow", "BB_ONLINE_ALLOW"},
                               {"native_fixture", "BB_NATIVE_FIXTURE"},
                               {"steam_app_id", "SteamAppId"}, {"steam_game_id", "SteamGameId"}})
        report[field] = env(name);
    report["account_matches_fixture"] = env("BB_ONLINE_ACCOUNT_ID") == "123456789";
    report["private_inheritance_removed"] = env("BB_ONLINE_STALE_FIXTURE").empty() && env("CTR_STALE_FIXTURE").empty() &&
                                            env("OSW_STALE_FIXTURE").empty();
    bool native_set = false;
    for (auto name : {"BB_USER_DIR", "BB_GPU_USER_DIR", "BB_GAME_DIR", "BB_CONFIG", "BB_FPS", "BB_NEO", "BB_TIMEOUT",
                      "BB_GAME_PROFILE", "BB_PATCHES_DIR", "BB_VBLANK_HZ"})
        native_set |= !env(name).empty();
    report["native_settings_absent"] = !native_set;
    save(root / "launcher.json", report);
    const auto mode = env("TEST_LAUNCHER_MODE");
    std::unique_ptr<Connection> own;
    if (mode == "two-owners") own = bound_udp("127.0.0.1", 0, report, "launcher_udp_port");
    int code = wait_for(spawn(exe, "--fixture-game"));
    if (mode == "restart" && code == 75) {
        // The native "Apply and restart": a new game process rebinds the same port.
        auto game = Json::parse(std::ifstream(root / "host.json"));
        set_env("TEST_RESTARTED", "1"); set_env("TEST_RESTART_PORT", std::to_string(game["udp_port"].get<unsigned>()));
        code = wait_for(spawn(exe, "--fixture-game"));
    }
    if (env("TEST_LAUNCHER_LINGER") == "1") std::this_thread::sleep_for(std::chrono::seconds(45));
    return code;
}
int game(const std::filesystem::path& root, const char* exe) {
#ifdef _WIN32
    WSADATA data{}; require(WSAStartup(MAKEWORD(2,2), &data) == 0, "Winsock startup");
#endif
    Json report{{"pid", process_id()}, {"steam_app_id", env("SteamAppId")}, {"steam_game_id", env("SteamGameId")}};
    if (env("TEST_RESTARTED") == "1") {
        auto udp = bound_udp("127.0.0.1", std::stoul(env("TEST_RESTART_PORT")), report, "udp_port");
        save(root / "restarted.json", report);
        std::this_thread::sleep_for(std::chrono::seconds(45)); return 0;
    }
    save(root / "host.json", report);
    auto mode = env("TEST_HOST_MODE");
    if (mode == "early") return 7;
    if (mode == "delayed") std::this_thread::sleep_for(std::chrono::milliseconds(300));
    auto udp = bound_udp(mode == "wrong-address" ? "127.0.0.2" : "127.0.0.1", 0, report, "udp_port");
    std::unique_ptr<Connection> extra;
    if (mode == "ambiguous") extra = bound_udp("127.0.0.1", 0, report, "second_udp_port");
    save(root / "host.json", report);
    if (mode == "hold" || mode == "ambiguous" || mode == "wrong-address") {
        auto child = spawn(exe, "--fixture-child"); report["child_pid"] = child.pid;
#ifdef _WIN32
        CloseHandle(child.handle);
#endif
        save(root / "host.json", report);
        std::this_thread::sleep_for(std::chrono::seconds(45)); return 0;
    }
    wait_endpoint_ready();
    if (mode == "delayed") { report["endpoint_ready"] = true; save(root / "host.json", report); return 0; }
    if (mode == "restart") { report["endpoint_ready"] = true; save(root / "host.json", report); return 75; }
    if (mode == "closed" || mode == "changed") {
        if (mode == "changed") extra = bound_udp("127.0.0.1", 0, report, "changed_udp_port");
        close_socket(udp->value); udp->value = invalid_socket;
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
    auto server = request("private-auth.fixture.invalid", "/auth/fixture", payload);
    require(server.status == 202, "Server status");
    auto echo = Json::parse(server.body);
    require(echo["host"] == "private-auth.fixture.invalid", "Server original Host");
    require(echo["path"] == "/auth/fixture" && echo["scheme"] == "https", "Server metadata");
    require(echo["header"] == "retained" && echo["hop_header_absent"] == true, "Server header handling");
    require(echo["body_bytes"] == Json(std::vector<uint8_t>(payload.begin(), payload.end())), "Server binary body");
    auto unsupported = request("userProfile.np.community.playstation.net", "/unsupported", "");
    require(unsupported.status == 503, "Unsupported provider operation is explicit");
    auto target = address("127.0.0.1", std::stoul(env("TEST_UDP_PORT")));
    require(sendto(udp->value, payload.data(), static_cast<int>(payload.size()), 0,
                   reinterpret_cast<sockaddr*>(&target), sizeof(target)) == static_cast<int>(payload.size()), "UDP send");
    std::array<char, 64> reply{};
    auto count = recv(udp->value, reply.data(), static_cast<int>(reply.size()), 0);
    require(count == static_cast<int>(payload.size()) && std::string(reply.data(), payload.size()) == payload, "UDP echo");
    report["http_and_udp_passed"] = true; save(root / "host.json", report);
    return 0;
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
        if (argc > 1 && std::string(argv[1]) == "--fixture-game") return game(root, argv[0]);
#ifdef _WIN32
        WSADATA data{}; require(WSAStartup(MAKEWORD(2,2), &data) == 0, "Winsock startup");
#endif
        return launcher(root, argv[0], argc, argv);
    } catch (const std::exception& error) {
        save(root / "host-error.json", {{"error", error.what()}}); return 9;
    }
}
