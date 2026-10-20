#include "host.h"
#include "platform.h"
#include <expat.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <exception>
#include <fstream>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <vector>

namespace bridge {
namespace {
// The release of the CTR:NF Server Signature Patch for CUSA13795 01.21: its file,
// the key the port's patch selection uses, and its single six-NOP write.
constexpr std::string_view patch_file = "CrashTeamRacingNitroFueled.xml";
constexpr std::string_view patch_name = "CTR:NF Server Signature Patch";
constexpr size_t patch_size_limit = 1048576;
std::string patch_key() { return std::string(patch_file) + "/" + std::string(patch_name); }

std::optional<std::string_view> attribute(const XML_Char** attributes, std::string_view name) {
    for (auto entry = attributes; *entry; entry += 2)
        if (name == entry[0]) return entry[1];
    return std::nullopt;
}
// Collect only actual elements. The native compiler searches descendant ID,
// Metadata and Line elements; comments and CDATA containing markup cannot count.
// Parse the complete document before using this summary, including its suffix.
struct PatchDocument {
    struct Element { bool id; bool child = false; std::string text; };
    struct Metadata { size_t depth; size_t lines = 0; bool write = true; bool elf = true; };
    XML_Parser parser;
    std::vector<Element> elements;
    std::vector<Metadata> active;
    bool title = false, found = false, wrong_elf = false, wrong_write = false;
    const char* problem = nullptr;
    std::exception_ptr failure;

    explicit PatchDocument(XML_Parser value) : parser(value) {}
    void stop(const char* message) {
        problem = message;
        XML_StopParser(parser, XML_FALSE);
    }
    template<class Operation> void callback(Operation operation) noexcept {
        // Never unwind a C++ exception through Expat's C callback frames.
        if (problem || failure) return;
        try { operation(); }
        catch (...) { failure = std::current_exception(); XML_StopParser(parser, XML_FALSE); }
    }
    void start(std::string_view name, const XML_Char** attributes) {
        if (elements.size() == 128) { stop("Signature patch XML nesting exceeds its limit"); return; }
        if (!elements.empty()) elements.back().child = true;
        elements.push_back({name == "ID", false, {}});
        if (name == "Metadata" && attribute(attributes, "Name") == patch_name &&
            attribute(attributes, "AppVer") == "01.21") {
            const auto elf = attribute(attributes, "AppElf");
            active.push_back({elements.size(), 0, true, !elf || *elf == "eboot.bin"});
        }
        if (name == "Line") {
            // The supported release has one literal six-NOP write. Extra or
            // relocated lines can make the native compiler skip/alter it.
            const auto signature = attribute(attributes, "Signature");
            const bool supported = attribute(attributes, "Type") == "bytes" &&
                attribute(attributes, "Address") == "0x00413ec0" &&
                attribute(attributes, "Value") == "909090909090" &&
                (!signature || signature->empty());
            for (auto& metadata : active) { ++metadata.lines; metadata.write &= supported; }
        }
    }
    void text(const XML_Char* value, int length) {
        if (!elements.empty() && elements.back().id && !elements.back().child)
            elements.back().text.append(value, static_cast<size_t>(length));
    }
    void end() {
        if (elements.back().id) {
            const auto& value = elements.back().text;
            const auto first = value.find_first_not_of(" \t\r\n");
            const auto last = value.find_last_not_of(" \t\r\n");
            if (first != value.npos && std::string_view(value).substr(first, last - first + 1) == "CUSA13795") title = true;
        }
        if (!active.empty() && active.back().depth == elements.size()) {
            const auto& metadata = active.back();
            found = true;
            wrong_elf |= !metadata.elf;
            wrong_write |= metadata.lines != 1 || !metadata.write;
            active.pop_back();
        }
        elements.pop_back();
    }
};
std::string parsed_patch_problem(std::string_view xml) {
    if (xml.size() > patch_size_limit) return "Signature patch XML exceeds its size bound";
    // Namespace-aware parsing matches the native parser's element names. No
    // external resolver is registered, and every DTD is rejected before use.
    std::unique_ptr<XML_ParserStruct, decltype(&XML_ParserFree)> parser(XML_ParserCreateNS(nullptr, '\x1f'), XML_ParserFree);
    if (!parser) throw std::runtime_error("Cannot allocate signature patch XML parser");
    PatchDocument document{parser.get()};
    XML_SetUserData(parser.get(), &document);
    XML_SetElementHandler(parser.get(),
        [](void* data, const XML_Char* name, const XML_Char** attributes) {
            auto& doc = *static_cast<PatchDocument*>(data);
            doc.callback([&] { doc.start(name, attributes); });
        },
        [](void* data, const XML_Char*) {
            auto& doc = *static_cast<PatchDocument*>(data);
            doc.callback([&] { doc.end(); });
        });
    XML_SetCharacterDataHandler(parser.get(), [](void* data, const XML_Char* value, int length) {
        auto& doc = *static_cast<PatchDocument*>(data);
        doc.callback([&] { doc.text(value, length); });
    });
    XML_SetStartDoctypeDeclHandler(parser.get(), [](void* data, const XML_Char*, const XML_Char*, const XML_Char*, int) {
        static_cast<PatchDocument*>(data)->stop("Signature patch XML must not contain a DTD");
    });
    const auto result = XML_Parse(parser.get(), xml.data(), static_cast<int>(xml.size()), XML_TRUE);
    if (document.failure) std::rethrow_exception(document.failure);
    if (document.problem) return document.problem;
    if (result != XML_STATUS_OK) return "Signature patch file is malformed XML";
    if (!document.title) return "Signature patch file does not target CUSA13795";
    if (!document.found) return "Signature patch for CUSA13795 01.21 is missing from its file";
    if (document.wrong_elf) return "Signature patch does not target eboot.bin";
    if (document.wrong_write) return "Signature patch does not contain exactly the supported 01.21 write";
    return {};
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
    if (!in) {
        std::error_code error;
        const bool exists = fs::exists(path, error);
        if (error || exists) throw std::runtime_error("Cannot read native patch configuration");
        return std::nullopt;
    }
    std::string text(patch_size_limit + 1, '\0');
    in.read(text.data(), static_cast<std::streamsize>(text.size()));
    if (in.bad() || (in.fail() && !in.eof())) throw std::runtime_error("Cannot read native patch configuration");
    text.resize(static_cast<size_t>(in.gcount()));
    if (text.size() > patch_size_limit) throw std::runtime_error("Native patch configuration exceeds its size bound");
    return text;
}
// Use ordered JSON so unrelated fields keep their order. Reject duplicate keys
// instead of silently discarding one while rewriting the user's configuration.
nlohmann::ordered_json patch_selection(std::string_view selection) {
    using Json = nlohmann::ordered_json;
    std::vector<std::set<std::string>> keys;
    auto json = Json::parse(selection, [&](int, Json::parse_event_t event, Json& value) {
        if (event == Json::parse_event_t::object_start) keys.emplace_back();
        if (event == Json::parse_event_t::object_end) keys.pop_back();
        if (event == Json::parse_event_t::key && !keys.back().insert(value.get<std::string>()).second)
            throw std::runtime_error("Native patches.json contains duplicate fields");
        return true;
    }, false);
    if (!json.is_object()) throw std::runtime_error("Native patches.json is not a JSON object");
    for (const auto* name : {"enabled", "disabled"}) {
        if (!json.contains(name)) continue;
        if (!json[name].is_array()) throw std::runtime_error("Native patches.json selection lists must be arrays");
        for (const auto& item : json[name])
            if (!item.is_string()) throw std::runtime_error("Native patches.json selections must be strings");
    }
    return json;
}
struct NativePatchPaths {
    fs::path selection, xml;
};
NativePatchPaths native_patch_paths(const Config& c, const std::map<std::string, std::string>& inherited) {
    if (!fs::is_regular_file(native_launcher(c))) throw std::runtime_error("Native launcher CTR-NitroFueled-PC.exe is missing beside the bridge");
    if (c.host == "octr" && !fs::is_regular_file(c.root / "psn-bridge-backend.dll"))
        throw std::runtime_error("OCTR PSN adapter psn-bridge-backend.dll is missing beside the bridge");
    const auto data = port_path(c, inherited_value(inherited, "BB_DATA_DIR"), c.root);
    const auto selection = port_path(c, inherited_value(inherited, "BB_PATCHES_CONFIG"), data / "patches.json");
    const auto patches = port_path(c, inherited_value(inherited, "BB_PATCHES_DIR"), c.root / "patches");
    return {selection, patches / std::string(patch_file)};
}
bool bridge_owned(const std::string& key) {
    // Keys are already environment_key()-normalized for this OS.
    for (std::string_view prefix : {"OSW_", "CTR_", "NEXTENDO_", "SHADNET_", "D3_", "DASH_", "BB_ONLINE_", "BB_PSN_"})
        if (key.starts_with(prefix)) return true;
    return key == "BB_USER_NAME" || key == "BB_NET_PRESERVE_ENDPOINTS" ||
           key == "STEAMAPPID" || key == "STEAMGAMEID" ||
           key == "SteamAppId" || key == "SteamGameId";
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
                                                      const std::map<std::string, std::string>& inherited,
                                                      const std::string& psn_capability) {
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
    if (c.host == "octr") {
        if (psn_capability.size() != 64 || psn_capability.find_first_not_of("0123456789abcdef") != std::string::npos)
            throw std::runtime_error("OCTR requires a private PSN bridge capability");
        env[environment_key("BB_ONLINE")] = "1";
        env[environment_key("BB_ONLINE_TUNNEL")] = "0";
        env[environment_key("BB_NET_PRESERVE_ENDPOINTS")] = "1";
        env[environment_key("BB_PSN_BACKEND")] = path_text(c.root / "psn-bridge-backend.dll");
        env[environment_key("BB_PSN_BACKEND_CONFIG")] = nlohmann::json({
            {"url", "http://" + c.address + ":" + std::to_string(c.http_port)},
            {"token", psn_capability}}).dump();
    }
    // Steam initializes in the bridge, but its overlay attaches to the separate
    // native renderer. Give that process the same configured application identity;
    // never inherit an unrelated app/shortcut ID or associate simulated Lab runs.
    if (!c.lab && c.provider == "steam") {
        env[environment_key("SteamAppId")] = std::to_string(c.app_id);
        env[environment_key("SteamGameId")] = std::to_string(c.app_id);
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
    return parsed_patch_problem(xml);
}
void validate_native_installation(const Config& c, const std::map<std::string, std::string>& inherited) {
    const auto paths = native_patch_paths(c, inherited);
    auto json = read_bounded(paths.selection);
    if (!json) throw std::runtime_error("Signature patch is not enabled: the port's patches.json is missing");
    auto xml = read_bounded(paths.xml);
    if (!xml) throw std::runtime_error("Signature patch file is missing from the port's patches folder");
    if (auto problem = signature_patch_problem(*xml, *json); !problem.empty()) throw std::runtime_error(problem);
}
bool enable_native_signature_patch(const Config& c, const std::map<std::string, std::string>& inherited) {
    const auto paths = native_patch_paths(c, inherited);
    const auto xml = read_bounded(paths.xml);
    if (!xml) throw std::runtime_error("Signature patch file is missing from the port's patches folder");
    if (auto problem = parsed_patch_problem(*xml); !problem.empty()) throw std::runtime_error(problem);
    const auto original = read_bounded(paths.selection);
    auto json = patch_selection(original.value_or("{}"));
    const auto key = patch_key();
    bool changed = false;
    if (!json.contains("enabled")) json["enabled"] = nlohmann::ordered_json::array();
    auto& enabled = json["enabled"];
    if (std::find(enabled.begin(), enabled.end(), key) == enabled.end()) {
        enabled.push_back(key);
        changed = true;
    }
    if (json.contains("disabled")) {
        auto& disabled = json["disabled"];
        const auto end = std::remove(disabled.begin(), disabled.end(), key);
        changed |= end != disabled.end();
        disabled.erase(end, disabled.end());
    }
    if (!changed) return false;
    auto replacement = json.dump(2) + "\n";
    if (replacement.size() > patch_size_limit) throw std::runtime_error("Native patch configuration exceeds its size bound");
    // The native launcher also creates a new data directory on first use.
    if (!original) fs::create_directories(paths.selection.parent_path());
    replace_file_atomically(paths.selection, original, replacement);
    return true;
}
}
