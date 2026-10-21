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
For this mod-only workflow, the native host and original game are compatibility
requirements. The complete distribution workflow below also builds the host.

## Complete P2P distributions

`distribution-lock.json` pins two independent integration branches,
`p2p/channel-a` and `p2p/channel-b`, in the contribution repository. Neutral channel
names do not remove the upstream identity: each lock and package records the
original repository, release tag, upstream commit, integration commit and shared
PSN module tree. Both branches must expose the same reviewed PSN contract tree.

Run **Prepare complete P2P distributions** with the existing preview version.
Each channel is rebuilt from its exact commit and recursively initialized
submodules. The bridge/provider/server keep their independent builds and public
interfaces. The host uses its own MSYS2 build and portable packager; the optional
PSN backend is built and tested independently before assembly. Stock updater
replacement is disabled in the integration build.

The complete workflow installs the compiler/library archives pinned by URL and
SHA-256 in `tools/msys2-packages.json`. It uses the runner's existing MSYS base and
records source/build evidence; runner images and system tools remain external
inputs, so this is not a claim of bit-identical builds. It never follows a floating
host branch or downloads a `latest` release during a build. The embedded Python
and iced-x86 archives remain pinned by the host's committed portable recipe.

The Windows package contains the host, backend and its DLL closure, mod, default
configuration and per-component notices. `p2p-distribution-manifest.json` binds
every payload hash to the selected channel and source companion. A separate
`host-build-manifest.json` input binds the launcher, runtime, capabilities helper
and backend hashes to the actual clean build receipt; the assembler rejects stale
or mismatched binaries. Sources and binaries have channel-specific filenames and
the bridge source suffix, preserving existing preview assets and versions.

The companion `*-source.zip` contains the exact host Git tree, recursively pinned
submodule trees, original licenses, tracked patch recipes, the distribution build
scripts and the pinned JSON header. The host build applies its recorded FSR
patches to the original submodule source. Neither modified working-tree files nor
installed profiles are copied. Original Git file modes are recorded in its
manifest; ZIP stores symbolic-link targets as text for explicit restoration when
building on Unix. This workflow qualifies only Windows builds.

`tools/msys2-source-lock.json` pins corresponding-source archives for bundled
copyleft DLLs and directly compiled host dependencies, including their MSYS2
recipes and patches. It also pins complete license texts, extracted from the
installed packages or source archives. Those texts accompany both binary and
source packages. Missing source evidence, an unknown runtime DLL, changed hashes
or a dirty build recipe make a package ineligible for release. The host's original
GPL-2.0-or-later notice remains; the build linked to GPLv3 FFmpeg is distributed
under GPLv3 or later. Independent MIT, PolyForm Shield and Valve components retain
their own licenses.

Known optional upstream game artwork and original cached HUD shader blobs are
omitted, with hashes and reasons recorded. Licensed fonts/backgrounds and AMD FSR
shaders remain. The integration obtains original HUD shaders from the player's
own game cache when needed. No game dumps, saves, databases or installed settings
are accepted as packaging input. When a portable archive supplies `bbport.ini`,
its bytes must match the committed portable defaults exactly; current channels
ship `bbport.default.ini` instead. Players preserve their existing settings when
updating.

Use explicit local build inputs without rebuilding the host:

```text
python tools/ci_distribution.py --channel channel-a --version v0.1.0-preview.1 --host-source /path/to/pinned-host --msys-root /path/to/msys64 --host-package /path/to/host-portable.zip --host-build-manifest /path/to/host-build-manifest.json --backend-dir /path/to/backend-dlls --mod-package /path/to/verified-mod.zip --require-redistribution-ready
```

Commit the reviewed recipes and locks before producing releasable source archives.
For a local source/assembly inspection before that commit, omit the final flag;
the manifest reports incomplete release readiness rather than claiming a clean
recipe. Outputs are never overwritten. `--ninja` and `--revision-asset` on
`tools/ci_build.py` support an initialized local MSVC environment and additive
mod assets without changing the preview version.

With `create_draft` selected, both channels and their matching source companions
must pass validation before the workflow creates a draft prerelease. Existing
tags/releases are never replaced by that helper. Manual runs of this workflow
produce CI artifacts or a new draft. The separate automatic release workflow
below publishes additive assets to the existing first preview after all checks.
Offline tests are separate from live Steam and multi-PC game acceptance.

To refresh the toolchain or dependency evidence, use `tools/lock_msys2.py capture`
and `tools/msys2_source_evidence.py capture` against a reviewed local toolchain
and the clean host/backend DLL directories. Review the resulting JSON changes,
including new source URLs, package versions and hashes, before committing them.
`materialize` and ordinary CI consume only those checked-in pins.

## Following upstream releases

**Automatic P2P releases** runs daily at 06:17 UTC and on manual dispatch from
`main`. It checks each official repository's latest stable release, resolves the
tag to an exact commit, and replays that channel's adapter commits in an isolated
candidate. Already-adopted changes are dropped. The existing channel and release
stay in place while the candidates are built and tested. A changed PSN contract,
rewritten upstream history, conflict, unknown dependency, missing source/license
evidence or failed check stops the run.

Both channels are rebuilt even when only one upstream changed. Each job recreates
the planned commits with fixed commit metadata and verifies the resulting SHAs.
The prospective bridge commit changes only `distribution-lock.json`, giving the
new packages a unique source suffix without changing the preview version.
The mod, host adapters, package hashes and corresponding sources must all pass.
These offline checks do not launch the game or establish multi-PC acceptance.

The final job validates both archives against the external plan, uploads sources
before binaries, atomically advances the two host branches with explicit leases,
and advances bridge `main` with a lease. Old and new host revisions receive
immutable source tags. Existing release tags and assets are never replaced.
A completion receipt lists the exact inputs, revisions and ten asset hashes;
the release notes link the latest completed build. Independent provider/server
pins and compiler/dependency pins remain reviewed inputs, not floating updates.

Each automatic publication also keeps the compiled standalone mod ZIP and its
checksum. It is the exact input used by both complete channel packages, validated
against their assembly receipts and component pins. Its default configuration
targets the supported legacy native host; manual PSN/OCTR installation requires
a compatible host with the PSN adapter and backend dependencies described in
`OCTR.md`. An unmodified current upstream binary does not gain that interface
by copying the mod files alone.

Only the publisher has `contents: write` and the Actions secret
`P2P_HOST_DEPLOY_KEY`. That dedicated write deploy key belongs only to the host
integration repository. Build jobs have read access and no persisted checkout
credentials. GitHub's SSH host key is pinned in `tools/github_known_hosts`.
Actions are disabled in the controlled host fork: imported upstream workflows
cannot run there when integration branches or source tags are promoted.
The notification job has issue access to assign failures to the configured owner.
GitHub inbox/email delivery follows that account's notification settings.

`automation.json` configures the existing preview tag, controlled host repository,
commit identity and notification assignee. The separate `automation/state`
branch stores a public, non-secret stop/recovery record. Failed runs open or
update one issue; scheduled runs then stay stopped without repeated build attempts.
Use **Run workflow** with these modes:

- `auto`: check for new stable releases; do nothing when unchanged or stopped.
- `retry`: after fixing a conflict/check, prepare and test a fresh candidate.
  If upstream pins are already current, verify them and clear the stop without
  rebuilding assets under existing release filenames.
- `resume`: finish a pending publication using its original plan and artifacts.
- `verify`: build/test current pins and check publisher access, without releasing.

GitHub cannot update two repositories and release assets in one transaction.
A failed publication can leave tested assets visible before its completion receipt
exists. Its pending record keeps the exact hashes, prior/new refs and original
Actions run. Resume never rebuilds or overwrites an asset. Recovery accepts only
the recorded before/after states; unrelated changes require manual resolution.
If bridge promotion loses a race, host rollback also uses explicit leases.
Artifacts are retained for 90 days; deleted or expired original artifacts cannot
be silently substituted with a rebuild. Preserve the original files for recovery.

For local diagnosis, prepare one isolated candidate without publishing:

```text
python tools/prepare_upstream_update.py --lock distribution-lock.json --channel channel-a --host-source /path/to/host-checkout --upstream-tag <new-tag> --upstream-revision <full-commit>
```

The helper verifies the official tag, creates a new candidate branch/worktree,
then replays the integration commits. Commits already adopted upstream are
dropped. A conflict stops the replay and preserves the candidate for resolution;
the existing channel and lock remain intact. The result includes the commands
needed to continue or abort and the checks required before promoting the candidate.

For a stopped update, fix the adapter or refresh reviewed dependency evidence
when needed, keep the lock aligned with its published integration branch, and
run `retry`. Never bypass the common PSN contract or package checks to clear a stop.
The low-level helper itself makes no remote writes; the automatic publisher owns
promotion and its recovery record.
