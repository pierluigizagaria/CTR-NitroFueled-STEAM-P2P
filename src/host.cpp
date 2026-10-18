#include "host.h"
#include "platform.h"
#include <stdexcept>

namespace bridge {
std::vector<std::string> native_arguments(const Config& c) {
    return {path_text(c.prepared_dir / "boot-linked.bin"), "--import-names", path_text(c.prepared_dir / "import_names.txt"),
        "--content-profile", path_text(c.prepared_dir / "content.bin"), "--patches", path_text(c.prepared_dir / "patches.bin"),
        "--app0", path_text(c.game_dir), "--user", path_text(c.saves), "--timeout", "0"};
}
std::map<std::string, std::string> native_environment(const Config& c, uint64_t account) {
    if (!account || c.online_id.empty()) throw std::runtime_error("Cannot launch host without provider identity");
    auto env = host_environment();
    std::map<std::string, std::string> mapped = {
        {"BB_ONLINE_SERVER", c.server}, {"BB_ONLINE_HTTP_PORT", std::to_string(c.http_port)},
        {"BB_ONLINE_ID", c.online_id}, {"BB_USER_NAME", c.online_id}, {"BB_ONLINE_ACCOUNT_ID", std::to_string(account)},
        {"BB_PATCHES_DIR", path_text(c.patches_dir)}, {"BB_GAME_DIR", path_text(c.game_dir)},
        {"BB_GAME_PROFILE", c.game_profile}, {"BB_DATA_DIR", path_text(c.state)}, {"BB_USER_DIR", path_text(c.saves)},
        {"BB_GPU_USER_DIR", path_text(c.saves)}, {"BB_CONFIG", path_text(c.native_config)},
        {"BB_TIMEOUT", "0"}, {"BB_NEO", "0"}, {"BB_PREUPLOAD", "1"}, {"BB_FPS", "30"}, {"BB_VBLANK_HZ", "60"}
    };
#ifdef _WIN32
    mapped["BB_GUEST_IN_PLACE"] = "0"; mapped["BB_UFFD"] = "0";
    mapped["BB_COPY_GPU_BUFFERS"] = "1"; mapped["BB_GPU_WRITE_TWINS"] = "1";
    mapped["BB_GPU_WRITE_TWINS_MAX"] = "65536";
#endif
    for (const auto& [key, value] : mapped) {
        if (!ascii_printable(value)) throw std::runtime_error("Native mapped environment must be ASCII");
        env[key] = value;
    }
    if (!c.runtime_dir.empty()) {
        std::string old;
        for (auto it = env.begin(); it != env.end();) {
            if (it->first == "PATH" || it->first == "Path" || it->first == "path") { old = it->second; it = env.erase(it); } else ++it;
        }
#ifdef _WIN32
        env["PATH"] = path_text(c.runtime_dir) + ";" + old;
#else
        env["PATH"] = path_text(c.runtime_dir) + ":" + old;
#endif
    }
    return env;
}
}
