#pragma once
#include "config.h"
#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace bridge {
fs::path executable_path();
class DynamicLibrary {
public:
    explicit DynamicLibrary(const fs::path& path);
    ~DynamicLibrary();
    DynamicLibrary(const DynamicLibrary&) = delete;
    DynamicLibrary& operator=(const DynamicLibrary&) = delete;
    void* symbol(const char* name);
private:
    void* handle_ = nullptr;
};
class Process {
public:
    Process(const fs::path& exe, const std::vector<std::string>& args, const fs::path& cwd,
            const std::map<std::string, std::string>& environment, const fs::path& log);
    ~Process();
    Process(const Process&) = delete;
    Process& operator=(const Process&) = delete;
    std::optional<int> exit_code();
    // Observe only this live child. No IPv4 UDP bind returns nullopt; ambiguous ports
    // or addresses other than wildcard/127.0.0.1 fail without selecting one.
    std::optional<uint16_t> udp_source_port() const;
    void stop();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
class DiagnosticDatagram {
public:
    DiagnosticDatagram();
    ~DiagnosticDatagram();
    DiagnosticDatagram(const DiagnosticDatagram&) = delete;
    DiagnosticDatagram& operator=(const DiagnosticDatagram&) = delete;
    uint16_t port() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
std::map<std::string, std::string> host_environment();
}
