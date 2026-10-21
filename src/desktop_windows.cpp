#include "app.h"
#include "platform.h"
#include <windows.h>
#include <shellapi.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::string utf8(const wchar_t* value) {
    const int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, nullptr, 0, nullptr, nullptr);
    if (!count) throw std::runtime_error("Cannot read the launch arguments");
    std::string result(static_cast<size_t>(count), '\0');
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, result.data(), count, nullptr, nullptr))
        throw std::runtime_error("Cannot read the launch arguments");
    result.pop_back();
    return result;
}

void show_failure(const std::string& reason) {
    const std::string message = "CTR-NitroFueled-STEAM-P2P stopped.\n\n" + reason +
        "\n\nSession log: ctrnf-p2p\\bridge.log beside the application.";
    const int count = MultiByteToWideChar(CP_UTF8, 0, message.c_str(), -1, nullptr, 0);
    std::wstring wide(static_cast<size_t>(count), L'\0');
    if (count) MultiByteToWideChar(CP_UTF8, 0, message.c_str(), -1, wide.data(), count);
    MessageBoxW(nullptr, count ? wide.c_str() : L"CTR-NitroFueled-STEAM-P2P could not start.",
                L"CTR-NitroFueled-STEAM-P2P", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
}

class LogStreams {
public:
    explicit LogStreams(std::ostream& output)
        : out_(std::cout.rdbuf(output.rdbuf())), error_(std::cerr.rdbuf(output.rdbuf())) {}
    ~LogStreams() { std::cout.rdbuf(out_); std::cerr.rdbuf(error_); }
private:
    std::streambuf* out_;
    std::streambuf* error_;
};
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    try {
        // A Windows subsystem executable never allocates or hides the caller's
        // console. Command-line users have the separate console entry point.
        const auto state = bridge::executable_path().parent_path() / "ctrnf-p2p";
        std::filesystem::create_directories(state);
        std::ofstream log(state / "bridge.log", std::ios::app);
        if (!log) throw std::runtime_error("Cannot open the private session log");
        log << "\nStarting CTR-NitroFueled-STEAM-P2P desktop session.\n";
        LogStreams streams(log);
        int count = 0;
        auto args = CommandLineToArgvW(GetCommandLineW(), &count);
        if (!args) throw std::runtime_error("Cannot read the launch arguments");
        std::vector<std::string> values;
        try {
            for (int i = 0; i < count; ++i) values.push_back(utf8(args[i]));
        } catch (...) { LocalFree(args); throw; }
        LocalFree(args);
        std::vector<char*> argv;
        for (auto& value : values) argv.push_back(value.data());
        argv.push_back(nullptr);
        std::string failure;
        const int result = bridge_main(count, argv.data(), &failure);
        log.flush();
        if (result) show_failure(failure.empty() ? "The native launcher exited with an error." : failure);
        return result;
    } catch (const std::exception& error) {
        show_failure(error.what());
        return 1;
    }
}
