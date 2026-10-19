# Building a Windows preview release

The source repositories and binary artifacts are independent. The mod ZIP is
an assembly of explicit artifacts, not a shared build system or runtime service.

## Build inputs

Build each component at a recorded clean commit and run its ordinary tests.
Use the provider's public header and nlohmann/json headers as explicit bridge
include paths. No host checkout, Steam SDK or game files are build inputs.

For a self-contained MSVC runtime in the bridge build, configure Release with:

```text
-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded -DEXPAT_MSVC_STATIC_CRT=ON
```

The provider shared target already selects the static CRT. To package its
authentication helper without a Visual C++ runtime prerequisite, also configure that
build with `-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`.
Build the server with `go build -trimpath -ldflags "-s -w"`.
Inspect PE dependencies of the final binaries; do not silently collect DLLs
from an installed game directory.

## Independent packages

The provider ZIP contains its DLL, matching public header, authentication helper,
documentation, MIT license and dependency notices. Source consumers of the
static target should build with CMake; a single static archive is insufficient.

The server ZIP contains its executable, example settings, documentation,
PolyForm Shield license, required notices and linked dependency licenses.
Neither package contains user configuration, accounts, databases or Steam files.

Each package supplies a `manifest.json`:

```json
{
  "component": "orbisteamworks",
  "version": "v0.0.1-preview.1",
  "revision": "<full source commit>",
  "license": "MIT",
  "files": {
    "orbisteamworks.dll": "<sha256>",
    "LICENSE": "<sha256>",
    "licenses/nlohmann-json.txt": "<sha256>"
  }
}
```

For the server, use component `demonware-server`, its own version and license,
and `demonware-server.exe`. Include all packaged payload files in the hash map.
Required notices for linked Go modules and the toolchain accompany that binary.

## Assemble the mod

The packager verifies input hashes and selects the runtime files explicitly.
It never copies a profile or installed port directory:

```text
python tools/package_mod.py --bridge-build /path/to/bridge-build --bridge-revision <commit> --provider-package /path/to/provider.zip --server-package /path/to/server.zip --patch-xml /path/to/CrashTeamRacingNitroFueled.xml --patch-license /path/to/patch-LICENSE --patch-revision <commit> --json-license /path/to/json-LICENSE --version v0.1.0-preview.1 --output /path/to/ctrnf-p2p-mod-v0.1.0-preview.1-windows-x64.zip
```

The output includes executable files, example INI, patch XML, operating guides,
per-component notices, a source manifest and SHA-256 file hashes. It deliberately
contains no live INI or patches.json that could replace a user's selections.
The bridge enables the validated signature patch during normal startup.
Keep internal testing procedures, captures and diagnostic executables out of
the player package; the CLI entry point remains available for troubleshooting.
An existing output archive is never overwritten.

Before publishing, inspect archive members, verify hashes after extraction and
run the diagnostic entry point without a game launch. Validate the patch and
configuration against a compatible installation separately; package checks do
not test multiplayer. Publish experimental builds as GitHub
pre-releases, including external SHA-256 checksums and exact source revisions.
