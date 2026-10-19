#include "psn.h"
#include <cstring>
#include <iostream>
#include <stdexcept>

using namespace bridge;
using Json = nlohmann::json;
namespace {
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
struct Fixture {
    osw_identity identity{};
    std::deque<std::string> events;
    Reply reply{OSW_OK, 201, {{"content_type", "application/octet-stream"}}, std::string("A\0\xff", 3)};
    Json metadata;
    std::string body;
    uint32_t operation = 0;
    unsigned requests = 0;
    bool fail = false;
    Fixture() {
        identity.size = sizeof(identity); identity.account_id = UINT64_C(76561198012345678); identity.signed_in = 1;
        std::strcpy(identity.online_id, "Fixture");
    }
    PsnServices services() {
        return {[this] { return identity; }, [this](uint32_t op, const Json& meta, const std::string& bytes) {
                    ++requests; operation = op; metadata = meta; body = bytes; return reply;
                }, [this]() -> std::optional<std::string> {
                    if (fail) throw std::runtime_error("fixture failure");
                    if (events.empty()) return std::nullopt;
                    auto value = events.front(); events.pop_front(); return value;
                }};
    }
};
const std::string capability(64, 'a');
HttpRequest request(std::string path, std::string method = "GET", Json body = nullptr) {
    return {std::move(method), std::move(path), {{"Authorization", "Bearer " + capability}}, body.is_null() ? "" : body.dump()};
}
Json event(unsigned index) {
    return {{"version", 1}, {"kind", "invitationAccepted"}, {"sessionId", std::to_string(index)},
        {"from", {{"accountId", "76561198012345679"}, {"onlineId", "Friend"}}},
        {"to", {{"accountId", "76561198012345678"}, {"onlineId", "Fixture"}}}, {"invitationId", "inv-123"}};
}
}
int main() {
    try {
        Fixture fixture;
        PsnRelay relay(fixture.services(), capability);
        auto missing = request("/psn/v1/info"); missing.headers.clear();
        require(relay.handle(missing).status == 403, "Unauthenticated relay access accepted");
        auto browser = request("/psn/v1/info"); browser.headers.emplace_back("Origin", "https://example.invalid");
        require(relay.handle(browser).status == 403, "Browser-origin relay access accepted");
        auto info = Json::parse(relay.handle(request("/psn/v1/info")).body);
        require(info["accountId"] == "76561198012345678" && info["version"] == 1, "Identity lost uint64 precision");
        require(relay.handle(request("/psn/v2/info")).status == 404, "Unknown protocol accepted");
        require(relay.handle(request("/psn/v1/events?after=1")).status == 409, "Unsent cursor acknowledged");
        fixture.events.push_back(event(10).dump());
        auto first = relay.handle(request("/psn/v1/events?after=0"));
        auto retry = relay.handle(request("/psn/v1/events?after=0"));
        require(first.status == 200 && first.body == retry.body, "Lost response consumed invitation");
        auto batch = Json::parse(first.body);
        require(batch["events"][0]["sequence"] == 1 && batch["events"][0]["event"] == event(10), "Relay changed provider event");
        fixture.events.push_back(event(20).dump());
        auto second = Json::parse(relay.handle(request("/psn/v1/events?after=1")).body);
        require(second["events"].size() == 1 && second["events"][0]["sequence"] == 2, "ACK did not retire old invitation");
        require(relay.handle(request("/psn/v1/events?after=0")).status == 409, "Expired cursor silently restarted");
        require(relay.handle(request("/psn/v1/events?after=-1")).status == 400, "Negative cursor accepted");
        require(relay.handle(request("/psn/v1/events?after=2&extra=1")).status == 400, "Extra cursor input accepted");
        auto empty = Json::parse(relay.handle(request("/psn/v1/events?after=2")).body);
        require(empty["events"].empty(), "Acknowledged invitation replayed");

        fixture.reply.body = "osw-local-fixture";
        auto token = Json::parse(relay.handle(request("/psn/v1/token", "POST", {{"kind", 1}, {"client_id", "fixture"}, {"scope", "openid"}})).body);
        require(token["token"] == "osw-local-fixture" && fixture.operation == OSW_TOKEN && !fixture.metadata.contains("server_id"), "Companion capability not forwarded");
        unsigned count = fixture.requests;
        auto unsupported = Json::parse(relay.handle(request("/psn/v1/token", "POST", {{"kind", 2}})).body);
        require(unsupported["status"] == OSW_NOT_SUPPORTED && count == fixture.requests, "Unsupported auth code fabricated");
        fixture.reply.status = OSW_SIGNED_OUT;
        auto failed = Json::parse(relay.handle(request("/psn/v1/token", "POST", {{"kind", 1}, {"client_id", "fixture"}, {"scope", "openid"}})).body);
        require(failed["status"] == OSW_SIGNED_OUT && failed["token"] == "", "Failed token payload leaked");
        fixture.reply = {OSW_OK, 201, {{"content_type", "application/octet-stream"}}, std::string("A\0\xff", 3)};
        Json web = {{"method", "PATCH"}, {"api_group", "sessionInvitation"}, {"path", "/v1/sessions/123/sessionData?x=1"},
            {"content_type", "application/octet-stream"}, {"headers", {{"X-Test", "kept"}}}, {"bodyHex", "4100ff"}};
        auto response = Json::parse(relay.handle(request("/psn/v1/webapi", "POST", web)).body);
        require(response["bodyHex"] == "4100ff" && response["httpStatus"] == 201 && fixture.body == std::string("A\0\xff", 3), "Binary WebAPI data changed");
        require(fixture.metadata["path"] == web["path"] && fixture.metadata["headers"] == web["headers"], "WebAPI metadata changed");
        web["headers"]["x-test"] = "duplicate";
        require(relay.handle(request("/psn/v1/webapi", "POST", web)).status == 400, "Duplicate header folded silently");
        web["headers"] = Json::object(); web["bodyHex"] = "zz";
        require(relay.handle(request("/psn/v1/webapi", "POST", web)).status == 400, "Invalid binary encoding accepted");
        web["bodyHex"] = std::string(2 * 256 * 1024 + 2, '0');
        require(relay.handle(request("/psn/v1/webapi", "POST", web)).status == 400, "Oversized binary request accepted");
        web["bodyHex"] = ""; web["path"] = "//remote.invalid/path";
        require(relay.handle(request("/psn/v1/webapi", "POST", web)).status == 400, "Absolute URL path accepted");

        fixture.fail = true;
        require(relay.handle(request("/psn/v1/events?after=2")).status == 503, "Provider stream failure hidden");
        fixture.fail = false;
        require(relay.handle(request("/psn/v1/events?after=2")).status == 503, "Broken notification stream silently resumed");
        ++fixture.identity.account_id;
        require(relay.handle(request("/psn/v1/info")).status == 503, "Account change reused session capability");
        Fixture overflow; PsnRelay bounded(overflow.services(), capability);
        for (unsigned i = 0; i < 513; ++i) overflow.events.push_back(event(i).dump());
        for (unsigned i = 0; i < 8; ++i)
            require(bounded.handle(request("/psn/v1/events?after=0")).status == 200, "Queue failed before documented bound");
        require(bounded.handle(request("/psn/v1/events?after=0")).status == 503, "Unacknowledged queue overflow lost invitations silently");
        std::cout << "PSN relay authentication, replay, binary forwarding and failure contracts passed.\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
