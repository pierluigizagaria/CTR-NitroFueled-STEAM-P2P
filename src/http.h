#pragma once
#include "config.h"
#include <functional>
#include <memory>
#include <utility>
#include <vector>

namespace bridge {
using Headers = std::vector<std::pair<std::string, std::string>>;
struct HttpRequest { std::string method, path; Headers headers; std::string body; };
struct HttpResponse { int status = 500; Headers headers; std::string body; };
std::string header(const Headers& headers, std::string_view name);
std::string api_group(const std::string& host);
HttpRequest parse_request_head(std::string_view input);
HttpResponse proxy_request(const HttpRequest& request, const std::string& address, uint16_t port);
class HttpServer {
public:
    using Handler = std::function<HttpResponse(const HttpRequest&)>;
    HttpServer(const std::string& address, uint16_t port, Handler handler);
    ~HttpServer();
    HttpServer(const HttpServer&) = delete;
    HttpServer& operator=(const HttpServer&) = delete;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
