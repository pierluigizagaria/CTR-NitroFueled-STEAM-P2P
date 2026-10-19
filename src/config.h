#pragma once
#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <string_view>

namespace bridge {
namespace fs = std::filesystem;
struct Config {
    fs::path root, provider_library, steam_library, executable, game_dir, prepared_dir;
    fs::path patches_dir, profile_dir, signing_key, publisher, runtime_dir, publisher_runtime_dir, lab_root;
    fs::path saves, state, data, native_config;
    std::string provider = "steam", host = "native", online_id, game_profile = "ctr";
    std::string title = "5760", build = "01.21", realm = "ctrnf-p2p";
    std::string server = "127.0.0.2", game_address = "127.0.0.1";
    uint32_t app_id = 480;
    uint16_t http_port = 31380, auth_port = 8460;
    uint64_t lab_account = 0;
    bool unlock_all = false, weak_admission = false, lab = false;
};
Config parse_config(std::string_view text, const fs::path& root);
Config load_config(const fs::path& file, const fs::path& executable_root);
void validate_files(const Config& config);
std::string ascii_name(std::string_view utf8);
bool ascii_printable(std::string_view text);
bool loopback_address(std::string_view text);
std::string path_text(const fs::path& path);
}
