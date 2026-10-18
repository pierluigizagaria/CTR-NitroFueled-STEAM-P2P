#pragma once
#include "config.h"
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
    void stop();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
std::map<std::string, std::string> host_environment();
}
