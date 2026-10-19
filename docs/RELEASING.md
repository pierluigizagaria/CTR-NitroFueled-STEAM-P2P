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
python tools/package_mod.py --bridge-build /path/to/bridge-build --bridge-revision <commit> --provider-package /path/to/provider.zip --server-package /path/to/server.zip --patch-xml /path/to/CrashTeamRacingNitroFueled.xml --patch-license /path/to/patch-LICENSE --patch-revision <commit> --json-license /path/to/json-LICENSE --steam-sdk-archive /path/to/steamworks_sdk_165.zip --steam-sdk-version 1.65 --steam-runtime-sha256 <verified-dll-sha256> --version v0.1.0-preview.1 --output /path/to/ctrnf-p2p-mod-v0.1.0-preview.1-windows-x64.zip
```

Supply an SDK archive obtained from Valve under its
[SDK Access Agreement](https://partner.steamgames.com/documentation/sdk_access_agreement).
Confirm its version from `sdk/Readme.txt`, verify the Valve Authenticode signature
of `sdk/redistributable_bin/win64/steam_api64.dll`, and record its SHA-256 as the
explicit packaging input. The packager reads only that DLL, rejects a duplicate
entry or a hash mismatch, and records its SDK version, license and hash in the
manifest. Keep the SDK archive and all Valve binaries outside source control.
The independent provider and server archives remain free of Steamworks files.

The output includes executable files, the unchanged Steam API redistributable,
a ready-to-use `ctrnf-p2p.ini`, patch XML, operating guides, per-component notices,
a source manifest and SHA-256 file hashes. The Valve runtime notice is at
`licenses/steamworks/NOTICE.txt`; its proprietary license remains separate.
The packaged INI comes only from the tracked `ctrnf-p2p.example.ini` template:
Steam, AppID 480, native host and normal progression. Never package an installed
user's configuration. The update instructions tell users to preserve their
existing INI. No native settings or `patches.json` are included.
The bridge enables the validated signature patch during normal startup.
Keep internal testing procedures, captures and diagnostic executables out of
the player package; the CLI entry point remains available for troubleshooting.
An existing output archive is never overwritten.

Before publishing, inspect archive members, verify hashes after extraction and
run the diagnostic entry point without a game launch. Validate the patch and
configuration against a compatible installation separately; package checks do
not test multiplayer. Publish experimental builds as GitHub
pre-releases, including external SHA-256 checksums and exact source revisions.

## Automated Windows builds and releases

GitHub Actions runs the ordinary offline tests on pull requests and pushes to
`main`. Builds use Windows Server 2022, Python 3.11.9 and CMake 3.31.10 with Visual Studio 2022 x64. Hosted runner images
can change; manifests record their image version and source commit. This is
dependency pinning and traceability, not a claim of bit-identical compiler output.

Open **Actions → Prepare mod release → Run workflow**, select `main`, and enter
a version such as `v0.1.0-preview.1`. With `create_draft` selected, successful
checks create a **draft prerelease** with the ZIP and external SHA-256 checksum.
An existing release or conflicting tag is never replaced. For a packaging-only
trial, clear `create_draft` and download the ZIP from the run's Artifacts.
No new secret or personal token is required; only the draft job has write access.

Inspect and test the downloaded package before publishing the draft. Offline
fixtures do not establish live Steam or multi-PC game acceptance. Keep user
configuration, databases, installed profiles and game files out of packages.

Run the same build locally from the repository root with CMake/Go and Python on
PATH: `python tools/ci_build.py --package --version v0.1.0-preview.1`.
Builds use ignored output directories and refuse to overwrite an existing ZIP;
choose a fresh version or archive the earlier output before rebuilding.
The existing first preview release is not changed by adding these workflows.

`release-lock.json` is the reviewed recipe for the combined mod. It pins exact
component archive checksums, versions, source commits, the supported native host,
JSON headers and the Steam runtime. The bridge compiles against the public header
inside the same provider package whose DLL is shipped. Every package manifest
and payload hash is verified before assembly. The release ZIP includes the lock
and build information alongside its source manifest and checksum inventory.

The initial Steam runtime source is the already-published first mod ZIP. Only its
original `steam_api64.dll` is selected, after checking both the archive and DLL
SHA-256 and Valve's Authenticode signature. The lock retains the original SDK
version and archive hash. No SDK credentials or full SDK upload is required.
If this bootstrap asset is replaced or unavailable, the build fails;
update the lock only to a reviewed source containing the exact authorized runtime.

To update a component, publish its independent tested package, update its URL,
archive hash, source revision and version in the lock, and open a PR. Merging an
updated lock does not release the mod automatically. Run the manual workflow to
prepare the selected combination. Never substitute `latest` or a branch URL.
The native host and original game are compatibility requirements, not build inputs.
