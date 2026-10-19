#include "host.h"
#include "platform.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <optional>
#include <stdexcept>

namespace bridge {
namespace {
// The release of the CTR:NF Server Signature Patch for CUSA13795 01.21: its file,
// the key the port's patch selection uses, and its single six-NOP write.
constexpr std::string_view patch_file = "CrashTeamRacingNitroFueled.xml";
constexpr std::string_view patch_name = "CTR:NF Server Signature Patch";
std::string patch_key() { return std::string(patch_file) + "/" + std::string(patch_name); }

std::optional<std::string> attribute(std::string_view tag, std::string_view name) {
    const auto pattern = std::string(name) + "=\"";
    for (auto at = tag.find(pattern); at != tag.npos; at = tag.find(pattern, at + 1)) {
        if (at == 0 || (tag[at - 1] != ' ' && tag[at - 1] != '\t' && tag[at - 1] != '\r' && tag[at - 1] != '\n')) continue;
        auto value = at + pattern.size(), end = tag.find('"', value);
        if (end == tag.npos) return std::nullopt;
        return std::string(tag.substr(value, end - value));
    }
    return std::nullopt;
}
std::string inherited_value(const std::map<std::string, std::string>& inherited, std::string_view name) {
    const auto key = environment_key(name);
    for (const auto& [entry, value] : inherited)
        if (environment_key(entry) == key) return value;
    return {};
}
// run.py resolves its relative locations from the port root (it changes into it).
fs::path port_path(const Config& c, const std::string& value, const fs::path& fallback) {
    if (value.empty()) return fallback;
    fs::path p(value);
    return (p.is_absolute() ? p : c.root / p).lexically_normal();
}
std::optional<std::string> read_bounded(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return std::nullopt;
    std::string text(1048577, '\0');
    in.read(text.data(), static_cast<std::streamsize>(text.size()));
    text.resize(static_cast<size_t>(in.gcount()));
    if (text.size() > 1048576) throw std::runtime_error("Native patch configuration exceeds its size bound");
    return text;
}
bool bridge_owned(const std::string& key) {
    // Keys are already environment_key()-normalized for this OS.
    for (std::string_view prefix : {"OSW_", "CTR_", "NEXTENDO_", "SHADNET_", "D3_", "DASH_", "BB_ONLINE_"})
        if (key.starts_with(prefix)) return true;
    return key == "BB_USER_NAME" || key == "STEAMAPPID" || key == "STEAMGAMEID";
}
}
fs::path native_launcher(const Config& c) {
#ifdef _WIN32
    return c.root / "CTR-NitroFueled-PC.exe";
#else
    // The POSIX launcher detaches the game into its own session, beyond this
    // bridge's process-group teardown. Refuse instead of leaving it unsupervised.
    (void)c;
    throw std::runtime_error("Native host launch is not yet supported on this OS");
#endif
}
std::map<std::string, std::string> native_environment(const Config& c, uint64_t account,
                                                      const std::map<std::string, std::string>& inherited) {
    if (!account || c.online_id.empty()) throw std::runtime_error("Cannot launch host without provider identity");
    std::map<std::string, std::string> env;
    for (const auto& [name, value] : inherited) {
        auto key = environment_key(name);
        if (!bridge_owned(key)) env[key] = value;
    }
    // The native port lets these environment values win over bbport.ini. An
    // explicit loopback allow list keeps bbport.ini online_allow from widening it.
    const std::map<std::string, std::string> mapped = {
        {"BB_ONLINE_SERVER", c.address}, {"BB_ONLINE_HTTP_PORT", std::to_string(c.http_port)},
        {"BB_ONLINE_ID", c.online_id}, {"BB_USER_NAME", c.online_id},
        {"BB_ONLINE_ACCOUNT_ID", std::to_string(account)}, {"BB_ONLINE_ALLOW", "127.0.0.1"}
    };
    for (const auto& [name, value] : mapped) {
        if (!ascii_printable(value)) throw std::runtime_error("Native mapped environment must be ASCII");
        env[environment_key(name)] = value;
    }
    return env;
}
std::string signature_patch_problem(std::string_view xml, std::string_view selection) {
    auto json = nlohmann::json::parse(selection, nullptr, false);
    if (!json.is_object()) return "Native patches.json is not a JSON object";
    auto listed = [&](const char* name) {
        if (!json.contains(name)) return false;
        const auto& list = json[name];
        if (!list.is_array()) throw std::runtime_error("Native patches.json selection lists must be arrays");
        for (const auto& item : list)
            if (item.is_string() && item.get<std::string>() == patch_key()) return true;
        return false;
    };
    const bool enabled = listed("enabled"), disabled = listed("disabled");
    if (enabled && disabled) return "Signature patch is both enabled and disabled in patches.json";
    if (!enabled) return "Signature patch is not enabled in patches.json";
    if (xml.find("<ID>CUSA13795</ID>") == xml.npos) return "Signature patch file does not target CUSA13795";
    for (auto at = xml.find("<Metadata"); at != xml.npos; at = xml.find("<Metadata", at + 1)) {
        auto close = xml.find('>', at), end = xml.find("</Metadata>", at);
        if (close == xml.npos || end == xml.npos || close > end) return "Signature patch file is malformed";
        auto tag = xml.substr(at, close - at);
        if (attribute(tag, "Name") != std::string(patch_name) || attribute(tag, "AppVer") != "01.21") continue;
        auto elf = attribute(tag, "AppElf");
        if (elf && *elf != "eboot.bin") return "Signature patch does not target eboot.bin";
        auto body = xml.substr(close, end - close);
        for (auto line = body.find("<Line"); line != body.npos; line = body.find("<Line", line + 1)) {
            auto line_end = body.find('>', line);
            if (line_end == body.npos) return "Signature patch file is malformed";
            auto entry = body.substr(line, line_end - line);
            if (attribute(entry, "Type") == "bytes" && attribute(entry, "Address") == "0x00413ec0" &&
                attribute(entry, "Value") == "909090909090")
                return {};
        }
        return "Signature patch does not contain the supported 01.21 write";
    }
    return "Signature patch for CUSA13795 01.21 is missing from its file";
}
void validate_native_installation(const Config& c, const std::map<std::string, std::string>& inherited) {
    if (!fs::is_regular_file(native_launcher(c))) throw std::runtime_error("Native launcher CTR-NitroFueled-PC.exe is missing beside the bridge");
    const auto data = port_path(c, inherited_value(inherited, "BB_DATA_DIR"), c.root);
    const auto selection = port_path(c, inherited_value(inherited, "BB_PATCHES_CONFIG"), data / "patches.json");
    const auto patches = port_path(c, inherited_value(inherited, "BB_PATCHES_DIR"), c.root / "patches");
    auto json = read_bounded(selection);
    if (!json) throw std::runtime_error("Signature patch is not enabled: the port's patches.json is missing");
    auto xml = read_bounded(patches / std::string(patch_file));
    if (!xml) throw std::runtime_error("Signature patch file is missing from the port's patches folder");
    if (auto problem = signature_patch_problem(*xml, *json); !problem.empty()) throw std::runtime_error(problem);
}
}
