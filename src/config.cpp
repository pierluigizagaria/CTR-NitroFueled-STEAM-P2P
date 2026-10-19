#include "config.h"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <charconv>
#include <fstream>
#include <set>
#include <sstream>
#include <stdexcept>

namespace bridge {
namespace {
std::string trim(std::string_view s) {
    auto first = s.find_first_not_of(" \t\r\n");
    if (first == s.npos) return {};
    auto last = s.find_last_not_of(" \t\r\n");
    return std::string(s.substr(first, last - first + 1));
}
uint64_t number(std::string_view s, uint64_t low, uint64_t high, const std::string& key) {
    uint64_t value = 0;
    auto [end, error] = std::from_chars(s.data(), s.data() + s.size(), value);
    if (error != std::errc{} || end != s.data() + s.size() || value < low || value > high)
        throw std::runtime_error(key + " must be a decimal integer in range");
    return value;
}
bool boolean(const std::string& s, const std::string& key) {
    if (s == "true") return true;
    if (s == "false") return false;
    throw std::runtime_error(key + " must be true or false");
}
fs::path resolve(const fs::path& root, const std::string& value) {
    if (value.empty()) return {};
    if (!ascii_printable(value)) throw std::runtime_error("Paths passed to the native host must be printable ASCII");
    fs::path p(value);
    return fs::absolute(p.is_absolute() ? p : root / p).lexically_normal();
}
void label(const std::string& s, size_t max, const char* key) {
    if (s.empty() || s.size() > max || !ascii_printable(s) || trim(s) != s)
        throw std::runtime_error(std::string(key) + " is empty, too long or invalid");
}
}
std::string path_text(const fs::path& path) {
    auto s = path.generic_u8string();
    return std::string(s.begin(), s.end());
}
bool ascii_printable(std::string_view s) {
    return std::all_of(s.begin(), s.end(), [](unsigned char c) { return c >= 32 && c <= 126; });
}
bool loopback_address(std::string_view text) {
    std::array<unsigned, 4> pieces{};
    for (size_t i = 0; i < 4; ++i) {
        auto dot = text.find('.');
        auto part = text.substr(0, dot);
        if (part.empty() || (part.size() > 1 && part[0] == '0')) return false;
        auto [end, ec] = std::from_chars(part.data(), part.data() + part.size(), pieces[i]);
        if (ec != std::errc{} || end != part.data() + part.size() || pieces[i] > 255) return false;
        if (i == 3) { if (dot != text.npos) return false; }
        else { if (dot == text.npos) return false; text.remove_prefix(dot + 1); }
    }
    return pieces[0] == 127;
}
std::string ascii_name(std::string_view input) {
    std::string output;
    for (size_t i = 0; i < input.size();) {
        auto c = static_cast<unsigned char>(input[i]);
        if (c < 128) { output += c >= 32 && c <= 126 ? static_cast<char>(c) : '_'; ++i; continue; }
        size_t count = (c >= 0xc2 && c <= 0xdf) ? 2 : (c >= 0xe0 && c <= 0xef) ? 3 :
                       (c >= 0xf0 && c <= 0xf4) ? 4 : 1;
        if (i + count > input.size()) count = 1;
        for (size_t j = 1; j < count; ++j)
            if ((static_cast<unsigned char>(input[i + j]) & 0xc0) != 0x80) { count = 1; break; }
        output += '_'; i += count;
    }
    output = trim(output);
    if (output.size() > 16) output.resize(16);
    output = trim(output);
    if (output.empty()) throw std::runtime_error("The player name is empty after ASCII conversion; set player.online_id");
    return output;
}
Config parse_config(std::string_view text, const fs::path& root) {
    if (text.size() > 65536 || text.find('\0') != text.npos) throw std::runtime_error("Invalid configuration size or NUL byte");
    static const std::map<std::string, std::set<std::string>> keys = {
        {"platform", {"provider", "library"}}, {"steam", {"app_id", "library"}},
        {"player", {"online_id", "unlock_all"}},
        {"game", {"host", "profile", "executable", "game_dir", "prepared_dir", "patches_dir", "profile_dir", "runtime_dir", "config", "normal_saves", "unlock_all_saves"}},
        {"publisher", {"executable", "signing_key", "weak_admission", "runtime_dir"}},
        {"session", {"title", "build", "realm"}},
        {"network", {"server", "http_port", "auth_port", "game_address"}},
        {"lab", {"enabled", "account_id", "root"}}
    };
    std::map<std::string, std::string> values;
    std::set<std::string> sections;
    std::istringstream stream{std::string(text)};
    std::string line, section;
    while (std::getline(stream, line)) {
        line = trim(line);
        if (line.empty() || line[0] == ';' || line[0] == '#') continue;
        if (line[0] == '[') {
            if (line.back() != ']') throw std::runtime_error("Malformed section");
            section = trim(std::string_view(line).substr(1, line.size() - 2));
            if (!keys.contains(section) || !sections.insert(section).second)
                throw std::runtime_error("Unknown or duplicate section: " + section);
            continue;
        }
        auto eq = line.find('=');
        if (eq == line.npos || !keys.contains(section)) throw std::runtime_error("Expected a setting inside a section");
        auto key = trim(std::string_view(line).substr(0, eq));
        if (!keys.at(section).contains(key)) throw std::runtime_error("Unknown setting: " + section + "." + key);
        auto value = trim(std::string_view(line).substr(eq + 1));
        if (!value.empty() && value[0] == '"') {
            auto parsed = nlohmann::json::parse(value, nullptr, false);
            if (!parsed.is_string()) throw std::runtime_error("Quoted values must be JSON strings");
            value = parsed.get<std::string>();
        } else {
            for (size_t i = 0; i < value.size(); ++i)
                if ((value[i] == ';' || value[i] == '#') && (i == 0 || value[i - 1] == ' ' || value[i - 1] == '\t')) {
                    value = trim(std::string_view(value).substr(0, i)); break;
                }
        }
        if (value.find('\0') != value.npos || !values.emplace(section + "." + key, value).second)
            throw std::runtime_error("Invalid or duplicate setting: " + section + "." + key);
    }
    auto get = [&](const std::string& key, const std::string& fallback = "") {
        auto it = values.find(key); return it == values.end() ? fallback : it->second;
    };
    auto path = [&](const std::string& key, const std::string& fallback = "") { return resolve(root, get(key, fallback)); };
    Config c; c.root = fs::absolute(root);
    c.provider = get("platform.provider", "steam"); c.host = get("game.host", "native");
    if (c.provider != "steam") throw std::runtime_error("Unsupported platform.provider; only steam is implemented");
    if (c.host != "native") throw std::runtime_error("Unsupported game.host; only native is implemented");
    c.game_profile = get("game.profile", c.game_profile); label(c.game_profile, 64, "game.profile");
#ifdef _WIN32
    c.provider_library = path("platform.library", "orbisteamworks.dll");
    c.steam_library = path("steam.library", "steam_api64.dll");
#elif defined(__APPLE__)
    c.provider_library = path("platform.library", "liborbisteamworks.dylib");
    c.steam_library = path("steam.library", "libsteam_api.dylib");
#else
    c.provider_library = path("platform.library", "liborbisteamworks.so");
    c.steam_library = path("steam.library", "libsteam_api.so");
#endif
    if (c.steam_library.parent_path() != c.root.lexically_normal())
        throw std::runtime_error("steam.library must be beside the bridge executable");
    c.app_id = static_cast<uint32_t>(number(get("steam.app_id", "480"), 1, UINT32_MAX, "steam.app_id"));
    c.online_id = get("player.online_id");
    if (!c.online_id.empty()) c.online_id = ascii_name(c.online_id);
    c.unlock_all = boolean(get("player.unlock_all", "false"), "player.unlock_all");
    c.weak_admission = boolean(get("publisher.weak_admission", "false"), "publisher.weak_admission");
    c.executable = path("game.executable"); c.game_dir = path("game.game_dir");
    c.prepared_dir = path("game.prepared_dir"); c.patches_dir = path("game.patches_dir");
    c.profile_dir = path("game.profile_dir", "runtime/player");
    c.runtime_dir = path("game.runtime_dir"); c.native_config = path("game.config");
    c.publisher = path("publisher.executable"); c.signing_key = path("publisher.signing_key");
    c.publisher_runtime_dir = path("publisher.runtime_dir");
    c.title = get("session.title", c.title); c.build = get("session.build", c.build); c.realm = get("session.realm", c.realm);
    label(c.title, 16, "session.title"); label(c.build, 64, "session.build"); label(c.realm, 64, "session.realm");
    c.server = get("network.server", c.server); c.game_address = get("network.game_address", c.game_address);
    if (!loopback_address(c.server) || !loopback_address(c.game_address)) throw std::runtime_error("network addresses must be literal loopback IPv4");
    if (!c.server.starts_with("127.0.0.") || c.server == "127.0.0.0" || c.server == "127.0.0.1" || c.server == "127.0.0.255")
        throw std::runtime_error("Bridge publisher listeners use 127.0.0.2 through 127.0.0.254");
    if (c.game_address != "127.0.0.1") throw std::runtime_error("The upstream native wildcard socket is observed as network.game_address=127.0.0.1");
    c.http_port = static_cast<uint16_t>(number(get("network.http_port", "31380"), 1, 65535, "network.http_port"));
    c.auth_port = static_cast<uint16_t>(number(get("network.auth_port", "8460"), 1, 65535, "network.auth_port"));
    if (c.http_port == c.auth_port || (c.http_port >= 3074 && c.http_port <= 3080) || c.http_port == 8093)
        throw std::runtime_error("HTTP front port conflicts with publisher listeners");
    if ((c.auth_port >= 3074 && c.auth_port <= 3080) || c.auth_port == 8093)
        throw std::runtime_error("Publisher auth port conflicts with lobby/dashboard listeners");
    if (c.server == c.game_address) throw std::runtime_error("Publisher and native game addresses must be distinct");
    c.lab = boolean(get("lab.enabled", "false"), "lab.enabled");
    c.lab_root = path("lab.root");
    c.lab_account = number(get("lab.account_id", "0"), 0, UINT64_MAX, "lab.account_id");
    if (c.lab && (!c.lab_account || c.lab_root.empty() || c.online_id.empty()))
        throw std::runtime_error("Explicit Lab mode requires lab.account_id, lab.root and player.online_id");
    if (!c.lab && (c.lab_account || !c.lab_root.empty())) throw std::runtime_error("Lab settings require lab.enabled=true");
    c.state = c.profile_dir / (c.unlock_all ? "unlock-all" : "normal");
    auto normal = path("game.normal_saves"), unlocked = path("game.unlock_all_saves");
    if (normal.empty()) normal = c.profile_dir / "normal" / "user";
    if (unlocked.empty()) unlocked = c.profile_dir / "unlock-all" / "user";
    auto comparable = [](const fs::path& p) {
        auto result = path_text(fs::weakly_canonical(p));
#ifdef _WIN32
        std::transform(result.begin(), result.end(), result.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
#endif
        return result + "/";
    };
    auto n = comparable(normal), u = comparable(unlocked);
    if (n.starts_with(u) || u.starts_with(n)) throw std::runtime_error("Normal and unlock-all save directories must not overlap");
    c.saves = c.unlock_all ? unlocked : normal;
    c.data = c.state / "publisher";
    if (c.native_config.empty()) c.native_config = c.state / "bbport.ini";
    return c;
}
Config load_config(const fs::path& file, const fs::path& root) {
    std::ifstream in(file, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open configuration file");
    std::string text(65537, '\0'); in.read(text.data(), static_cast<std::streamsize>(text.size()));
    text.resize(static_cast<size_t>(in.gcount())); return parse_config(text, root);
}
void validate_files(const Config& c) {
    for (const auto& [path, name] : std::initializer_list<std::pair<fs::path, const char*>>{
        {c.executable, "game.executable"}, {c.publisher, "publisher.executable"}, {c.signing_key, "publisher.signing_key"},
        {c.provider_library, "platform.library"}, {c.game_dir / "eboot.bin", "game.game_dir/eboot.bin"},
        {c.prepared_dir / "boot-linked.bin", "game.prepared_dir/boot-linked.bin"},
        {c.prepared_dir / "import_names.txt", "game.prepared_dir/import_names.txt"},
        {c.prepared_dir / "content.bin", "game.prepared_dir/content.bin"},
        {c.prepared_dir / "patches.bin", "game.prepared_dir/patches.bin"}})
        if (path.empty() || !fs::is_regular_file(path)) throw std::runtime_error(std::string("Missing file for ") + name);
    if (!fs::is_directory(c.patches_dir)) throw std::runtime_error("game.patches_dir must exist");
    if (!c.lab && !fs::is_regular_file(c.steam_library)) throw std::runtime_error("User-supplied Steam API library is missing beside the bridge");
    if (!c.runtime_dir.empty() && !fs::is_directory(c.runtime_dir)) throw std::runtime_error("game.runtime_dir must exist");
    if (!c.publisher_runtime_dir.empty() && !fs::is_directory(c.publisher_runtime_dir)) throw std::runtime_error("publisher.runtime_dir must exist");
    if (!c.weak_admission) throw std::runtime_error("Native upstream requires explicit publisher.weak_admission=true");
}
}
