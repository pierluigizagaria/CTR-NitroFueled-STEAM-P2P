#pragma once
#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <string_view>

namespace bridge {
namespace fs = std::filesystem;
// The server's plain HTTP auth listener on network.address: internal wiring
// between the bridge front and its own child, never a user setting.
inline constexpr uint16_t server_auth_port = 8460;
struct Config {
    // root is the bridge executable directory, which is also the port root.
    fs::path root, provider_library, steam_library, server, lab_root;
    // Bridge-owned state beside the executable; the server's own folder beside
    // its executable, holding data/ and logs/.
    fs::path state, server_dir;
    std::string provider = "steam", host = "native", online_id;
    // title and build come from the host adapter; realm is the matchmaking namespace.
    std::string title, build, realm = "ctrnf-p2p";
    std::string address = "127.0.0.2", game_address;
    uint32_t app_id = 480;
    uint16_t http_port = 31380;
    uint64_t lab_account = 0;
    // native_token: the host adapter cannot present a provider capability and
    // enables the server's loopback owner-token admission instead.
    bool unlock_all = false, native_token = false, lab = false;
};
Config parse_config(std::string_view text, const fs::path& root);
Config load_config(const fs::path& file, const fs::path& executable_root);
// Files every mode needs: provider, Steam library and server executable.
void validate_files(const Config& config);
std::string ascii_name(std::string_view utf8);
bool ascii_printable(std::string_view text);
bool loopback_address(std::string_view text);
std::string path_text(const fs::path& path);
}
