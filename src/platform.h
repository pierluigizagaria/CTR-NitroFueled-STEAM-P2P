#pragma once
#include "config.h"
#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace bridge {
fs::path executable_path();
// Replace a file only after its current bytes match the caller's snapshot.
// nullopt requires a missing file. A sibling temporary file is flushed before
// the atomic replacement; failures never truncate the original in place.
void replace_file_atomically(const fs::path& path, const std::optional<std::string>& expected,
                             std::string_view replacement);
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
// The supervised game's UDP source: the one process owning it (its ID and start
// time, so a reused ID is never mistaken for it) and its single local port.
struct GameEndpoint {
    uint64_t owner = 0, started = 0;
    uint16_t port = 0;
    bool operator==(const GameEndpoint&) const = default;
};
class Process {
public:
    Process(const fs::path& exe, const std::vector<std::string>& args, const fs::path& cwd,
            const std::map<std::string, std::string>& environment, const fs::path& log);
    ~Process();
    Process(const Process&) = delete;
    Process& operator=(const Process&) = delete;
    // The direct child's exit code, once it has exited.
    std::optional<int> exit_code();
    // Whether any process of the supervised tree still runs.
    bool running();
    // Observe only processes this bridge supervises. No IPv4 UDP bind returns
    // nullopt; several owners, several ports or addresses other than wildcard/
    // 127.0.0.1 fail without selecting one.
    std::optional<GameEndpoint> game_endpoint() const;
    // Whether exactly that owner still runs inside the supervised tree.
    bool alive(const GameEndpoint& endpoint) const;
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
// The bridge's own inherited environment, unfiltered.
std::map<std::string, std::string> host_environment();
// The comparison key of an environment name: case-insensitive on Windows.
std::string environment_key(std::string_view name);
}
