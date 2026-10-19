#include "config.h"
#include "host.h"
#include "http.h"
#include "platform.h"
#include "provider.h"
#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>

namespace { volatile std::sig_atomic_t interrupted = 0; void interrupt(int) { interrupted = 1; } }
namespace {
void check_directory(bridge::Provider& provider) {
    auto created = provider.request(OSW_P2P, {{"op", "directory.create"}, {"capacity", 2}, {"metadata", nlohmann::json::object()}});
    if (created.status != OSW_OK || !created.metadata.is_object() || !created.metadata.contains("room_id") || !created.metadata["room_id"].is_string())
        throw std::runtime_error("Directory check could not create a room");
    auto room = created.metadata["room_id"].get<std::string>();
    try {
        auto read = provider.request(OSW_P2P, {{"op", "directory.members"}, {"room_id", room}});
        if (read.status != OSW_OK || !read.metadata.is_object() || read.metadata.value("room_id", std::string{}) != room)
            throw std::runtime_error("Directory check failed room read-back");
        bool found = false;
        auto end = std::chrono::steady_clock::now() + std::chrono::seconds(20);
        while (!found && std::chrono::steady_clock::now() < end) {
            auto listed = provider.request(OSW_P2P, {{"op", "directory.search"}, {"metadata", nlohmann::json::object()}, {"limit", 32}}, {}, 5000);
            if (listed.status == OSW_OK && listed.metadata.is_object() && listed.metadata.contains("rooms") && listed.metadata["rooms"].is_array())
                for (const auto& item : listed.metadata["rooms"])
                    if (item.is_object() && item.value("room_id", std::string{}) == room) found = true;
            if (!found) std::this_thread::sleep_for(std::chrono::milliseconds(250));
        }
        if (!found) throw std::runtime_error("Directory check did not find its own room");
    } catch (...) { try { provider.request(OSW_P2P, {{"op", "directory.leave"}, {"room_id", room}}); } catch (...) {} throw; }
    auto left = provider.request(OSW_P2P, {{"op", "directory.leave"}, {"room_id", room}});
    if (left.status != OSW_OK) throw std::runtime_error("Directory check could not leave its room");
}
}
int main(int argc, char** argv) {
    using namespace bridge;
    // Supervised runs redirect output to a private log. Make lifecycle evidence
    // visible while the host is running, rather than only when the bridge exits.
    std::cout << std::unitbuf;
    try {
        auto root = executable_path().parent_path(); auto file = root / "ctrnf-p2p.ini";
        bool check_only = false, probe_only = false, directory_only = false;
        for (int i = 1; i < argc; ++i) {
            std::string arg(argv[i]);
            if (arg == "--config" && i + 1 < argc) file = fs::absolute(argv[++i]);
            else if (arg == "--check") check_only = true;
            else if (arg == "--probe") probe_only = true;
            else if (arg == "--directory-check") directory_only = true;
            else if (arg == "--help") { std::cout << "ctrnf-p2p [--config path] [--check | --probe | --directory-check]\n--check validates configuration and launch prerequisites without starting processes; --probe checks provider and server; --directory-check also creates, reads, searches and leaves a room. Neither diagnostic launches the game.\n"; return 0; }
            else throw std::runtime_error("Unknown or incomplete command-line option");
        }
        if (static_cast<int>(check_only) + probe_only + directory_only > 1) throw std::runtime_error("Choose only one diagnostic mode");
        auto c = load_config(file, root); validate_files(c);
        const auto inherited = host_environment();
        // Launch prerequisites are native-adapter specific; the portable
        // provider/server diagnostics do not need them.
        if (check_only || (!probe_only && !directory_only)) validate_native_installation(c, inherited);
        if (check_only) { std::cout << "Configuration, required files and launch prerequisites validated.\n"; return 0; }
        std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt);
        fs::create_directories(c.state); fs::create_directories(c.server_dir / "logs");
        uint64_t bootstrap_account = 0;
        if (!c.lab) {
            // The displayed name always derives from the connected account's persona.
            Provider bootstrap(c, false); bootstrap_account = bootstrap.wait_identity().account_id; c.online_id = ascii_name(bootstrap.persona());
        }
        Provider provider(c, true); auto id = provider.wait_identity(); provider.wait_ready();
        if (bootstrap_account && bootstrap_account != id.account_id) throw std::runtime_error("Platform account changed during launch; restart the bridge");
        if (std::string(id.online_id) != c.online_id) throw std::runtime_error("Provider did not retain the explicit launch name");
        std::cout << (c.lab ? "Simulated Lab" : "Steam") << " provider and local server ready; economy "
                  << (c.unlock_all ? "unlock-all" : "normal") << ".\n";
        HttpServer front(c.address, c.http_port, [&](const HttpRequest& request) {
            auto group = api_group(header(request.headers, "host"));
            return group.empty() ? proxy_request(request, c.address, server_auth_port) : provider.webapi(request, group);
        });
        if (probe_only) { std::cout << "Provider, server and HTTP listener probe passed; no game acceptance implied.\n"; return 0; }
        if (directory_only) {
            DiagnosticDatagram endpoint;
            provider.bind_game_endpoint(c.game_address, endpoint.port());
            check_directory(provider);
            std::cout << "Directory create/read/search/leave passed; no game or peer transport acceptance implied.\n"; return 0;
        }
        Process host(native_launcher(c), {}, c.root, native_environment(c, id.account_id, inherited), c.state / "host.log");
        std::cout << "Native launcher started; start the game from it. There is no session cutoff.\n";
        auto next_check = std::chrono::steady_clock::now();
        std::optional<GameEndpoint> bound;
        while (!interrupted) {
            if (!host.running()) {
                auto code = host.exit_code().value_or(0);
                std::cout << "Native launcher exited with code " << code << ".\n";
                return code == 0 ? 0 : 3;
            }
            if (!bound) {
                if (auto endpoint = host.game_endpoint()) {
                    provider.bind_game_endpoint(c.game_address, endpoint->port);
                    bound = endpoint;
                    std::cout << "Owned game UDP endpoint registered on port " << endpoint->port << ".\n";
                }
            }
            if (std::chrono::steady_clock::now() >= next_check) {
                if (!provider.healthy(id.account_id)) throw std::runtime_error("Provider, account or server became unavailable; supervised session stopped");
                if (bound) {
                    // The session belongs to one game process and port. A game exit,
                    // including the native "Apply and restart", ends it; a changed or
                    // vanished socket of the still-running game fails closed.
                    auto current = host.game_endpoint();
                    if (!current || *current != *bound) {
                        if (!host.alive(*bound)) {
                            std::cout << "Game exited; the supervised session is finished. Relaunch ctrnf-p2p to play online again.\n";
                            return 0;
                        }
                        if (!current)
                            throw std::runtime_error("Owned game UDP endpoint is no longer observable (registered port " +
                                std::to_string(bound->port) + "); restart the supervised session");
                        if (current->owner != bound->owner || current->started != bound->started)
                            throw std::runtime_error("Another supervised process owns the game UDP endpoint; restart the supervised session");
                        throw std::runtime_error("Owned game UDP endpoint changed from port " +
                            std::to_string(bound->port) + " to " + std::to_string(current->port) +
                            "; restart the supervised session");
                    }
                }
                next_check = std::chrono::steady_clock::now() + std::chrono::seconds(1);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        std::cout << "Stopping supervised session.\n";
        return 0;
    } catch (const std::exception& e) {
        // Only local fixed-category failures and configuration labels reach here.
        // Host/provider response payloads and credentials are never printed.
        std::cerr << "ctrnf-p2p: " << e.what() << '\n'; return 1;
    }
}
