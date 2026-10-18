#include "platform.h"
#include <algorithm>
#include <cerrno>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
extern char** environ;
#endif

namespace bridge {
namespace {
bool private_environment(std::string name) {
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    for (auto prefix : {"BB_", "OSW_", "CTR_", "NEXTENDO_", "SHADNET_", "D3_", "DASH_"})
        if (name.starts_with(prefix)) return true;
    return name == "STEAMAPPID" || name == "STEAMGAMEID";
}
#ifdef _WIN32
std::wstring wide(std::string_view text) {
    if (text.empty()) return {};
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (!count) throw std::runtime_error("Invalid UTF-8 process argument");
    std::wstring out(count, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), out.data(), count);
    return out;
}
std::string utf8(std::wstring_view text) {
    if (text.empty()) return {};
    int count = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(count, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), count, nullptr, nullptr);
    return out;
}
std::wstring quote(const std::wstring& arg) {
    std::wstring out = L"\""; size_t slashes = 0;
    for (auto c : arg) {
        if (c == L'\\') { ++slashes; continue; }
        out.append(slashes * (c == L'"' ? 2 : 1), L'\\'); slashes = 0;
        if (c == L'"') out += L'\\';
        out += c;
    }
    out.append(slashes * 2, L'\\'); out += L'"'; return out;
}
#endif
}
fs::path executable_path() {
#ifdef _WIN32
    std::wstring path(32768, L'\0');
    auto count = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (!count || count == path.size()) throw std::runtime_error("Cannot locate bridge executable");
    path.resize(count); return fs::path(path);
#elif defined(__APPLE__)
    uint32_t size = 0; _NSGetExecutablePath(nullptr, &size);
    std::string path(size, '\0');
    if (_NSGetExecutablePath(path.data(), &size)) throw std::runtime_error("Cannot locate bridge executable");
    return fs::canonical(path.c_str());
#else
    return fs::canonical("/proc/self/exe");
#endif
}
DynamicLibrary::DynamicLibrary(const fs::path& path) {
#ifdef _WIN32
    handle_ = LoadLibraryExW(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
#else
    handle_ = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
#endif
    if (!handle_) throw std::runtime_error("Provider library cannot be loaded (missing file, dependency or incompatible architecture)");
}
DynamicLibrary::~DynamicLibrary() {
    if (!handle_) return;
#ifdef _WIN32
    FreeLibrary(static_cast<HMODULE>(handle_));
#else
    dlclose(handle_);
#endif
}
void* DynamicLibrary::symbol(const char* name) {
#ifdef _WIN32
    auto result = reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(handle_), name));
#else
    auto result = dlsym(handle_, name);
#endif
    if (!result) throw std::runtime_error(std::string("Provider is missing required C API symbol: ") + name);
    return result;
}
std::map<std::string, std::string> host_environment() {
    std::map<std::string, std::string> out;
    auto accept = [&](const std::string& pair) {
        auto equal = pair.find('=');
        if (equal == pair.npos || equal == 0) return;
        auto name = pair.substr(0, equal);
        if (!private_environment(name)) out[name] = pair.substr(equal + 1);
    };
#ifdef _WIN32
    auto env = GetEnvironmentStringsW();
    if (!env) throw std::runtime_error("Cannot read process environment");
    for (auto p = env; *p; p += wcslen(p) + 1) accept(utf8(p));
    FreeEnvironmentStringsW(env);
#else
    for (auto p = environ; *p; ++p) accept(*p);
#endif
    return out;
}
struct Process::Impl {
    std::optional<int> result;
#ifdef _WIN32
    HANDLE job = nullptr, process = nullptr;
#else
    pid_t guardian = -1; int pipe = -1;
#endif
};
Process::Process(const fs::path& exe, const std::vector<std::string>& args, const fs::path& cwd,
                 const std::map<std::string, std::string>& env, const fs::path& log) : impl_(std::make_unique<Impl>()) {
#ifdef _WIN32
    std::wstring command = quote(exe.wstring());
    for (const auto& arg : args) command += L" " + quote(wide(arg));
    std::wstring environment;
    std::map<std::wstring, std::wstring> sorted;
    for (const auto& [key, value] : env) {
        auto name = wide(key); std::transform(name.begin(), name.end(), name.begin(), towupper);
        sorted[name] = wide(value);
    }
    for (const auto& [key, value] : sorted) { environment += key + L"=" + value; environment += L'\0'; }
    environment += L'\0';
    SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
    HANDLE output = CreateFileW(log.c_str(), GENERIC_WRITE, FILE_SHARE_READ, &security, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (output == INVALID_HANDLE_VALUE || input == INVALID_HANDLE_VALUE) {
        if (output != INVALID_HANDLE_VALUE) CloseHandle(output);
        if (input != INVALID_HANDLE_VALUE) CloseHandle(input);
        throw std::runtime_error("Cannot create private host log");
    }
    SIZE_T bytes = 0; InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
    std::vector<unsigned char> storage(bytes);
    auto attrs = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
    bool initialized = InitializeProcThreadAttributeList(attrs, 1, 0, &bytes) != 0;
    HANDLE handles[] = {output, input};
    bool configured = initialized && UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, sizeof(handles), nullptr, nullptr);
    impl_->job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    bool job_ready = impl_->job && SetInformationJobObject(impl_->job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
    STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = input; startup.StartupInfo.hStdOutput = startup.StartupInfo.hStdError = output;
    startup.lpAttributeList = attrs;
    PROCESS_INFORMATION process{};
    bool created = configured && job_ready && CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, TRUE,
        CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
        environment.data(), cwd.c_str(), &startup.StartupInfo, &process);
    if (initialized) DeleteProcThreadAttributeList(attrs);
    CloseHandle(input); CloseHandle(output);
    if (!created || !AssignProcessToJobObject(impl_->job, process.hProcess)) {
        if (created) { TerminateProcess(process.hProcess, 1); WaitForSingleObject(process.hProcess, 5000); CloseHandle(process.hThread); CloseHandle(process.hProcess); }
        if (impl_->job) CloseHandle(impl_->job);
        throw std::runtime_error("Cannot launch or supervise native host");
    }
    impl_->process = process.hProcess;
    if (ResumeThread(process.hThread) == static_cast<DWORD>(-1)) {
        CloseHandle(process.hThread); stop(); throw std::runtime_error("Cannot resume native host");
    }
    CloseHandle(process.hThread);
#else
    // The guardian owns a separate process group and observes parent EOF. This
    // also works on macOS, where Linux's PR_SET_PDEATHSIG is unavailable.
    int pipes[2];
    if (::pipe(pipes) != 0) throw std::runtime_error("Cannot create host lifetime pipe");
    fcntl(pipes[0], F_SETFD, FD_CLOEXEC); fcntl(pipes[1], F_SETFD, FD_CLOEXEC);
    int output = open(log.c_str(), O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600);
    int input = open("/dev/null", O_RDONLY | O_CLOEXEC);
    if (output < 0 || input < 0) {
        close(pipes[0]); close(pipes[1]); if (output >= 0) close(output); if (input >= 0) close(input);
        throw std::runtime_error("Cannot create private host log");
    }
    std::vector<std::string> arguments{exe.string()}, environment;
    arguments.insert(arguments.end(), args.begin(), args.end());
    for (const auto& [k, v] : env) environment.push_back(k + "=" + v);
    std::vector<char*> argv, envp;
    for (auto& s : arguments) argv.push_back(s.data()); argv.push_back(nullptr);
    for (auto& s : environment) envp.push_back(s.data()); envp.push_back(nullptr);
    auto child = fork();
    if (child == 0) {
        close(pipes[1]);
        auto host = fork();
        if (host == 0) {
            close(pipes[0]); setpgid(0, 0);
            if (chdir(cwd.c_str()) || dup2(input, 0) < 0 || dup2(output, 1) < 0 || dup2(output, 2) < 0) _exit(126);
            execve(exe.c_str(), argv.data(), envp.data()); _exit(127);
        }
        close(output); close(input);
        if (host < 0) _exit(126);
        setpgid(host, host);
        for (;;) {
            siginfo_t info{};
            if (waitid(P_PID, static_cast<id_t>(host), &info, WEXITED | WNOHANG | WNOWAIT) == 0 && info.si_pid == host) break;
            pollfd lifetime{pipes[0], POLLIN | POLLHUP, 0};
            int result = poll(&lifetime, 1, 100);
            if (result > 0 && lifetime.revents) break;
            if (result < 0 && errno != EINTR) break;
        }
        kill(-host, SIGKILL);
        int status = 0; while (waitpid(host, &status, 0) < 0 && errno == EINTR) {}
        close(pipes[0]);
        _exit(WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status));
    }
    close(pipes[0]); close(input); close(output);
    if (child < 0) { close(pipes[1]); throw std::runtime_error("Cannot launch host guardian"); }
    impl_->guardian = child; impl_->pipe = pipes[1];
#endif
}
Process::~Process() { stop(); }
std::optional<int> Process::exit_code() {
    if (impl_->result) return impl_->result;
#ifdef _WIN32
    if (impl_->process && WaitForSingleObject(impl_->process, 0) == WAIT_OBJECT_0) {
        DWORD code = 1; GetExitCodeProcess(impl_->process, &code); impl_->result = static_cast<int>(code);
    }
#else
    int status = 0;
    if (impl_->guardian > 0 && waitpid(impl_->guardian, &status, WNOHANG) == impl_->guardian) {
        impl_->guardian = -1;
        impl_->result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    }
#endif
    return impl_->result;
}
void Process::stop() {
    if (!impl_) return;
#ifdef _WIN32
    if (impl_->job) { CloseHandle(impl_->job); impl_->job = nullptr; }
    if (impl_->process) { WaitForSingleObject(impl_->process, 5000); CloseHandle(impl_->process); impl_->process = nullptr; }
#else
    if (impl_->pipe >= 0) { close(impl_->pipe); impl_->pipe = -1; }
    if (impl_->guardian > 0) {
        int status; while (waitpid(impl_->guardian, &status, 0) < 0 && errno == EINTR) {}
        impl_->guardian = -1;
    }
#endif
}
}
