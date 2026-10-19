// Independent public-ABI fixture. This does not call Steam or start a publisher.
#include <orbisteamworks/osw.h>
#include <nlohmann/json.hpp>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <vector>
#ifdef _WIN32
#define TEST_EXPORT extern "C"
#else
#define TEST_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {
using Json = nlohmann::json;
void record(const Json& entry) {
    if (const auto path = std::getenv("TEST_PROVIDER_LOG"))
        std::ofstream(path, std::ios::app) << entry.dump() << '\n';
}
struct Result {
    int32_t status = OSW_OK;
    int32_t http_status = 200;
    std::string metadata, body;
};
}

struct osw_context {
    osw_config_v2 config{};
    bool started = false, loopback = false, endpoint_pending = false;
    uint32_t app_id = 480;
    uint64_t next_request = 1;
    unsigned bound_readiness_reads = 0;
    bool room_active = false;
    unsigned directory_searches = 0;
    std::map<uint64_t, Result> results;
};

TEST_EXPORT int32_t osw_create(const osw_config*, osw_context**) { return OSW_NOT_SUPPORTED; }
TEST_EXPORT int32_t osw_create_v2(const osw_config_v2* config, osw_context** output) {
    if (!config || !output || config->base.size != sizeof(*config) || config->base.abi_version != OSW_ABI_VERSION_2)
        return OSW_INVALID_ARGUMENT;
    auto context = new osw_context;
    context->config = *config;
    *output = context;
    record({{"event", "create"}, {"online_id", config->base.online_id},
            {"title", config->base.title}, {"build", config->base.build},
            {"realm", config->base.realm}, {"backend", config->backend},
            {"game_bind", config->game_bind}, {"game_port", config->game_port},
            {"companion", config->companion_path[0] != 0},
            {"companion_environment", Json::parse(config->companion_environment[0] ? config->companion_environment : "{}")}});
    return OSW_OK;
}
TEST_EXPORT int32_t osw_set_app_id(osw_context* c, uint32_t id) {
    if (!c || c->started || !id) return OSW_INVALID_ARGUMENT;
    c->app_id = id; record({{"event", "appid"}, {"value", id}}); return OSW_OK;
}
TEST_EXPORT int32_t osw_enable_loopback_endpoints(osw_context* c) {
    if (!c || c->started) return OSW_INVALID_ARGUMENT;
    c->loopback = true; record({{"event", "loopback"}}); return OSW_OK;
}
TEST_EXPORT int32_t osw_enable_virtual_endpoints(osw_context*) { return OSW_NOT_SUPPORTED; }
TEST_EXPORT int32_t osw_defer_game_endpoint(osw_context* c) {
    if (!c || c->started || !c->loopback || !c->config.companion_path[0]) return OSW_INVALID_ARGUMENT;
    c->endpoint_pending = true; record({{"event", "defer_endpoint"}}); return OSW_OK;
}
TEST_EXPORT int32_t osw_get_local_endpoint(osw_context*, osw_endpoint*) { return OSW_NOT_SUPPORTED; }
TEST_EXPORT int32_t osw_route_endpoint(osw_context*, uint32_t, const osw_endpoint*, osw_endpoint*) { return OSW_NOT_SUPPORTED; }
TEST_EXPORT int32_t osw_start(osw_context* c) {
    if (!c || !c->loopback || c->started) return OSW_INVALID_ARGUMENT;
    record({{"event", "start"}});
    if (std::getenv("TEST_PROVIDER_FAIL_START")) return OSW_UNAVAILABLE;
    c->started = true; return OSW_OK;
}
TEST_EXPORT int32_t osw_get_identity(osw_context* c, osw_identity* out) {
    if (!c || !out || out->size != sizeof(*out)) return OSW_INVALID_ARGUMENT;
    *out = {}; out->size = sizeof(*out); out->signed_in = c->started;
    out->account_id = c->config.lab_account_id ? c->config.lab_account_id : 123456789;
    const std::string name = c->config.base.online_id[0] ? c->config.base.online_id : "Fixture";
    std::memcpy(out->online_id, name.c_str(), name.size() + 1);
    return OSW_OK;
}
#ifndef TEST_MISSING_PERSONA_SYMBOL
TEST_EXPORT int32_t osw_get_persona_name(osw_context* c, char* buffer, size_t capacity, size_t* required) {
    if (!c || !required) return OSW_INVALID_ARGUMENT;
    const std::string name = "  Fixture \xc3\xa9!  ";
    *required = name.size() + 1;
    if (!buffer || capacity < *required) return OSW_LIMIT;
    std::memcpy(buffer, name.c_str(), *required); return OSW_OK;
}
#endif
TEST_EXPORT int32_t osw_submit(osw_context* c, const osw_request* request, uint64_t* id) {
    if (!c || !request || !id || request->size != sizeof(*request)) return OSW_INVALID_ARGUMENT;
    auto metadata = Json::parse(request->metadata, request->metadata + request->metadata_size, nullptr, false);
    if (!metadata.is_object()) return OSW_INVALID_ARGUMENT;
    Result value;
    if (request->operation == OSW_P2P && metadata.value("op", "") == "status") {
        // Registration confirmation and one subsequent health poll succeed.
        // Fail a later health poll with identity deliberately still signed in.
        bool ready = !std::getenv("TEST_PROVIDER_DROP_READY") || c->endpoint_pending || c->bound_readiness_reads < 2;
        if (!c->endpoint_pending) ++c->bound_readiness_reads;
        value.metadata = Json({{"ready", ready}, {"game_endpoint_pending", c->endpoint_pending}}).dump();
    } else if (request->operation == OSW_P2P && metadata.value("op", "") == "game.endpoint.bind") {
        if (!c->endpoint_pending || metadata.value("address", "") != "127.0.0.1" ||
            !metadata.contains("port") || !metadata["port"].is_number_unsigned() ||
            metadata["port"].get<uint64_t>() == 0 || metadata["port"].get<uint64_t>() > 65535)
            value.status = OSW_INVALID_ARGUMENT;
        else if (std::getenv("TEST_ENDPOINT_REJECT")) value.status = OSW_UNAVAILABLE;
        else c->endpoint_pending = false;
        record({{"event", "bind_endpoint"}, {"address", metadata.value("address", "")},
                {"port", metadata.value("port", 0)}, {"status", value.status}});
        value.metadata = "{}";
    } else if (request->operation == OSW_P2P && metadata.value("op", "").starts_with("directory.")) {
        if (c->endpoint_pending) return OSW_UNAVAILABLE;
        // Only the documented OSW_P2P directory protocol is simulated here.
        const auto operation = metadata.value("op", "");
        const auto configured_failure = std::getenv("TEST_DIRECTORY_FAILURE");
        const std::string failure = configured_failure ? configured_failure : "";
        const std::string room_id = "987654321";
        const auto owner = std::to_string(c->config.lab_account_id ? c->config.lab_account_id : 123456789);
        const Json room = {{"room_id", room_id}, {"owner", owner}, {"members", Json::array({owner})}, {"metadata", Json::object()}};
        if (operation == "directory.create") {
            if (c->room_active || metadata.value("capacity", 0) != 2 || !metadata.contains("metadata") || !metadata["metadata"].is_object())
                value.status = OSW_INVALID_ARGUMENT;
            else { c->room_active = true; value.metadata = room.dump(); }
        } else if (operation == "directory.search") {
            if (failure == "search") value.status = OSW_UNAVAILABLE;
            else {
                // Discovery can lag creation; a successful diagnostic must wait.
                const auto rooms = c->room_active && c->directory_searches++ > 0 ? Json::array({room}) : Json::array();
                value.metadata = Json({{"rooms", rooms}}).dump();
            }
        } else if (!c->room_active || metadata.value("room_id", "") != room_id) {
            value.status = OSW_NOT_FOUND;
        } else if (operation == "directory.members") {
            if (failure == "read") value.status = OSW_UNAVAILABLE;
            else value.metadata = room.dump();
        } else if (operation == "directory.leave") {
            c->room_active = false; value.metadata = "{}";
        } else value.status = OSW_NOT_SUPPORTED;
        if (value.status != OSW_OK) value.metadata = R"({"error":"fixture_directory_failure"})";
        record({{"event", "directory"}, {"op", operation}, {"status", value.status}});
    } else if (request->operation == OSW_WEBAPI && metadata.value("path", "") == "/fixture-ready") {
        value.http_status = c->endpoint_pending ? 503 : 204;
        value.metadata = R"({"content_type":"application/json"})";
    } else if (request->operation == OSW_WEBAPI && metadata.value("path", "").starts_with("/fixture")) {
        std::vector<uint8_t> bytes;
        if (request->body_size) bytes.assign(request->body, request->body + request->body_size);
        value.metadata = R"({"content_type":"application/vnd.bridge-fixture+json"})";
        value.http_status = 201;
        value.body = Json({{"metadata", metadata}, {"body_bytes", bytes}}).dump();
        record({{"event", "webapi"}, {"metadata", metadata}, {"body_size", request->body_size}});
    } else {
        value.status = OSW_NOT_SUPPORTED; value.http_status = 501;
        value.metadata = R"({"content_type":"application/json"})";
        value.body = R"({"error":"unsupported_fixture_operation"})";
    }
    *id = c->next_request++; c->results.emplace(*id, std::move(value)); return OSW_OK;
}
TEST_EXPORT int32_t osw_get_result(osw_context* c, uint64_t id, osw_result* out) {
    if (!c || !out || out->size != sizeof(*out)) return OSW_INVALID_ARGUMENT;
    auto item = c->results.find(id);
    if (item == c->results.end()) return OSW_NOT_FOUND;
    const auto& value = item->second;
    out->status = value.status; out->http_status = value.http_status;
    out->metadata = value.metadata.data(); out->metadata_size = value.metadata.size();
    out->body = reinterpret_cast<const uint8_t*>(value.body.data()); out->body_size = value.body.size();
    return OSW_OK;
}
TEST_EXPORT int32_t osw_cancel(osw_context* c, uint64_t id) {
    if (!c || !c->results.contains(id)) return OSW_NOT_FOUND;
    c->results[id].status = OSW_ABORTED; return OSW_OK;
}
TEST_EXPORT int32_t osw_release(osw_context* c, uint64_t id) {
    return c && c->results.erase(id) ? OSW_OK : OSW_NOT_FOUND;
}
TEST_EXPORT int32_t osw_poll_event(osw_context*, osw_event*) { return OSW_PENDING; }
TEST_EXPORT int32_t osw_stop(osw_context* c) {
    if (!c) return OSW_INVALID_ARGUMENT;
    c->started = false; record({{"event", "stop"}, {"room_active", c->room_active}}); return OSW_OK;
}
TEST_EXPORT void osw_destroy(osw_context* c) { record({{"event", "destroy"}}); delete c; }
