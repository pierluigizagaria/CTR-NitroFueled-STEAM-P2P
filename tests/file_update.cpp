#include "platform.h"
#include <chrono>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <stdexcept>
#ifdef _WIN32
#include <windows.h>
#endif

namespace {
using namespace bridge;
int checks = 0;
void require(bool value, const char* message) {
    ++checks;
    if (!value) throw std::runtime_error(message);
}
void rejects(const std::function<void()>& operation) {
    bool failed = false;
    try { operation(); } catch (const std::exception&) { failed = true; }
    require(failed, "A conflicting or inaccessible update was accepted");
}
std::string read(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Cannot read fixture");
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
struct Fixture {
    fs::path root;
    Fixture() {
        root = fs::current_path() / ("file-update-fixture-" +
            std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        if (!fs::create_directory(root)) throw std::runtime_error("Cannot create isolated fixture");
    }
    ~Fixture() {
        std::error_code error;
        fs::permissions(root / "patches.json", fs::perms::owner_write, fs::perm_options::add, error);
        fs::remove_all(root, error);
    }
    void no_temporary_files() const {
        for (const auto& entry : fs::directory_iterator(root))
            require(!entry.path().filename().string().starts_with(".ctrnf-p2p-update-"), "Temporary update file leaked");
    }
};
}

int main() {
    try {
        Fixture fixture;
        const auto file = fixture.root / "patches.json";
        replace_file_atomically(file, std::nullopt, "first");
        require(read(file) == "first", "Missing target was not created");
        replace_file_atomically(file, "first", "second");
        require(read(file) == "second", "Existing target was not replaced");
        fixture.no_temporary_files();

        rejects([&] { replace_file_atomically(file, std::nullopt, "overwritten"); });
        require(read(file) == "second", "A newly created target was overwritten");
        rejects([&] { replace_file_atomically(file, "stale!", "overwritten"); });
        require(read(file) == "second", "Changed bytes were overwritten");
        rejects([&] { replace_file_atomically(file, "short", "overwritten"); });
        require(read(file) == "second", "Changed size was overwritten");
        rejects([&] { replace_file_atomically(fixture.root / "removed.json", "old", "new"); });
        require(!fs::exists(fixture.root / "removed.json"), "Removed target was recreated");
        rejects([&] { replace_file_atomically(fixture.root / "missing" / "patches.json", std::nullopt, "new"); });
        require(!fs::exists(fixture.root / "missing"), "Parent directories were created");
        fixture.no_temporary_files();

        fs::permissions(file, fs::perms::owner_read, fs::perm_options::replace);
        rejects([&] { replace_file_atomically(file, "second", "new"); });
        require(read(file) == "second", "Read-only target was truncated");
        fs::permissions(file, fs::perms::owner_write, fs::perm_options::add);
        fixture.no_temporary_files();

#ifdef _WIN32
        HANDLE locked = CreateFileW(file.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        require(locked != INVALID_HANDLE_VALUE, "Cannot lock fixture");
        rejects([&] { replace_file_atomically(file, "second", "new"); });
        CloseHandle(locked);
        require(read(file) == "second", "Locked target was truncated");
        fixture.no_temporary_files();
#else
        const auto permissions = fs::status(file).permissions();
        replace_file_atomically(file, "second", "second");
        require(fs::status(file).permissions() == permissions, "Existing file permissions changed");
        const auto link = fixture.root / "linked.json";
        fs::create_symlink(file.filename(), link);
        rejects([&] { replace_file_atomically(link, "second", "new"); });
        require(read(file) == "second", "Symlink target was overwritten");
#endif
        const std::string large(150000, 'x');
        replace_file_atomically(file, "second", large);
        require(read(file) == large, "Multi-block replacement was incomplete");
        replace_file_atomically(file, large, "");
        require(read(file).empty(), "Empty replacement was incomplete");
        replace_file_atomically(file, "", "final");
        require(read(file) == "final", "Empty existing target was not replaced");
        const auto directory = fixture.root / "directory";
        fs::create_directory(directory);
        rejects([&] { replace_file_atomically(directory, "", "new"); });
        require(fs::is_directory(directory), "Directory target changed");
        fixture.no_temporary_files();
        std::cout << checks << " atomic file update checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
