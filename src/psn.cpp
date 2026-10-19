#include "psn.h"
#include <algorithm>
#include <charconv>
#include <cctype>
#include <stdexcept>
#include <set>

namespace bridge {
namespace {
using Json = nlohmann::json;
constexpr size_t body_limit = 256 * 1024;
HttpResponse json_response(int status, const Json& value) {
    return {status, {{"Content-Type", "application/json"}, {"Cache-Control", "no-store"}}, value.dump()};
}
HttpResponse error(int status, const char* category) {
    return json_response(status, {{"error", category}});
}
std::string text(const Json& value, const char* key, size_t maximum, bool empty = true) {
    if (!value.contains(key) || !value[key].is_string()) throw std::invalid_argument("field");
    auto result = value[key].get<std::string>();
    if (result.size() > maximum || result.find('\0') != result.npos || (!empty && result.empty()))
        throw std::invalid_argument("field");
    return result;
}
std::string encode_hex(std::string_view bytes) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result; result.reserve(bytes.size() * 2);
    for (unsigned char byte : bytes) { result += hex[byte >> 4]; result += hex[byte & 15]; }
    return result;
}
std::string decode_hex(const std::string& hex) {
    if (hex.size() % 2 || hex.size() > body_limit * 2) throw std::invalid_argument("body");
    auto digit = [](char c) {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        throw std::invalid_argument("body");
    };
    std::string result; result.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.size(); i += 2)
        result += static_cast<char>((digit(hex[i]) << 4) | digit(hex[i + 1]));
    return result;
}
bool equal_capability(std::string_view a, std::string_view b) {
    if (a.size() != b.size()) return false;
    unsigned difference = 0;
    for (size_t i = 0; i < a.size(); ++i) difference |= static_cast<unsigned char>(a[i] ^ b[i]);
    return difference == 0;
}
}
PsnRelay::PsnRelay(Provider& provider, std::string capability)
    : PsnRelay({[&provider] { return provider.identity(); },
                [&provider](uint32_t op, const Json& metadata, const std::string& body) {
                    return provider.request(op, metadata, body);
                }, [&provider] { return provider.psn_event(); }}, std::move(capability)) {}
PsnRelay::PsnRelay(PsnServices services, std::string capability) : services_(std::move(services)) {
    if (capability.size() != 64 || capability.find_first_not_of("0123456789abcdef") != capability.npos)
        throw std::invalid_argument("Invalid private PSN capability");
    authorization_ = "Bearer " + capability;
    auto identity = services_.identity();
    if (!identity.signed_in || !identity.account_id) throw std::runtime_error("PSN bridge requires a signed-in provider");
    account_ = identity.account_id;
}
HttpResponse PsnRelay::events(std::string_view cursor) {
    uint64_t after = 0;
    auto [end, ec] = std::from_chars(cursor.data(), cursor.data() + cursor.size(), after);
    if (ec != std::errc{} || end != cursor.data() + cursor.size() || cursor.empty())
        return error(400, "invalid_cursor");
    std::lock_guard lock(mutex_);
    if (failed_) return error(503, "notification_stream_failed");
    // Acknowledgement is explicit. A response lost in transit can be read again
    // with the same cursor, including accepted invitations, without consuming it.
    if (after < acknowledged_ || after > offered_) return error(409, "invalid_cursor");
    acknowledged_ = after;
    while (!pending_.empty() && pending_.front().first <= after) pending_.pop_front();
    try {
        for (unsigned i = 0; i < 64; ++i) {
            auto raw = services_.event();
            if (!raw) break;
            if (raw->size() > 65535 || pending_.size() == 512) throw std::runtime_error("overflow");
            auto value = Json::parse(*raw);
            if (!value.is_object() || value.value("version", 0) != 1)
                throw std::runtime_error("invalid event envelope");
            pending_.emplace_back(next_++, std::move(value));
        }
    } catch (...) {
        failed_ = true;
        pending_.clear();
        return error(503, "notification_stream_failed");
    }
    Json batch = Json::array();
    size_t bytes = 0;
    for (const auto& [sequence, value] : pending_) {
        auto length = value.dump().size();
        if (batch.size() == 64 || bytes + length > 768 * 1024) break;
        batch.push_back({{"sequence", sequence}, {"event", value}});
        bytes += length;
        offered_ = std::max(offered_, sequence);
    }
    return json_response(200, {{"version", 1}, {"events", std::move(batch)}});
}
HttpResponse PsnRelay::handle(const HttpRequest& request) {
    // No browser origin is part of this private, inherited-capability protocol.
    if (!header(request.headers, "origin").empty() ||
        !equal_capability(header(request.headers, "authorization"), authorization_))
        return error(403, "forbidden");
    try {
        auto identity = services_.identity();
        if (!identity.signed_in || identity.account_id != account_) return error(503, "identity_changed");
        if (request.method == "GET" && request.path == "/psn/v1/info") {
            return json_response(200, {{"version", 1}, {"accountId", std::to_string(identity.account_id)},
                {"onlineId", identity.online_id}, {"signedIn", true},
                {"capabilities", {"identity", "id-token", "webapi", "push", "invitation-accepted"}}});
        }
        constexpr std::string_view prefix = "/psn/v1/events?after=";
        if (request.method == "GET" && request.path.starts_with(prefix))
            return events(std::string_view(request.path).substr(prefix.size()));
        if (request.method != "POST" ||
            (request.path != "/psn/v1/token" && request.path != "/psn/v1/webapi"))
            return error(404, "unsupported_operation");
        if (request.body.size() > 1024 * 1024) return error(413, "request_limit");
        auto input = Json::parse(request.body);
        if (!input.is_object()) return error(400, "invalid_request");
        if (request.path == "/psn/v1/token") {
            if (!input.contains("kind") || input["kind"] != 1)
                return json_response(200, {{"status", OSW_NOT_SUPPORTED}});
            auto client = text(input, "client_id", 128, false);
            auto scope = text(input, "scope", 128, false);
            auto result = services_.request(OSW_TOKEN, {{"client_id", client}, {"scope", scope}}, {});
            if (result.status == OSW_OK && (result.body.empty() || result.body.size() > 4096 || result.body.find('\0') != result.body.npos))
                return error(502, "invalid_provider_response");
            // This is the local companion capability and an adapter issuer value,
            // not a claim that Sony or Steam issued a PSN credential.
            return json_response(200, {{"status", result.status}, {"issuerId", 256},
                {"token", result.status == OSW_OK ? result.body : ""}});
        }
        auto method = text(input, "method", 6, false);
        if (method != "GET" && method != "POST" && method != "PUT" && method != "DELETE" && method != "PATCH")
            return error(400, "invalid_method");
        auto path = text(input, "path", 8192, false);
        if (path[0] != '/' || path.starts_with("//") || path.find_first_of("\r\n#") != path.npos)
            return error(400, "invalid_path");
        auto group = text(input, "api_group", 256, false);
        auto type = text(input, "content_type", 256);
        if (type.find_first_of("\r\n") != type.npos) return error(400, "invalid_content_type");
        const auto& headers = input.at("headers");
        if (!headers.is_object() || headers.size() > 64) return error(400, "invalid_headers");
        std::set<std::string> names;
        for (const auto& [name, value] : headers.items()) {
            if (name.empty() || name.size() > 256 || name.find_first_not_of("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") != name.npos ||
                !value.is_string()) return error(400, "invalid_headers");
            const auto& v = value.get_ref<const std::string&>();
            if (v.size() > 8192 || v.find_first_of("\r\n") != v.npos || v.find('\0') != v.npos)
                return error(400, "invalid_headers");
            std::string folded = name;
            for (auto& c : folded) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            if (!names.insert(folded).second) return error(400, "duplicate_header");
        }
        Json metadata = {{"method", method}, {"path", path}, {"api_group", group}, {"content_type", type}, {"headers", headers}};
        if (metadata.dump().size() > 65536) return error(413, "metadata_limit");
        auto body = decode_hex(text(input, "bodyHex", body_limit * 2));
        auto result = services_.request(OSW_WEBAPI, metadata, body);
        if (result.body.size() > body_limit) return error(502, "response_limit");
        auto response_type = result.metadata.is_object() ? result.metadata.value("content_type", std::string("application/json")) : "application/json";
        if (response_type.size() > 256 || response_type.find_first_of("\r\n") != response_type.npos)
            return error(502, "invalid_provider_response");
        return json_response(200, {{"status", result.status}, {"httpStatus", result.http_status},
            {"contentType", response_type}, {"bodyHex", encode_hex(result.body)}});
    } catch (const nlohmann::json::exception&) { return error(400, "invalid_request"); }
      catch (const std::invalid_argument&) { return error(400, "invalid_request"); }
      catch (...) { return error(503, "provider_unavailable"); }
}
}
