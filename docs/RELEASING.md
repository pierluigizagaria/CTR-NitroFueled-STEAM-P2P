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

`distribution-lock.json` identifies the supported distributions by upstream:
`GetLostIn/CTR-NitroFueled-PC` and `Ryu7w7/OCTR-NitroFueled-PC`. It pins each
original release tag and commit, its P2P-owned integration recipe and SHA-256,
the resulting source commit/tree and the shared PSN contract tree. Recipes and
patches live in `integrations/` with their own GPL license and original authors.
The bridge and distribution tools remain independent MIT components.

Builds fetch the official upstream repository and apply the tracked recipe.
The historical `p2p/channel-a` and `p2p/channel-b` branches remain as checkpoints;
no current build, source export or publisher requires them or writes to their
repository. A recipe records text patches and checked file deletions separately,
so removed optional artwork and original shader blobs are not embedded in patches.
Reconstruction verifies every patch hash and the exact generated commit/tree.

Run **Prepare complete P2P distributions** with the existing preview version.
Both upstream distributions are reconstructed and their exact submodules are
initialized. The bridge/provider/server keep independent builds and public
interfaces. Each host uses its own MSYS2 build and portable packager; the optional
PSN backend is built and tested independently before assembly. Stock updater
replacement is disabled in the integration build.

The workflow installs the compiler/library archives pinned by URL and SHA-256 in
`tools/msys2-packages.json`. It uses the runner's existing MSYS base and records
source/build evidence; runner images and system tools remain external inputs,
so binary-identical builds are not claimed. A build never follows a floating
host branch. Embedded Python and iced-x86 archives remain pinned by the host's
committed portable recipe.

Each Windows package contains the host, backend and its DLL dependencies, mod,
default configuration and component notices. `p2p-distribution-manifest.json`
binds every payload hash to the upstream identity, recipe and source companion.
The host build receipt binds the launcher, runtime, capabilities helper and
backend to their generated source revision, tree and recipe. Assembly rejects
mismatched sources or binaries. New archive names use
`getlostin-ctr-nitrofueled-pc` and `ryu7w7-octr-nitrofueled-pc` plus the P2P source
revision. Existing preview assets and their historical names are preserved.

The matching `*-source.zip` contains the exact host Git tree, recursively pinned
submodule trees, original licenses, the P2P-owned host integration recipes,
distribution build scripts and pinned JSON header. The host build applies its
recorded FSR patches to the original submodule source. Mutable working-tree
files and installed profiles are never copied. Original Git modes are recorded
in the manifest; ZIP stores symbolic-link targets as text for explicit restoration
on Unix. This workflow qualifies only Windows builds.

`tools/msys2-source-lock.json` pins corresponding-source archives for bundled
copyleft DLLs and directly compiled dependencies, including their MSYS2 recipes
and patches. Complete dependency license texts accompany both binary and source
packages. Missing source evidence, unknown runtime DLLs, changed hashes or dirty
build recipes make a package ineligible for release. The host's original
GPL-2.0-or-later notice remains; this build linked to GPLv3 FFmpeg is distributed
under GPLv3 or later. MIT, PolyForm Shield and Valve components retain their own
licenses.

Known optional upstream game artwork and cached HUD shader blobs are omitted,
with hashes and reasons recorded. Licensed fonts/backgrounds and AMD FSR shaders
remain. The integration obtains original HUD shaders from the player's own game
cache when needed. No game dumps, saves, databases or installed settings are
accepted as packaging inputs. If a portable archive supplies `bbport.ini`, its
bytes must match committed portable defaults. Players preserve their settings
when updating.

Reconstruct and build one distribution locally:

```text
python tools/ci_distribution.py --channel getlostin-ctr-nitrofueled-pc --materialize --host-source out/hosts/getlostin --version v0.1.0-preview.1 --msys-root /path/to/msys64 --mod-package /path/to/verified-mod.zip --require-redistribution-ready
```

For explicit prebuilt inputs omit `--materialize` and add `--host-package`,
`--host-build-manifest` and `--backend-dir`. The source checkout must match the
locked reconstruction, and the receipt must bind its source tree and recipe.
Commit reviewed recipes and locks before producing releasable source archives.
For local assembly inspection before committing, omit the final readiness flag;
the manifest reports incomplete readiness. Existing output ZIPs are never
overwritten. `--ninja` and `--revision-asset` on `tools/ci_build.py` support an
initialized local MSVC environment and additive mod assets.

With `create_draft` selected, both distributions and their source companions must
pass before a draft prerelease is created. That helper never replaces existing
tags/releases. The automatic workflow below supports additive publication to the
existing preview. Offline checks do not establish live Steam or multi-PC acceptance.

To refresh toolchain or dependency evidence, use `tools/lock_msys2.py capture`
and `tools/msys2_source_evidence.py capture` against a reviewed local toolchain
and clean host/backend DLL directories. Review URLs, versions and hashes before
committing. Ordinary CI consumes only checked-in dependency pins.

## Following upstream releases

**Automatic P2P releases** runs daily at 06:17 UTC and on manual dispatch from
`main`. It checks the official repositories' latest stable releases, resolves
tags to exact commits, and applies each tracked adapter recipe in an isolated
candidate under the P2P checkout. A changed PSN contract, rewritten upstream
history, patch conflict, unknown dependency, missing license/source evidence or
failed check stops the run. Existing public assets remain available.

Both distributions are rebuilt when either upstream changes. Each job reconstructs
the plan with fixed commit metadata and verifies the generated SHAs and trees.
The prospective P2P commit changes only `distribution-lock.json`, giving packages
a unique source suffix without changing the preview version. Recipe modifications
remain reviewed source changes; unattended updates cannot change patches or the
shared PSN contract. The mod, adapters, package hashes and corresponding sources
must all pass before publication.

The trusted publisher validates archives against the external plan, uploads
sources before binaries and promotes only this repository's `main`, with an
explicit lease. Generated host commits are reproducible source identifiers,
not refs that need publishing in a separate host fork. Full corresponding source
archives and recipes are published alongside the binaries. Existing release tags
and assets are never replaced. A completion receipt lists the inputs, revisions
and ten asset hashes; release notes link the latest completed build.

Every automatic publication also provides the compiled standalone mod ZIP and
checksum: the exact input used by both complete distributions. Manual installation
requires a compatible host with the adapter and backend dependencies documented
in `OCTR.md`; copying mod files alone cannot add this interface to current stock
upstream binaries. Independent provider/server and compiler/dependency pins
remain reviewed inputs.

Only the publisher receives repository write access. There is no host deploy key
or cross-repository write credential. Build jobs have read access and no persisted
checkout credentials. The notification job can assign failures to the configured
owner; GitHub inbox/email delivery follows that account's notification settings.
`automation.json` configures the existing preview tag, commit identity and owner.
The separate `automation/state` branch keeps a public, non-secret stop/recovery
record. Failed runs open or update one incident; scheduled runs stay stopped
without repeated build attempts.

Manual modes:

- `auto`: check stable releases; do nothing when unchanged or stopped.
- `retry`: prepare and test a fresh candidate after fixing a failure. If pins
  are current, verify them and clear the stop without republishing existing names.
- `resume`: complete a pending publication with its original plan and artifacts.
- `verify`: build/test current pins and check publisher access without publishing.
- `publish-pinned`: explicitly build and publish the current reviewed pins, for
  changes such as this migration that do not depend on a new upstream release.

GitHub ref updates and release asset uploads are separate operations. A failed
publication can leave tested assets visible before the completion receipt exists.
The pending record keeps exact hashes, before/after refs and the original Actions
run. Resume never rebuilds or overwrites assets; unrelated remote changes require
manual resolution. Original artifacts are retained for 90 days and cannot be
silently replaced by a rebuild if they expire. Preserve them for recovery.

For local diagnosis, prepare one candidate without publishing:

```text
python tools/prepare_upstream_update.py --repository . --lock distribution-lock.json --channel getlostin-ctr-nitrofueled-pc --upstream-tag <new-tag> --upstream-revision <full-commit>
```

The helper verifies the official tag and applies the tracked recipe to an isolated
checkout. Conflicts stop and retain the candidate for inspection. The lock and
historical branches stay intact. Fix the P2P-owned recipe or reviewed dependency
evidence as necessary, review the resulting lock, and run `retry`. Never bypass
contract or package checks to clear a stop. This helper makes no remote writes;
publication and recovery remain the trusted publisher's responsibility.
