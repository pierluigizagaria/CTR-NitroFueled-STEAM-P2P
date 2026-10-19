# Building ctrnf-p2p

Requirements: C and C++20 compilers and CMake 3.20 or newer. The external
dependencies are the provider's public C header (`orbisteamworks/osw.h`) and the
nlohmann/json headers; pass their include directories explicitly. No provider
code is linked into the bridge, and no Steamworks SDK is needed to build.

The portable Expat XML parser is included as unmodified upstream source under
`third_party/expat`, with its license and source provenance. It is linked
statically; no XML runtime library or system installation is needed.

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DOSW_INCLUDE_DIR=/path/to/orbisteamworks/include -DJSON_INCLUDE_DIR=/path/to/json/include
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Tests are on by default and use Python 3, a fake provider library and a fake
launcher that starts a fake HTTP/UDP game. They need no Steam account, game or
server binary. Set `-DBUILD_TESTING=OFF` to build without Python and tests. The
tests do not exercise the real provider, server or game.

For release builds with a self-contained MSVC runtime, see
[Releasing](RELEASING.md).

## Platforms

Windows is the tested platform. Shared code uses standard C++20;
`platform.cpp` isolates library loading and child supervision, and `http.cpp`
isolates Winsock and POSIX sockets. The POSIX implementation uses a guardian
process and an EOF pipe for child lifetime, including on macOS where Linux
parent-death signals are unavailable. **macOS and Linux builds have not been
tested**, and the native adapter refuses to launch on POSIX
(see [Architecture](ARCHITECTURE.md#platforms)). The provider and the native
game must support the target OS as well.
