#pragma once
#include "config.h"
#include "http.h"
#include "platform.h"
#include <orbisteamworks/osw.h>
#include <mutex>
#include <nlohmann/json.hpp>

namespace bridge {
struct Reply { int status = OSW_UNAVAILABLE, http_status = 0; nlohmann::json metadata; std::string body; };
class Provider {
public:
    Provider(const Config& config, bool companion);
    ~Provider();
    Provider(const Provider&) = delete;
    Provider& operator=(const Provider&) = delete;
    osw_identity identity();
    osw_identity wait_identity();
    std::string persona();
    Reply request(uint32_t operation, const nlohmann::json& metadata, const std::string& body = {}, uint32_t timeout = 25000);
    HttpResponse webapi(const HttpRequest& request, const std::string& group);
    void wait_ready();
    bool healthy();
private:
    DynamicLibrary library_;
    osw_context* context_ = nullptr;
    std::mutex mutex_;
    decltype(&osw_create_v2) create_;
    decltype(&osw_start) start_;
    decltype(&osw_stop) stop_;
    decltype(&osw_destroy) destroy_;
    decltype(&osw_get_identity) identity_;
    decltype(&osw_submit) submit_;
    decltype(&osw_get_result) result_;
    decltype(&osw_cancel) cancel_;
    decltype(&osw_release) release_;
    decltype(&osw_poll_event) poll_;
    int32_t (*loopback_)(osw_context*);
    int32_t (*appid_)(osw_context*, uint32_t);
    int32_t (*persona_)(osw_context*, char*, size_t, size_t*);
};
}
