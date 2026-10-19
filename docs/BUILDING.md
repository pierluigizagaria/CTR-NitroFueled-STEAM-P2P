# Building ctrnf-p2p

C and C++20 compilers and CMake 3.20 or newer. External dependencies are the provider's public C header
(`orbisteamworks/osw.h`) and nlohmann/json headers. Neither dependency needs a
sibling source checkout: pass their installed include directories explicitly.
No provider code is linked into the bridge. No Steamworks SDK is needed to build.
The portable Expat XML parser is included as unmodified upstream source under
`third_party/expat`, with its license and pinned source provenance. It is linked
statically; no XML runtime library or system installation is needed.

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DOSW_INCLUDE_DIR=/path/to/public-sdk/include -DJSON_INCLUDE_DIR=/path/to/json/include
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Tests default on and use Python 3, a fake provider DLL/shared library and a fake
launcher that starts a fake HTTP/UDP game, written for these tests. They need no
Steam account, game, server binary or sibling runtime state. Set `-DBUILD_TESTING=OFF` for a build without
Python/tests. Real-provider/publisher and original-game acceptance are separate
optional integration work, never implied by these fixtures.

Windows is the tested execution platform. Shared code uses standard C++20;
platform.cpp isolates library loading and child supervision, and http.cpp isolates
Winsock/POSIX sockets. The POSIX implementation uses a guardian process and an EOF
pipe for child lifetime, including on macOS where Linux parent-death signals are
unavailable. **macOS and Linux builds/runtime are not yet qualified**, and the
native adapter refuses to launch on POSIX (see below). The provider
and native game must independently support the target OS; bridge portability does
not establish their compatibility.
