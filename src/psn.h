#pragma once
#include "provider.h"
#include <deque>
#include <functional>

namespace bridge {
// Transport only: the provider owns PSN event names, identities and session semantics.
// Injection is for independent contract tests; production binds the public Provider API.
struct PsnServices {
    std::function<osw_identity()> identity;
    std::function<Reply(uint32_t, const nlohmann::json&, const std::string&)> request;
    std::function<std::optional<std::string>()> event;
};
class PsnRelay {
public:
    PsnRelay(Provider& provider, std::string capability);
    PsnRelay(PsnServices services, std::string capability);
    HttpResponse handle(const HttpRequest& request);
private:
    PsnServices services_;
    std::string authorization_;
    uint64_t account_ = 0;
    std::mutex mutex_;
    std::deque<std::pair<uint64_t, nlohmann::json>> pending_;
    uint64_t next_ = 1, acknowledged_ = 0, offered_ = 0;
    bool failed_ = false;
    HttpResponse events(std::string_view cursor);
};
}
