#include "provider.h"
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <thread>

namespace bridge {
namespace {
template<size_t N> void copy(char (&dest)[N], const std::string& value) {
    if (value.size() >= N || value.find('\0') != value.npos) throw std::runtime_error("Provider configuration field exceeds ABI bound");
    std::memcpy(dest, value.data(), value.size()); dest[value.size()] = 0;
}
void check(int code, const char* operation) {
    if (code != OSW_OK) throw std::runtime_error(std::string(operation) + " failed (provider status " + std::to_string(code) + ")");
}
}
Provider::Provider(const Config& c, bool companion) : library_(c.provider_library) {
#define RESOLVE(member, name) member = reinterpret_cast<decltype(member)>(library_.symbol(name))
    RESOLVE(create_, "osw_create_v2"); RESOLVE(start_, "osw_start"); RESOLVE(stop_, "osw_stop");
    RESOLVE(destroy_, "osw_destroy"); RESOLVE(identity_, "osw_get_identity"); RESOLVE(submit_, "osw_submit");
    RESOLVE(result_, "osw_get_result"); RESOLVE(cancel_, "osw_cancel"); RESOLVE(release_, "osw_release");
    RESOLVE(poll_, "osw_poll_event"); RESOLVE(loopback_, "osw_enable_loopback_endpoints");
    RESOLVE(appid_, "osw_set_app_id"); RESOLVE(persona_, "osw_get_persona_name");
    RESOLVE(defer_endpoint_, "osw_defer_game_endpoint");
#undef RESOLVE
    // All symbols used by this current contract are resolved before startup.
    osw_config_v2 config{}; config.base.size = sizeof(config); config.base.abi_version = OSW_ABI_VERSION_2;
    copy(config.base.library_path, path_text(c.steam_library)); copy(config.base.online_id, c.online_id);
    copy(config.base.title, c.title); copy(config.base.build, c.build); copy(config.base.realm, c.realm);
    config.backend = c.lab ? 1 : 0; config.lab_account_id = c.lab_account;
    // ABI v2 requires a nonzero initial port. Deferred mode suppresses this
    // placeholder; only a subsequently confirmed owned socket becomes active.
    config.game_port = 3074;
    copy(config.game_bind, c.game_address); copy(config.lab_root, path_text(c.lab_root));
    if (companion) {
        // The server runs in its own folder and keeps data/ and logs/ there. The
        // host adapter decides native-token admission; the server's own default
        // stays disabled. Replies are unsigned: no key or OpenSSL is involved.
        copy(config.companion_path, path_text(c.server)); copy(config.companion_working_dir, path_text(c.server_dir));
        nlohmann::json env = {
            {"CTR_ADMISSION", "local"}, {"CTR_COMPANION", "stdio"}, {"CTR_MATCHMAKING", "steam"},
            {"CTR_AUTH_HTTP", "1"}, {"CTR_LOCAL_WEAK_TOKEN", c.native_token ? "1" : "0"},
            {"BIND_ADDR", c.address}, {"NEXTENDO_HOST", c.address}, {"AUTH_PORT", std::to_string(server_auth_port)},
            {"LOBBY_PORTS", "3074,3075,3076,3077,3078,3079,3080"}, {"NAT_PORT", "3074"}, {"DASH_PORT", "8093"},
            {"DATA_DIR", path_text(c.server_dir / "data")},
            {"CTR_UNLOCK_ALL", c.unlock_all ? "true" : "false"}, {"NEXTENDO_REDACT_LOGS", "true"},
            {"OSW_COMPANION_STDERR", path_text(c.server_dir / "logs" / "server.log")}
        };
        copy(config.companion_environment, env.dump());
    }
    check(create_(&config, &context_), "Provider creation");
    try {
        check(appid_(context_, c.app_id), "AppID configuration");
        check(loopback_(context_), "Loopback endpoint configuration");
        if (companion) check(defer_endpoint_(context_), "Deferred game endpoint configuration");
        check(start_(context_), "Provider start");
    }
    catch (...) { destroy_(context_); context_ = nullptr; throw; }
}
Provider::~Provider() {
    if (context_) { stop_(context_); destroy_(context_); }
}
osw_identity Provider::identity() {
    std::lock_guard lock(mutex_); osw_identity id{}; id.size = sizeof(id); check(identity_(context_, &id), "Identity read"); return id;
}
osw_identity Provider::wait_identity() {
    auto end = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    osw_identity last{};
    while (std::chrono::steady_clock::now() < end) {
        last = identity(); if (last.signed_in && last.account_id) return last;
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }
    throw std::runtime_error("Provider did not sign in (reason code " + std::to_string(last.reason_code) + ")");
}
std::string Provider::persona() {
    std::lock_guard lock(mutex_);
    size_t required = 0; auto status = persona_(context_, nullptr, 0, &required);
    if (status != OSW_LIMIT && status != OSW_OK) check(status, "Persona size read");
    if (!required || required > 4096) throw std::runtime_error("Provider persona size is invalid");
    std::string buffer(required, '\0'); check(persona_(context_, buffer.data(), buffer.size(), &required), "Persona read");
    if (!required || required > buffer.size() || buffer[required - 1] != 0) throw std::runtime_error("Provider persona termination is invalid");
    buffer.resize(required - 1); return buffer;
}
Reply Provider::request(uint32_t operation, const nlohmann::json& metadata, const std::string& body, uint32_t timeout) {
    auto json = metadata.dump(); osw_request req{}; req.size = sizeof(req); req.operation = operation; req.timeout_ms = timeout;
    req.metadata = json.data(); req.metadata_size = json.size(); req.body = reinterpret_cast<const uint8_t*>(body.data()); req.body_size = body.size();
    uint64_t id = 0;
    { std::lock_guard lock(mutex_);
      auto code = submit_(context_, &req, &id);
      if (code != OSW_OK) {
          osw_identity current{}; current.size = sizeof(current); identity_(context_, &current);
          throw std::runtime_error("Provider request submission failed (status " + std::to_string(code) +
              ", reason " + std::to_string(current.reason_code) + ": " + std::string(current.reason, strnlen(current.reason, sizeof(current.reason))) + ")");
      }
    }
    auto end = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout + 500);
    try {
        for (;;) {
            { std::lock_guard lock(mutex_);
              osw_result value{}; value.size = sizeof(value); auto rc = result_(context_, id, &value);
              if (rc != OSW_PENDING) {
                  check(rc, "Provider result read");
                  if (value.metadata_size > 65536 || value.body_size > 1048576 || (value.body_size && !value.body) || (value.metadata_size && !value.metadata))
                      throw std::runtime_error("Provider result exceeds public bounds");
                  Reply reply; reply.status = value.status; reply.http_status = value.http_status;
                  if (value.metadata_size) reply.metadata = nlohmann::json::parse(value.metadata, value.metadata + value.metadata_size, nullptr, false);
                  if (value.body_size) reply.body.assign(reinterpret_cast<const char*>(value.body), value.body_size);
                  release_(context_, id); return reply;
              }
            }
            if (std::chrono::steady_clock::now() >= end) throw std::runtime_error("Provider request deadline exceeded");
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    } catch (...) { std::lock_guard lock(mutex_); cancel_(context_, id); release_(context_, id); throw; }
}
HttpResponse Provider::webapi(const HttpRequest& req, const std::string& group) {
    nlohmann::json headers = nlohmann::json::object();
    for (const auto& [k, v] : req.headers) headers[k] = v;
    auto reply = request(OSW_WEBAPI, {{"method", req.method}, {"path", req.path}, {"api_group", group},
        {"content_type", header(req.headers, "content-type")}, {"headers", headers}}, req.body);
    if (reply.status != OSW_OK) return {reply.status == OSW_TIMEOUT ? 504 : 503,
        {{"Content-Type", "application/json"}}, "{\"error\":\"provider_unavailable\"}"};
    auto content_type = reply.metadata.is_object() ? reply.metadata.value("content_type", std::string("application/json")) : "application/json";
    if (content_type.find_first_of("\r\n") != content_type.npos) throw std::runtime_error("Invalid provider content type");
    return {reply.http_status, {{"Content-Type", content_type}}, std::move(reply.body)};
}
void Provider::wait_ready() {
    auto end = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    while (std::chrono::steady_clock::now() < end) {
        auto result = request(OSW_P2P, {{"op", "status"}}, {}, 2000);
        if (result.status == OSW_OK && result.metadata.is_object() && result.metadata.value("ready", false)) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    throw std::runtime_error("Local server did not acknowledge loopback readiness");
}
void Provider::bind_game_endpoint(const std::string& address, uint16_t port) {
    auto reply = request(OSW_P2P, {{"op", "game.endpoint.bind"}, {"address", address}, {"port", port}});
    check(reply.status, "Owned game endpoint registration");
    auto state = request(OSW_P2P, {{"op", "status"}}, {}, 2000);
    if (state.status != OSW_OK || !state.metadata.is_object() ||
        !state.metadata.value("ready", false) || state.metadata.value("game_endpoint_pending", true))
        throw std::runtime_error("Provider did not confirm the owned game endpoint");
}
bool Provider::healthy(uint64_t account) {
    auto id = identity(); if (!id.signed_in || id.account_id != account) return false;
    auto state = request(OSW_P2P, {{"op", "status"}}, {}, 2000);
    if (state.status != OSW_OK || !state.metadata.is_object() || !state.metadata.value("ready", false)) return false;
    std::lock_guard lock(mutex_);
    for (int i = 0; i < 64; ++i) { osw_event e{}; e.size = sizeof(e); if (poll_(context_, &e) != OSW_OK) break; }
    return true;
}
}
