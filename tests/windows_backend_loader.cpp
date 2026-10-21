#include "config.h"
#include "host.h"
#include "platform.h"
#include <windows.h>
#include <chrono>
#include <iostream>
#include <optional>
#include <stdexcept>

namespace {
using namespace bridge;
int checks = 0;
void require(bool value, const std::string& message) {
    ++checks;
    if (!value) throw std::runtime_error(message);
}

std::wstring decode_utf8(const std::string& value) {
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                                        static_cast<int>(value.size()), nullptr, 0);
    require(count > 0, "Backend environment path is not UTF-8");
    std::wstring result(count, L'\0');
    require(MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                               static_cast<int>(value.size()), result.data(), count) == count,
            "Cannot decode the backend environment path");
    return result;
}

struct Fixture {
    fs::path original_cwd = fs::current_path();
    fs::path root, backend_dir;
    std::optional<std::wstring> original_path;
    bool owned = false;

    Fixture() {
        const DWORD count = GetEnvironmentVariableW(L"PATH", nullptr, 0);
        if (count) {
            std::wstring value(count, L'\0');
            const DWORD copied = GetEnvironmentVariableW(L"PATH", value.data(), count);
            require(copied < count, "Cannot snapshot PATH for the fixture");
            value.resize(copied);
            original_path = std::move(value);
        }
        root = original_cwd / ("backend-loader-fixture-" + std::to_string(GetCurrentProcessId()) + "-" +
            std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        owned = fs::create_directory(root);
        require(owned, "Cannot create isolated loader fixture");
        backend_dir = root / L"backend files \u00e8 \u6f22";
    }
    ~Fixture() {
        std::error_code error;
        fs::current_path(original_cwd, error);
        SetEnvironmentVariableW(L"PATH", original_path ? original_path->c_str() : nullptr);
        if (owned) fs::remove_all(root, error);
    }
    void isolate() {
        fs::create_directory(backend_dir);
        const auto unrelated = root / "unrelated working directory";
        fs::create_directory(unrelated);
        fs::current_path(unrelated);
        require(SetEnvironmentVariableW(L"PATH", L"") != 0, "Cannot clear the fixture process PATH");
        require(GetModuleHandleW(L"bridge_p2p_loader_sidecar.dll") == nullptr,
                "Fixture sidecar was already loaded before the test");
    }
};

struct Module {
    HMODULE value;
    DWORD error;
    explicit Module(const std::wstring& path)
        : value(LoadLibraryExW(path.c_str(), nullptr,
                              LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)),
          error(value ? ERROR_SUCCESS : GetLastError()) {}
    ~Module() { if (value) FreeLibrary(value); }
};

std::wstring environment_path(const fs::path& root, const char* host) {
    auto config = parse_config(std::string("[game]\nhost = ") + host + "\n", root);
    config.online_id = "Fixture";
    const auto environment = native_environment(config, 42, {}, std::string(64, 'a'));
    // Decode exactly what the child receives. Filesystem or ctypes normalization here
    // would hide the forward-slash LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR regression.
    return decode_utf8(environment.at(environment_key("BB_PSN_BACKEND")));
}
}

int wmain(int argc, wchar_t** argv) {
    try {
        require(argc == 3, "Expected fixture DLL and sidecar DLL paths");
        const auto source = fs::absolute(argv[1]);
        const auto sidecar = fs::absolute(argv[2]);
        require(sidecar.filename() == L"bridge_p2p_loader_sidecar.dll", "Unexpected sidecar filename");
        Fixture fixture;
        fixture.isolate();
        fs::copy_file(source, fixture.backend_dir / "psn-bridge-backend.dll");
        {
            Module missing(environment_path(fixture.backend_dir, "psn"));
            require(!missing.value && missing.error == ERROR_MOD_NOT_FOUND,
                    "A backend without its private sidecar did not fail with ERROR_MOD_NOT_FOUND");
        }
        fs::copy_file(sidecar, fixture.backend_dir / sidecar.filename());
        for (const char* host : {"psn", "octr"}) {
            Module module(environment_path(fixture.backend_dir, host));
            require(module.value != nullptr, std::string(host) + " backend path failed raw LoadLibraryExW: " +
                                             std::to_string(module.error));
            using Value = int (*)();
            const auto value = reinterpret_cast<Value>(GetProcAddress(module.value, "bridge_loader_fixture_value"));
            require(value != nullptr && value() == 73, "Loaded fixture did not resolve its adjacent dependency");
            const HMODULE dependency = GetModuleHandleW(L"bridge_p2p_loader_sidecar.dll");
            require(dependency != nullptr, "Fixture sidecar is missing from the loaded module set");
            std::wstring loaded(32768, L'\0');
            const DWORD count = GetModuleFileNameW(dependency, loaded.data(), static_cast<DWORD>(loaded.size()));
            require(count > 0 && count < loaded.size(), "Cannot identify the loaded sidecar");
            loaded.resize(count);
            require(fs::equivalent(fs::path(loaded), fixture.backend_dir / sidecar.filename()),
                    "Loader resolved a sidecar outside the backend directory");
        }
        std::cout << checks << " Windows backend loader checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
