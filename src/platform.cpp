#include "platform.h"
#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cstddef>
#include <fstream>
#include <set>
#include <sstream>
#include <stdexcept>
#ifdef _WIN32
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#else
#include <arpa/inet.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <libproc.h>
#include <mach-o/dyld.h>
#include <sys/proc_info.h>
#endif
extern char** environ;
#endif

namespace bridge {
namespace {
constexpr size_t max_socket_bytes = 8 * 1024 * 1024;
constexpr size_t max_child_fds = 16384;
void observe_port(std::optional<uint16_t>& found, uint32_t address, uint16_t port) {
    if (!port) return; // Unbound socket, not a source endpoint.
    if (address != 0 && address != 0x7f000001)
        throw std::runtime_error("Native child UDP socket has an unsupported local address");
    if (found && *found != port)
        throw std::runtime_error("Native child has multiple distinct UDP source ports");
    found = port;
}
#ifndef _WIN32
struct FileDescriptor {
    int value = -1;
    explicit FileDescriptor(int fd = -1) : value(fd) {}
    ~FileDescriptor() { if (value >= 0) close(value); }
    FileDescriptor(const FileDescriptor&) = delete;
    int release() { int fd = value; value = -1; return fd; }
};
struct PrivatePipe {
    FileDescriptor read, write;
    PrivatePipe() {
        int descriptors[2];
        if (::pipe(descriptors)) throw std::runtime_error("Cannot create child supervision pipe");
        read.value = descriptors[0]; write.value = descriptors[1];
        if (fcntl(read.value, F_SETFD, FD_CLOEXEC) < 0 || fcntl(write.value, F_SETFD, FD_CLOEXEC) < 0)
            throw std::runtime_error("Cannot protect child supervision pipe");
    }
};
pid_t receive_child_pid(int fd) {
    pid_t child = -1;
    auto* output = reinterpret_cast<char*>(&child); size_t copied = 0;
    const auto end = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (copied < sizeof(child)) {
        auto left = std::chrono::duration_cast<std::chrono::milliseconds>(end - std::chrono::steady_clock::now()).count();
        if (left <= 0) throw std::runtime_error("Native child PID handshake timed out");
        pollfd ready{fd, POLLIN | POLLHUP, 0};
        auto result = poll(&ready, 1, static_cast<int>(left));
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) throw std::runtime_error("Native child PID handshake failed");
        auto bytes = ::read(fd, output + copied, sizeof(child) - copied);
        if (bytes < 0 && errno == EINTR) continue;
        if (bytes <= 0) throw std::runtime_error("Native child PID handshake was incomplete");
        copied += static_cast<size_t>(bytes);
    }
    if (child <= 0) throw std::runtime_error("Native child PID handshake was invalid");
    return child;
}
#ifdef __APPLE__
bool owned_child(pid_t child, pid_t guardian) {
    proc_bsdinfo info{};
    auto count = proc_pidinfo(child, PROC_PIDTBSDINFO, 0, &info, sizeof(info));
    if (count <= 0 && errno == ESRCH) return false;
    if (count != static_cast<int>(sizeof(info))) throw std::runtime_error("Cannot inspect native child identity");
    return info.pbi_pid == static_cast<uint32_t>(child) && info.pbi_ppid == static_cast<uint32_t>(guardian) &&
           !(info.pbi_flags & PROC_FLAG_INEXIT);
}
#else
bool owned_child(pid_t child, pid_t guardian) {
    std::ifstream input("/proc/" + std::to_string(child) + "/stat");
    if (!input) {
        if (errno == ENOENT || errno == ESRCH) return false;
        throw std::runtime_error("Cannot inspect native child identity");
    }
    std::array<char, 4096> buffer{}; input.getline(buffer.data(), buffer.size());
    if (!input) throw std::runtime_error("Invalid native child process record");
    std::string text(buffer.data()); auto end = text.rfind(')');
    if (end == text.npos) throw std::runtime_error("Invalid native child process record");
    std::istringstream fields(text.substr(end + 1)); char state = 0; pid_t parent = -1;
    if (!(fields >> state >> parent)) throw std::runtime_error("Invalid native child process identity");
    return parent == guardian && state != 'Z' && state != 'X';
}
uint64_t proc_number(std::string_view text, int base = 10) {
    uint64_t value = 0; auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), value, base);
    if (text.empty() || ec != std::errc{} || end != text.data() + text.size())
        throw std::runtime_error("Invalid native child socket record");
    return value;
}
std::set<uint64_t> socket_inodes(pid_t child) {
    std::set<uint64_t> result; size_t count = 0;
    std::error_code error;
    fs::directory_iterator entries("/proc/" + std::to_string(child) + "/fd", error), end;
    if (error) throw std::runtime_error("Cannot inspect native child file descriptors");
    while (entries != end) {
        if (++count > max_child_fds) throw std::runtime_error("Native child file descriptor limit exceeded");
        auto target = fs::read_symlink(entries->path(), error).string();
        if (error && error != std::errc::no_such_file_or_directory)
            throw std::runtime_error("Cannot inspect native child socket ownership");
        if (!error && target.starts_with("socket:[") && target.ends_with(']'))
            result.insert(proc_number(std::string_view(target).substr(8, target.size() - 9)));
        entries.increment(error);
        if (error) throw std::runtime_error("Cannot enumerate native child file descriptors");
    }
    return result;
}
#endif
#endif
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
    pid_t guardian = -1, child = -1; int pipe = -1;
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
    PrivatePipe lifetime, identity;
    FileDescriptor output(open(log.c_str(), O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600));
    FileDescriptor input(open("/dev/null", O_RDONLY | O_CLOEXEC));
    if (output.value < 0 || input.value < 0) {
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
        close(lifetime.write.value); close(identity.read.value);
        auto host = fork();
        if (host == 0) {
            close(lifetime.read.value); close(identity.write.value); setpgid(0, 0);
            if (chdir(cwd.c_str()) || dup2(input.value, 0) < 0 || dup2(output.value, 1) < 0 || dup2(output.value, 2) < 0) _exit(126);
            execve(exe.c_str(), argv.data(), envp.data()); _exit(127);
        }
        close(output.value); close(input.value);
        if (host < 0) _exit(126);
        setpgid(host, host);
        // Parent timeout/termination must not let SIGPIPE abandon the host.
        signal(SIGPIPE, SIG_IGN);
        ssize_t sent;
        do { sent = ::write(identity.write.value, &host, sizeof(host)); } while (sent < 0 && errno == EINTR);
        close(identity.write.value);
        for (;;) {
            if (sent != static_cast<ssize_t>(sizeof(host))) break;
            siginfo_t info{};
            if (waitid(P_PID, static_cast<id_t>(host), &info, WEXITED | WNOHANG | WNOWAIT) == 0 && info.si_pid == host) break;
            pollfd parent{lifetime.read.value, POLLIN | POLLHUP, 0};
            int result = poll(&parent, 1, 100);
            if (result > 0 && parent.revents) break;
            if (result < 0 && errno != EINTR) break;
        }
        kill(-host, SIGKILL); kill(host, SIGKILL);
        int status = 0; while (waitpid(host, &status, 0) < 0 && errno == EINTR) {}
        close(lifetime.read.value);
        _exit(WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status));
    }
    close(lifetime.read.release()); close(identity.write.release());
    if (child < 0) throw std::runtime_error("Cannot launch host guardian");
    impl_->guardian = child; impl_->pipe = lifetime.write.release();
    try { impl_->child = receive_child_pid(identity.read.value); }
    catch (...) { stop(); throw; }
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
std::optional<uint16_t> Process::udp_source_port() const {
    if (!impl_ || impl_->result) return std::nullopt;
    std::optional<uint16_t> found;
#ifdef _WIN32
    if (!impl_->process || WaitForSingleObject(impl_->process, 0) != WAIT_TIMEOUT) return std::nullopt;
    const auto child = GetProcessId(impl_->process);
    if (!child) throw std::runtime_error("Cannot inspect native child process identity");
    ULONG bytes = 0;
    auto status = GetExtendedUdpTable(nullptr, &bytes, FALSE, AF_INET, UDP_TABLE_OWNER_PID, 0);
    for (int attempt = 0; attempt < 3; ++attempt) {
        if (status != ERROR_INSUFFICIENT_BUFFER || bytes < offsetof(MIB_UDPTABLE_OWNER_PID, table) || bytes > max_socket_bytes)
            throw std::runtime_error("Cannot inspect bounded UDP owner table");
        std::vector<unsigned char> buffer(bytes);
        status = GetExtendedUdpTable(buffer.data(), &bytes, FALSE, AF_INET, UDP_TABLE_OWNER_PID, 0);
        if (status == ERROR_INSUFFICIENT_BUFFER) continue;
        if (status != NO_ERROR || bytes > buffer.size() || bytes < offsetof(MIB_UDPTABLE_OWNER_PID, table))
            throw std::runtime_error("Cannot read UDP owner table");
        const auto* table = reinterpret_cast<const MIB_UDPTABLE_OWNER_PID*>(buffer.data());
        if (table->dwNumEntries > (bytes - offsetof(MIB_UDPTABLE_OWNER_PID, table)) / sizeof(MIB_UDPROW_OWNER_PID))
            throw std::runtime_error("Invalid UDP owner table size");
        for (DWORD i = 0; i < table->dwNumEntries; ++i) {
            const auto& row = table->table[i];
            if (row.dwOwningPid == child)
                observe_port(found, ntohl(row.dwLocalAddr), ntohs(static_cast<uint16_t>(row.dwLocalPort)));
        }
        if (WaitForSingleObject(impl_->process, 0) != WAIT_TIMEOUT) return std::nullopt;
        return found;
    }
    throw std::runtime_error("UDP owner table changed beyond retry bound");
#else
    if (impl_->guardian <= 0 || impl_->child <= 0 || !owned_child(impl_->child, impl_->guardian)) return std::nullopt;
#ifdef __APPLE__
    // libproc enumerates descriptors of this exact child, never a global port scan.
    std::vector<proc_fdinfo> descriptors(max_child_fds + 1);
    auto bytes = proc_pidinfo(impl_->child, PROC_PIDLISTFDS, 0, descriptors.data(),
                             static_cast<int>(descriptors.size() * sizeof(proc_fdinfo)));
    if (bytes <= 0 || bytes % sizeof(proc_fdinfo) || static_cast<size_t>(bytes) >= descriptors.size() * sizeof(proc_fdinfo))
        throw std::runtime_error("Cannot inspect bounded native child descriptors");
    descriptors.resize(static_cast<size_t>(bytes) / sizeof(proc_fdinfo));
    for (const auto& fd : descriptors) {
        if (fd.proc_fdtype != PROX_FDTYPE_SOCKET) continue;
        socket_fdinfo info{};
        auto size = proc_pidfdinfo(impl_->child, fd.proc_fd, PROC_PIDFDSOCKETINFO, &info, sizeof(info));
        if (size <= 0 && (errno == EBADF || errno == ENOENT)) return std::nullopt; // Snapshot changed.
        if (size != static_cast<int>(sizeof(info))) throw std::runtime_error("Cannot inspect native child socket");
        if (info.psi.soi_family != AF_INET || info.psi.soi_type != SOCK_DGRAM || info.psi.soi_protocol != IPPROTO_UDP) continue;
        if (info.psi.soi_kind != SOCKINFO_IN) throw std::runtime_error("Unsupported native child UDP socket record");
        const auto& address = info.psi.soi_proto.pri_in;
        observe_port(found, ntohl(address.insi_laddr.ina_46.i46a_addr4.s_addr),
                     ntohs(static_cast<uint16_t>(address.insi_lport)));
    }
#else
    // /proc/<pid>/net/udp is namespace-wide. Only inodes still present in the
    // exact child's descriptor set qualify; unrelated processes are excluded.
    const auto inodes = socket_inodes(impl_->child);
    std::ifstream input("/proc/" + std::to_string(impl_->child) + "/net/udp");
    if (!input) throw std::runtime_error("Cannot inspect native child UDP table");
    std::array<char, 1024> line{};
    if (!input.getline(line.data(), line.size())) throw std::runtime_error("Invalid native child UDP table header");
    size_t bytes = 0;
    std::vector<std::pair<uint32_t, uint16_t>> candidates;
    while (input.getline(line.data(), line.size())) {
        bytes += static_cast<size_t>(input.gcount());
        if (bytes > max_socket_bytes) throw std::runtime_error("Native child UDP table exceeds bound");
        std::istringstream fields(line.data()); std::array<std::string, 10> columns;
        for (auto& column : columns)
            if (!(fields >> column)) throw std::runtime_error("Invalid native child UDP table row");
        if (!inodes.contains(proc_number(columns[9]))) continue;
        auto colon = columns[1].find(':');
        if (colon != 8 || columns[1].size() != 13) throw std::runtime_error("Invalid native child UDP endpoint");
        const auto address = static_cast<uint32_t>(proc_number(std::string_view(columns[1]).substr(0, 8), 16));
        const auto port = static_cast<uint16_t>(proc_number(std::string_view(columns[1]).substr(9), 16));
        candidates.emplace_back(ntohl(address), port);
        if (candidates.size() > max_child_fds) throw std::runtime_error("Native child UDP endpoint limit exceeded");
    }
    if (!input.eof()) throw std::runtime_error("Cannot read bounded native child UDP table");
    if (socket_inodes(impl_->child) != inodes) return std::nullopt;
    for (const auto& [address, port] : candidates) observe_port(found, address, port);
#endif
    if (!owned_child(impl_->child, impl_->guardian)) return std::nullopt;
    return found;
#endif
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
struct DiagnosticDatagram::Impl {
    uint16_t port = 0;
#ifdef _WIN32
    SOCKET socket = INVALID_SOCKET;
    bool winsock = false;
    ~Impl() { if (socket != INVALID_SOCKET) closesocket(socket); if (winsock) WSACleanup(); }
#else
    int socket = -1;
    ~Impl() { if (socket >= 0) close(socket); }
#endif
};
DiagnosticDatagram::DiagnosticDatagram() : impl_(std::make_unique<Impl>()) {
#ifdef _WIN32
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data)) throw std::runtime_error("Cannot initialize diagnostic UDP socket");
    impl_->winsock = true;
#endif
    impl_->socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
#ifdef _WIN32
    if (impl_->socket == INVALID_SOCKET || !SetHandleInformation(reinterpret_cast<HANDLE>(impl_->socket), HANDLE_FLAG_INHERIT, 0))
#else
    if (impl_->socket < 0 || fcntl(impl_->socket, F_SETFD, FD_CLOEXEC) < 0)
#endif
        throw std::runtime_error("Cannot create private diagnostic UDP socket");
    sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(0x7f000001);
    if (bind(impl_->socket, reinterpret_cast<const sockaddr*>(&address), sizeof(address)))
        throw std::runtime_error("Cannot bind diagnostic UDP socket");
#ifdef _WIN32
    int size = sizeof(address);
#else
    socklen_t size = sizeof(address);
#endif
    if (getsockname(impl_->socket, reinterpret_cast<sockaddr*>(&address), &size) || !address.sin_port)
        throw std::runtime_error("Cannot read diagnostic UDP socket port");
    impl_->port = ntohs(address.sin_port);
}
DiagnosticDatagram::~DiagnosticDatagram() = default;
uint16_t DiagnosticDatagram::port() const noexcept { return impl_->port; }
}
