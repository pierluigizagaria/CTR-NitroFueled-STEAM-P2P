#include "config.h"
#include "host.h"
#include "http.h"
#include "platform.h"
#include <functional>
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0;
void require(bool value, const char* message) { ++checks; if (!value) throw std::runtime_error(message); }
void rejects(const std::function<void()>& operation) {
    bool failed = false; try { operation(); } catch (const std::exception&) { failed = true; }
    require(failed, "Invalid input was accepted");
}
const char* patch_xml = R"(<?xml version='1.0' encoding='utf-8'?>
<Patch><TitleID><ID>CUSA13795</ID></TitleID><Metadata Title="Crash Team Racing Nitro-Fueled" Name="CTR:NF Server Signature Patch" Author="fixture" PatchVer="0.1" AppVer="01.21" AppElf="eboot.bin" isEnabled="false" Note="fixture"><PatchList><Line Type="bytes" Address="0x00413ec0" Value="909090909090" /></PatchList></Metadata></Patch>)";
const char* selected = R"({"enabled": ["CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch"], "disabled": []})";
const char* patch_line = R"(<Line Type="bytes" Address="0x00413ec0" Value="909090909090" />)";
std::string replaced(std::string text, const std::string& from, const std::string& to) {
    auto at = text.find(from); if (at == text.npos) throw std::runtime_error("fixture text missing");
    return text.replace(at, from.size(), to);
}
}
int main() {
    using namespace bridge;
    try {
        auto root = fs::absolute("fixture-root").lexically_normal();
        auto c = parse_config("", root);
        require(c.app_id == 480 && !c.unlock_all && !c.lab && c.realm == "ctrnf-p2p", "Defaults changed");
        require(c.title == "5760" && c.build == "01.21" && c.game_address == "127.0.0.1" && c.native_token,
                "Native adapter contract changed");
        require(c.address == "127.0.0.2" && c.http_port == 31380, "Network defaults changed");
        require(c.state == root / "ctrnf-p2p", "Bridge state is not beside the executable");
#ifdef _WIN32
        require(c.server == root / "demonware-server.exe", "Server default is not beside the bridge");
#else
        require(c.server == root / "demonware-server", "POSIX server default carries a Windows suffix");
#endif
        require(c.server_dir == root / "demonware-server", "Server folder is not beside its executable");
        auto elsewhere = parse_config("[server]\nexecutable = tools/demonware-server.exe\n", root);
        require(elsewhere.server_dir == root / "tools" / "demonware-server", "Server folder does not follow its executable");
        auto unlocked = parse_config("[server]\nunlock_all = true\n", root);
        require(unlocked.unlock_all && unlocked.server_dir == c.server_dir && unlocked.state == c.state,
                "Economy mode selected different storage");
        require(unlocked.realm == c.realm && unlocked.title == c.title && unlocked.build == c.build, "Economy entered discovery namespace");
        auto lab = parse_config("[lab]\nenabled = true\naccount_id = 7\nroot = hub\nonline_id = \"Lab ; # A\"\n", root);
        require(lab.lab && lab.online_id == "Lab ; # A" && lab.lab_account == 7, "Lab identity lost");
        require(ascii_name("  A !.{};B  ") == "A !.{};B", "Printable ASCII lost");
        require(ascii_name("\xc3\xa8\xf0\x9f\x98\x80" "ABCDEFGHIJKLMNO") == "__ABCDEFGHIJKLMN", "UTF8 mapping/truncation order incorrect");
        require(ascii_name("  ab  ") == "ab", "Host-only NP sanitization leaked into provider name");
        require(ascii_name("\tA\n") == "_A_", "Control characters entered environment");
        rejects([] { ascii_name("   "); });
        for (auto text : {"[unknown]\nx=1", "[server]\nwat=1", "[server]\nunlock_all=1", "[steam]\napp_id=0", "[steam]\napp_id=-1",
                          "[steam]\napp_id=4294967296", "[server]\nunlock_all=true\nunlock_all=false", "[server]\n[server]",
                          "[game]\nhost=shadps4", "[platform]\nprovider=shadnet", "[network]\naddress=0.0.0.0",
                          "[network]\naddress=127.00.0.2", "[network]\naddress=127.0.0.1", "[network]\nhttp_port=8460",
                          "[network]\nhttp_port=3076", "[lab]\nenabled=true", "[lab]\naccount_id=1", "[lab]\nonline_id=Alice",
                          "[steam]\nlibrary=../elsewhere.dll",
                          // Removed settings stay removed: no aliases.
                          "[player]\nonline_id=Alice", "[player]\nunlock_all=true", "[publisher]\nexecutable=x",
                          "[server]\nweak_admission=true", "[server]\nsigning_key=key.pem", "[game]\nexecutable=x",
                          "[game]\ngame_dir=x", "[game]\nsaves_dir=user", "[game]\nprepared_dir=x", "[game]\npatches_dir=x",
                          "[game]\nprofile=ctr", "[game]\nprofile_dir=x", "[game]\nport_dir=x", "[game]\nconfig=x",
                          "[session]\ntitle=5760", "[session]\nbuild=01.21", "[network]\nserver=127.0.0.2",
                          "[network]\nauth_port=8460", "[network]\ngame_address=127.0.0.1", "[network]\ngame_port=3098"})
            rejects([&] { parse_config(text, root); });
        auto parsed = parse_config("[session]\nrealm = private-group ; comment\n[steam]\napp_id=12345 ; private fixture\n", root);
        require(parsed.realm == "private-group" && parsed.app_id == 12345, "Comments broken");
        require(loopback_address("127.255.255.254") && !loopback_address("128.0.0.1"), "Loopback parser incorrect");

        auto request = parse_request_head("POST /v1/sessions?x=1 HTTP/1.1\r\nHost: sessionInvitation.np.community.playstation.net\r\nContent-Type: application/octet-stream\r\nContent-Length: 3\r\nX-SacredFire-Scheme: https\r\n\r\n");
        require(request.path == "/v1/sessions?x=1" && request.method == "POST", "Request metadata lost");
        require(api_group(header(request.headers, "host")) == "sessioninvitation", "API group route wrong");
        require(api_group("sdk:userProfile.np.community.playstation.net") == "userprofile", "Native SDK authority was routed to server");
        require(api_group("sdk:sessionInvitation.np.community.playstation.net:443") == "sessioninvitation", "SDK authority with explicit port misrouted");
        require(api_group("userProfile.np.community.playstation.net:443") == "userprofile", "Platform authority with port misrouted");
        for (auto host : {"sdk:publisher.invalid", "sdk:userProfile.np.community.playstation.net.evil", "sdk:sdk:userProfile.np.community.playstation.net", "userProfile.np.community.playstation.net:evil", "userProfile.np.community.playstation.net:443:80"})
            rejects([&] { api_group(host); });
        require(api_group("session.np.community.playstation.net.evil") == "", "Suffix routing escaped");
        require(api_group("publisher.invalid") == "", "Server request misrouted");
        for (auto text : {
            "GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n",
            "GET http://external/ HTTP/1.1\r\nHost: a\r\n\r\n", "GET / HTTP/1.1\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\n folded: bad\r\n\r\n"}) rejects([&] { parse_request_head(text); });

        // Online identity and application association; native settings pass through.
        auto named = c; named.online_id = "Alice";
        std::map<std::string, std::string> inherited = {
            {"PATH", "fixture-path"}, {"BB_DATA_DIR", "native-data"}, {"BB_NEO", "1"},
            {"BB_ONLINE_SERVER", "203.0.113.9"}, {"BB_ONLINE_ALLOW", "203.0.113.9"}, {"CTR_UNLOCK_ALL", "1"},
            {"OSW_STALE", "x"}, {"STEAMAPPID", "1"}, {"STEAMGAMEID", "2"},
            {"SteamAppId", "3"}, {"SteamGameId", "4"}};
#ifdef _WIN32
        inherited["bb_user_name"] = "stale"; inherited["bb_online_id"] = "stale";
#endif
        auto env = native_environment(named, 42, inherited);
        require(env.at(environment_key("BB_ONLINE_ACCOUNT_ID")) == "42" && env.at(environment_key("BB_ONLINE_ID")) == "Alice" &&
                env.at(environment_key("BB_USER_NAME")) == "Alice", "Identity mapping wrong");
        require(env.at(environment_key("BB_ONLINE_SERVER")) == "127.0.0.2" && env.at(environment_key("BB_ONLINE_HTTP_PORT")) == "31380" &&
                env.at(environment_key("BB_ONLINE_ALLOW")) == "127.0.0.1", "Online routing wrong");
        require(env.at(environment_key("BB_DATA_DIR")) == "native-data" && env.at(environment_key("BB_NEO")) == "1" &&
                env.at(environment_key("PATH")) == "fixture-path", "Native settings were not passed through");
        require(!env.contains(environment_key("CTR_UNLOCK_ALL")) && !env.contains(environment_key("OSW_STALE")),
                "Private inheritance leaked");
        require(env.at(environment_key("SteamAppId")) == "480" && env.at(environment_key("SteamGameId")) == "480",
                "Native renderer lost the default Steam application association");
        auto custom_app = named; custom_app.app_id = 12345;
        auto octr = parse_config("[game]\nhost=octr", root);
        require(!octr.native_token, "OCTR enabled fabricated-token admission");
        octr.online_id = "Alice";
        rejects([&] { native_environment(octr, 42, inherited); });
        inherited["BB_PSN_BACKEND"] = "stale-adapter";
        inherited["BB_PSN_BACKEND_CONFIG"] = "stale-capability";
        inherited["BB_NET_PRESERVE_ENDPOINTS"] = "0";
        require(!native_environment(named, 42, inherited).contains(environment_key("BB_PSN_BACKEND")), "Native host inherited external backend");
        require(!native_environment(named, 42, inherited).contains(environment_key("BB_NET_PRESERVE_ENDPOINTS")), "Native host inherited OCTR transport policy");
        auto octr_env = native_environment(octr, 42, inherited, std::string(64, 'a'));
        require(octr_env.at(environment_key("BB_ONLINE")) == "1" && octr_env.at(environment_key("BB_ONLINE_TUNNEL")) == "0", "OCTR local route not selected");
        require(octr_env.at(environment_key("BB_NET_PRESERVE_ENDPOINTS")) == "1", "OCTR endpoint preservation not selected");
        require(fs::u8path(octr_env.at(environment_key("BB_PSN_BACKEND"))) == root / "psn-bridge-backend.dll", "OCTR adapter path wrong");
        require(octr_env.at(environment_key("BB_PSN_BACKEND_CONFIG")).find("stale-capability") == std::string::npos, "OCTR reused stale capability");
        auto psn = parse_config("[game]\nhost=psn", root);
        require(!psn.native_token && psn.uses_psn_backend(), "PSN host enabled fabricated-token admission");
        psn.online_id = "Alice";
        rejects([&] { native_environment(psn, 42, inherited); });
        inherited["BB_ONLINE_TUNNEL"] = "1";
        auto psn_env = native_environment(psn, 42, inherited, std::string(64, 'b'));
        require(fs::u8path(psn_env.at(environment_key("BB_PSN_BACKEND"))) == root / "psn-bridge-backend.dll", "PSN adapter path wrong");
        require(psn_env.at(environment_key("BB_PSN_BACKEND_CONFIG")).find(std::string(64, 'b')) != std::string::npos, "PSN host lost fresh capability");
        require(psn_env.at(environment_key("BB_ONLINE_SERVER")) == c.address &&
                psn_env.at(environment_key("BB_ONLINE_HTTP_PORT")) == "31380", "PSN publisher routing changed");
        require(!psn_env.contains(environment_key("BB_ONLINE_TUNNEL")) &&
                !psn_env.contains(environment_key("BB_NET_PRESERVE_ENDPOINTS")), "PSN host inherited OCTR transport switches");
        auto custom_env = native_environment(custom_app, 42, inherited);
        require(custom_env.at(environment_key("SteamAppId")) == "12345" && custom_env.at(environment_key("SteamGameId")) == "12345",
                "Native Steam association differs from the configured provider AppID");
        auto lab_env = native_environment(lab, 42, inherited);
        for (auto key : {"SteamAppId", "SteamGameId", "STEAMAPPID", "STEAMGAMEID"})
            require(!lab_env.contains(environment_key(key)), "Simulated Lab inherited a Steam application association");
        for (auto name : {"BB_USER_DIR", "BB_GAME_DIR", "BB_CONFIG", "BB_FPS", "BB_TIMEOUT", "BB_PATCHES_DIR", "BB_GAME_PROFILE"})
            require(!env.contains(environment_key(name)), "Bridge set a native path or preference");
        size_t names = 0;
        for (const auto& [key, value] : env) if (environment_key(key) == environment_key("BB_USER_NAME")) ++names;
        require(names == 1, "Differently cased environment names survived");
        rejects([&] { native_environment(c, 42, {}); });
        rejects([&] { native_environment(named, 0, {}); });

        require(signature_patch_problem(patch_xml, selected).empty(), "Supported signature patch refused");
        require(signature_patch_problem(replaced(patch_xml, " AppElf=\"eboot.bin\"", ""), selected).empty(), "Default AppElf refused");
        require(signature_patch_problem(replaced(patch_xml, "<ID>CUSA13795</ID>", "<ID>  CUSA13795\n</ID>"), selected).empty(),
                "Title ID whitespace refused");
        require(signature_patch_problem(replaced(patch_xml, "Name=\"CTR:NF Server Signature Patch\"",
                "Name = 'CTR:NF Server Signature Patch'"), selected).empty(), "Valid XML attribute quoting refused");
        require(signature_patch_problem(replaced(patch_xml, "Name=\"CTR:NF Server Signature Patch\"",
                "Name=\"CTR:NF Server Signature Patc&#104;\""), selected).empty(), "XML character reference refused");
        require(signature_patch_problem(replaced(patch_xml, patch_line, std::string("<!-- explanatory comment -->") + patch_line), selected).empty(),
                "Comment beside a real patch write refused");
        require(signature_patch_problem(replaced(patch_xml, "<ID>CUSA13795</ID>", "<ID><![CDATA[CUSA13795]]></ID>"), selected).empty(),
                "Real title ID text inside CDATA refused");
        for (auto [xml, selection] : std::initializer_list<std::pair<std::string, std::string>>{
                 {patch_xml, "{}"}, {patch_xml, "[]"}, {patch_xml, R"({"enabled": []})"},
                 {patch_xml, R"({"enabled": ["CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch"], "disabled": ["CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch"]})"},
                 {replaced(patch_xml, "CUSA13795", "CUSA00000"), selected},
                 {replaced(patch_xml, "AppVer=\"01.21\"", "AppVer=\"01.20\""), selected},
                 {replaced(patch_xml, "AppElf=\"eboot.bin\"", "AppElf=\"other.prx\""), selected},
                 {replaced(patch_xml, "0x00413ec0", "0x00413ec4"), selected},
                 {replaced(patch_xml, "909090909090", "90909090"), selected},
                 {replaced(patch_xml, "Type=\"bytes\"", "Type=\"bytes16\""), selected},
                 {replaced(patch_xml, "Name=\"CTR:NF Server Signature Patch\"", "Name=\"Other\""), selected},
                 {replaced(patch_xml, "</Metadata>", ""), selected}})
            require(!signature_patch_problem(xml, selection).empty(), "Unsupported signature patch accepted");
        // A literal match is not a native patch: comments and CDATA are not
        // elements, and a later parse error invalidates the entire document.
        for (const auto& [description, xml] : std::initializer_list<std::pair<const char*, std::string>>{
                 {"Commented patch write accepted", replaced(patch_xml, patch_line, std::string("<!--") + patch_line + "-->")},
                 {"CDATA patch write accepted", replaced(patch_xml, patch_line, std::string("<![CDATA[") + patch_line + "]]>")},
                 {"Line-prefixed element accepted", replaced(patch_xml, "<Line ", "<LineIgnored ")},
                 {"Commented Metadata accepted", replaced(replaced(patch_xml, "<Metadata ", "<!--<Metadata "), "</Metadata>", "</Metadata>-->")},
                 {"Commented title ID accepted", replaced(patch_xml, "<ID>CUSA13795</ID>", "<!--<ID>CUSA13795</ID>--><ID>CUSA00000</ID>")},
                 {"CDATA title markup accepted", replaced(patch_xml, "<ID>CUSA13795</ID>", "<![CDATA[<ID>CUSA13795</ID>]]><ID>CUSA00000</ID>")},
                 {"Mismatched closing tag accepted", replaced(patch_xml, "</Patch>", "</Wrong>")},
                 {"Trailing second root accepted", std::string(patch_xml) + "<Other/>"},
                 {"Trailing unterminated comment accepted", std::string(patch_xml) + "<!--"},
                 {"Duplicate XML attributes accepted", replaced(patch_xml, "AppVer=\"01.21\"", "AppVer=\"01.21\" AppVer=\"01.20\"")},
                 {"Undefined XML entity accepted", replaced(patch_xml, "Note=\"fixture\"", "Note=\"&undefined;\"")},
                 {"Invalid XML character reference accepted", replaced(patch_xml, "Note=\"fixture\"", "Note=\"&#0;\"")},
                 {"XML NUL suffix accepted", std::string(patch_xml) + std::string(1, '\0')},
                 {"Namespaced patch elements accepted", replaced(patch_xml, "<Patch>", "<Patch xmlns=\"urn:unrecognized\">")},
                 {"Unbound namespace prefix accepted", replaced(patch_xml, "<Patch>", "<Patch missing:attribute=\"x\">")},
                 {"Unsupported additional Line accepted", replaced(patch_xml, "</PatchList>", "<Line Type=\"mask\" Address=\"0x00413ec0\" Value=\"90\"/></PatchList>")},
                 {"Overwriting additional Line accepted", replaced(patch_xml, "</PatchList>", "<Line Type=\"bytes\" Address=\"0x00413ec0\" Value=\"00\"/></PatchList>")},
                 {"Signature-relocated write accepted", replaced(patch_xml, "Type=\"bytes\"", "Type=\"bytes\" Signature=\"00 11\"")},
                 {"DTD document accepted", replaced(patch_xml, "<Patch>", "<!DOCTYPE Patch><Patch>")},
                 {"Entity-declaring DTD accepted", replaced(patch_xml, "<Patch>", "<!DOCTYPE Patch [<!ENTITY ignored 'text'>]><Patch>")},
                 {"External DTD accepted", replaced(patch_xml, "<Patch>", "<!DOCTYPE Patch SYSTEM 'file:///nonexistent-bridge-fixture'><Patch>")},
                 {"Oversized XML accepted", std::string(patch_xml) + std::string(1048576, ' ')}})
            require(!signature_patch_problem(xml, selected).empty(), description);
        rejects([&] { signature_patch_problem(patch_xml, R"({"enabled": "CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch"})"); });
        std::cout << checks << " bridge contract checks passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
