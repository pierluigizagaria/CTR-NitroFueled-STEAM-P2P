#include "config.h"
#include "host.h"
#include "http.h"
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
}
int main() {
    using namespace bridge;
    try {
        auto root = fs::absolute("fixture-root");
        auto normal = parse_config("[player]\nonline_id = Alice\nunlock_all = false\n", root);
        auto unlocked = parse_config("[player]\nonline_id = Alice\nunlock_all = true\n", root);
        require(normal.app_id == 480 && !normal.weak_admission && !normal.lab, "Defaults changed");
        require(normal.saves != unlocked.saves && normal.data != unlocked.data, "Economy storage is shared");
        require(normal.realm == unlocked.realm && normal.title == unlocked.title && normal.build == unlocked.build, "Economy entered discovery namespace");
        require(ascii_name("  A !.{};B  ") == "A !.{};B", "Printable ASCII lost");
        require(ascii_name("\xc3\xa8\xf0\x9f\x98\x80" "ABCDEFGHIJKLMNO") == "__ABCDEFGHIJKLMN", "UTF8 mapping/truncation order incorrect");
        require(ascii_name("  ab  ") == "ab", "Host-only NP sanitization leaked into provider name");
        require(ascii_name("\tA\n") == "_A_", "Control characters entered environment");
        rejects([] { ascii_name("   "); });
        for (auto text : {"[unknown]\nx=1", "[player]\nwat=1", "[player]\nunlock_all=1", "[steam]\napp_id=0", "[steam]\napp_id=-1", "[steam]\napp_id=4294967296", "[player]\nunlock_all=true\nunlock_all=false", "[player]\n[player]", "[game]\nhost=shadps4", "[platform]\nprovider=shadnet", "[network]\nserver=0.0.0.0", "[network]\nserver=127.00.0.1", "[network]\nhttp_port=8460", "[lab]\nenabled=true", "[lab]\naccount_id=1", "[steam]\nlibrary=../elsewhere.dll"})
            rejects([&] { parse_config(text, root); });
        auto parsed = parse_config("[player]\nonline_id = \"A ; # B\"\n[steam]\napp_id=12345 ; private fixture\n", root);
        require(parsed.online_id == "A ; # B" && parsed.app_id == 12345, "Quoted names or comments broken");
        require(loopback_address("127.255.255.254") && !loopback_address("128.0.0.1"), "Loopback parser incorrect");
        auto request = parse_request_head("POST /v1/sessions?x=1 HTTP/1.1\r\nHost: sessionInvitation.np.community.playstation.net\r\nContent-Type: application/octet-stream\r\nContent-Length: 3\r\nX-SacredFire-Scheme: https\r\n\r\n");
        require(request.path == "/v1/sessions?x=1" && request.method == "POST", "Request metadata lost");
        require(api_group(header(request.headers, "host")) == "sessioninvitation", "API group route wrong");
        require(api_group("sdk:userProfile.np.community.playstation.net") == "userprofile", "Native SDK authority was routed to publisher");
        require(api_group("sdk:sessionInvitation.np.community.playstation.net:443") == "sessioninvitation", "SDK authority with explicit port misrouted");
        require(api_group("userProfile.np.community.playstation.net:443") == "userprofile", "Platform authority with port misrouted");
        for (auto host : {"sdk:publisher.invalid", "sdk:userProfile.np.community.playstation.net.evil", "sdk:sdk:userProfile.np.community.playstation.net", "userProfile.np.community.playstation.net:evil", "userProfile.np.community.playstation.net:443:80"})
            rejects([&] { api_group(host); });
        require(api_group("session.np.community.playstation.net.evil") == "", "Suffix routing escaped");
        require(api_group("publisher.invalid") == "", "Publisher misrouted");
        for (auto text : {
            "GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n",
            "GET http://external/ HTTP/1.1\r\nHost: a\r\n\r\n", "GET / HTTP/1.1\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\n folded: bad\r\n\r\n"}) rejects([&] { parse_request_head(text); });
        auto env = native_environment(normal, 42);
        require(env.at("BB_ONLINE_ACCOUNT_ID") == "42" && env.at("BB_ONLINE_ID") == "Alice", "Identity mapping wrong");
        require(env.at("BB_USER_DIR") == env.at("BB_GPU_USER_DIR"), "Save/cache roots differ");
        auto custom_profile = parse_config("[player]\nonline_id = Alice\n[game]\nprofile = fixture-other-title\n", root);
        require(native_environment(custom_profile, 42).at("BB_GAME_PROFILE") == "fixture-other-title", "Configured host profile was ignored");
        auto args = native_arguments(normal);
        require(args[args.size() - 2] == "--timeout" && args.back() == "0", "Native default time cutoff not disabled");
        require(!env.contains("BB_OSW_LIBRARY") && !env.contains("BB_ONLINE_BIND"), "Modified-host settings leaked");
        rejects([&] { parse_config("[game]\nunlock_all_saves=runtime/player/normal/user", root); });
        rejects([&] { parse_config("[game]\nnormal_saves=runtime/player/unlock-all", root); });
        std::cout << checks << " bridge contract checks passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
