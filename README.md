# ctrnf-p2p

A local process that connects an unchanged native host to a platform provider
through the public orbiSteamworks C API. It owns its configuration, HTTP adaptation
and process lifetime. Steam, endpoint allocation, peer authorization and opaque
transport belong to the provider. Demonware, CTR matchmaking and local progression
belong to the separate local server (demonware-server). Native paths, saves and
preferences belong to the port. No source from the host, provider or server is
incorporated here. License: MIT.

The first host adapter targets GetLostIn `online` at
`b1b4bf9647132822147e76aeec47390c6cb157bf`. It does not require a host source change.
The provider must support `loopback-v1`, configurable AppID and raw persona lookup.
An older or incomplete provider is refused before starting the game. There is no
fallback to another provider. A future shadNet provider can implement the same C
API; a future shadPS4 host protocol adapter is a separate concern.

## Build

C and C++20 compilers and CMake 3.20 or newer. External dependencies are the provider's public C header
(`orbisteamworks/osw.h`) and nlohmann/json headers. Neither dependency needs a
sibling source checkout: pass their installed include directories explicitly.
No provider code is linked into the bridge. No Steamworks SDK is needed to build.
The portable Expat XML parser is included as unmodified upstream source under
`third_party/expat`, with its license and pinned source provenance. It is linked
statically; no XML runtime library or system installation is needed.

```text
cmake -S . -B build -DOSW_INCLUDE_DIR=/path/to/public-sdk/include -DJSON_INCLUDE_DIR=/path/to/json/include
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

## Install

The mod is installed directly into the root folder of an existing native port
installation (the folder with `CTR-NitroFueled-PC.exe`, `run.py`, `bbport.ini` and
`patches/`). The bridge executable's folder is the port root: no setting names it.

```text
<port root>/
├── CTR-NitroFueled-PC.exe        native launcher (unchanged)
├── bbport.ini, launcher.ini, user/, out/, patches/, patches.json   native, unchanged
├── ctrnf-p2p.exe, ctrnf-p2p.ini  desktop bridge and its configuration
├── ctrnf-p2p-cli.exe             console entry point for diagnostics/scripts
├── ctrnf-p2p/                    bridge-owned state and diagnostics only
├── demonware-server.exe          the independent local server
├── demonware-server/             its data/ctrnf.db and logs/
├── orbisteamworks.dll            the provider
└── steam_api64.dll               user-supplied Steam API library
```

Place the user-supplied Steam API library beside the bridge executable; nothing
from Steamworks is included or distributed. `steam_appid.txt` is neither required
nor consulted: `steam.app_id` is the only AppID source.

Install the CTR:NF Server Signature Patch XML into the port's `patches/` folder and
enable `CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch` in the port's
existing `patches.json` (`enabled` list), keeping its other selections. The release
file is disabled by default; copying it alone does not activate it. The local server
sends unsigned authentication replies: the game's verifier then fails and this patch
removes the rejection of that failure. No response-signing key or OpenSSL is needed.
The patch supports only the verified CUSA13795 01.21 `eboot.bin` (see its own
documentation); the bridge does not inspect the game files.

## Run

On Windows, double-click `ctrnf-p2p.exe`. It opens the native launcher without a
terminal window. Lifecycle messages go to `ctrnf-p2p/bridge.log`; a startup or
session error appears in a dialog. Close the native launcher to end the session.
The console entry point runs the same bridge logic and keeps stdout, stderr and
exit codes available to terminals and scripts:

```text
ctrnf-p2p-cli --check
ctrnf-p2p-cli --probe
ctrnf-p2p-cli --directory-check
ctrnf-p2p-cli
```

On POSIX the console executable is still named `ctrnf-p2p`; there is no desktop
entry point, and native game launch remains unsupported there.

Copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini` beside the executable. Relative
paths resolve beside the executable, even with `--config`; `--config path` itself
resolves from the current working directory.

`--check` validates the configuration, the provider, Steam and server files, and the
launch prerequisites (native launcher and signature patch selection) without
starting anything. `--probe` starts the provider, the hidden local server and the
HTTP listener, verifies readiness and stops them; it does not start a game or
qualify game/peer transport. `--directory-check` additionally creates a temporary
room, reads it, requires that exact room in search and leaves it. These two
portable diagnostics do not need the native launcher or the patch.

An ordinary launch starts the port's own launcher; the player starts the game from
it as usual. Everything native (game folder, saves, preparation, patches, graphics,
input, language, restart) is handled by the port with its own settings. The session
belongs to the first game process that opens the game's UDP socket: when that game
exits, including the native in-game "Apply and restart", the bridge ends the session
and closes the launcher. Relaunch the bridge to play online again. Closing the
launcher before starting a game also ends it. Windows uses a kill-on-close Job
Object for the launcher and all its descendants; the provider owns its own server.
Host exit, bridge teardown, provider/server failure or a Steam account change tears
the session down. There is no menu-idle or elapsed-session cutoff.

## Configuration

Unknown/duplicate sections or settings and invalid values stop startup. There are
no aliases for removed settings. Boolean values are exactly `true` or `false`.
Integers are decimal. Full-line `;`/`#` comments are accepted. Unquoted inline
comments start after whitespace; a JSON quoted string keeps such punctuation.
Paths passed to the bridge must be printable ASCII.

The configuration holds only bridge settings and the links between its components.
Native paths, saves and preferences are never copied here.

| Setting | Default and meaning |
| --- | --- |
| platform.provider | `steam`; other providers are currently unsupported |
| steam.app_id | `480`; nonzero uint32. Every peer must use the same licensed AppID |
| game.host | `native`; selects the bridge's host adapter, not a native setting |
| server.unlock_all | `false`; forwarded to the server's `CTR_UNLOCK_ALL`. Same saves and database in both modes |

Advanced settings, omitted from the example:

| Setting | Default and meaning |
| --- | --- |
| platform.library | `orbisteamworks.dll` on Windows, `liborbisteamworks.dylib` on macOS, `liborbisteamworks.so` on other POSIX targets |
| steam.library | `steam_api64.dll` on Windows, `libsteam_api.dylib` on macOS, `libsteam_api.so` otherwise; must be beside the bridge executable |
| server.executable | `demonware-server.exe` on Windows, `demonware-server` elsewhere, beside the bridge. Its working folder is `demonware-server/` beside that executable, with `data/` (passed as `DATA_DIR`) and `logs/` |
| session.realm | `ctrnf-p2p`; at most 64 bytes, same for all peers. Matchmaking namespace only: never economy or progression |
| network.address | `127.0.0.2`; loopback address in 127.0.0.2–254 for the bridge front and the server listeners. Distinct instances on one PC need distinct addresses |
| network.http_port | `31380`; the native HTTP front; must not collide with the server listeners |
| lab.enabled, lab.account_id, lab.root, lab.online_id | Off. Explicitly simulated local backend for fixtures/Lab only, never a Steam fallback; all four are required together |

The native adapter fixes the rest of the contract: Demonware title `5760` (the PS4
asset title CUSA13795 is a different identifier), build `01.21`, the game's UDP
source as observed at `127.0.0.1`, the server's auth listener on port `8460` of
`network.address`, and native-token admission (`CTR_LOCAL_WEAK_TOKEN=1`), because
the unchanged host fabricates its token. The server's own default for that mode
stays disabled; a future host adapter declares its own requirements.

## Identity, persistence and security boundary

The SteamID and the displayed name always come from the connected Steam account;
there is no production name override. The ASCII mapping retains printable
0x20–0x7e, replaces non-ASCII Unicode characters with `_`, trims spaces and limits
to 16 bytes. Control bytes become `_`; an all-blank persona refuses to start. The
same name goes to the provider, `BB_ONLINE_ID` and `BB_USER_NAME`. Native upstream
then separately rewrites its NP ID to `[A-Za-z0-9_-]` and pads names shorter than
3 characters; UserService retains `BB_USER_NAME`. This difference is documented
rather than patched. AppID identifies the application, SteamID the account, and the
online ID is only the displayed name.

The SteamID64 is passed as decimal `BB_ONLINE_ACCOUNT_ID`. Native upstream fabricates
its sacredfire token; native-token admission only checks that its account is the
current pipe owner and the actual request source is loopback. **Any local process
able to impersonate that owner format can attempt admission.** This is weaker than
the provider's random pipe capability. Name text is not the authentication key.
It must never be exposed as central/public admission.

The identity is read once per session. If another Steam account signs in behind the
same client, the provider fails the context and the bridge ends the session; relaunch
to play as that account. The server's one database (`demonware-server/data/ctrnf.db`)
keeps each account's progression under its SteamID, so A → B → A preserves both, and
normal/unlock-all share it: unlock-all makes the catalog available without recording
it as owned, while races, challenges and statistics count in both modes. Returning to
normal shows real purchases, coins and progress again. The native save is the port's
and is shared by every account and both modes; the bridge never selects, copies,
resets or edits saves. Use the port's own save-folder settings for separation.
Each server exposes only the documented room/opaque race contracts to peers;
progression and server files stay local.

## Native adapter and HTTP front

The launcher inherits the bridge's environment except stale bridge, provider,
server and online settings (`OSW_*`, `CTR_*`, `NEXTENDO_*`, `SHADNET_*`, `D3_*`,
`DASH_*`, `BB_ONLINE_*`, `BB_USER_NAME`, `STEAMAPPID`, `STEAMGAMEID`; compared
case-insensitively on Windows). Other native `BB_*` values pass through unchanged.
The bridge then sets only `BB_ONLINE_SERVER`, `BB_ONLINE_HTTP_PORT`, `BB_ONLINE_ID`,
`BB_USER_NAME`, `BB_ONLINE_ACCOUNT_ID` and `BB_ONLINE_ALLOW=127.0.0.1`. The port's
launch script lets these environment values win over `bbport.ini`; the explicit
loopback allow list keeps `bbport.ini` `online_allow` from widening the game's
reachable addresses. The native launcher may still show its own online fields.

Before an ordinary launch (and in `--check`) the bridge reads, without writing, the
patch selection the native launch script will use: `BB_PATCHES_CONFIG`, else
`patches.json` in `BB_DATA_DIR` (else the port root), and `BB_PATCHES_DIR`, else
`patches/`. Relative values resolve from the port root, as the script does. The
patch must be listed under `enabled` and not under `disabled`. Its XML is parsed
as a complete document; comments and CDATA cannot supply patch elements, malformed
documents and DTDs are refused. The selected patch must name CUSA13795, AppVer
01.21, `eboot.bin` and the supported write. This is a
configuration diagnostic: the launcher can change the selection afterwards, and
other selected patches are not inspected for conflicts.

The bridge discovers the IPv4 UDP socket owned by exactly one process of its own
job. It accepts only one distinct port bound to wildcard or `127.0.0.1`; several
owning processes or ports fail closed, and an unrelated process cannot supply it.
The session is pinned to that process (ID and start time) and port. The provider
starts with `osw_defer_game_endpoint` and requires the server's `game.endpoint.v1`
capability. NAT responses and room/peer advertisement remain blocked until
`game.endpoint.bind` receives the server's correlated acknowledgement. A closed or
changed socket of the still-running game fails closed. Socket discovery has no
menu-idle timeout. `--directory-check` instead reserves a diagnostic loopback UDP
socket for its own lifetime; it never claims game acceptance.

The POSIX native launcher detaches the game into its own session, beyond the
POSIX process-group teardown, so the native adapter refuses to launch there until
that is solved. Configuration, provider, server and HTTP code and the portable
diagnostics stay platform-neutral.

Upstream forwards HTTP and HTTPS as plain HTTP to this loopback front. Exact
`<group>.np.community.playstation.net` hosts, including the pinned native host's
`sdk:` authority prefix, dispatch OSW_WEBAPI with method, path,
group, headers, content type and opaque binary body. Other hosts go only to the
local server; the Host/scheme/end-to-end headers are preserved.
There is no external DNS/proxy destination or redirect following. Hop-by-hop
headers and framing are rebuilt. Duplicate/ambiguous framing is rejected.
Unsupported provider routes retain explicit HTTP errors.

Limits: 32 KiB headers, 100 header fields, 1 MiB body, 8 concurrent handlers and 16
queued connections. Socket operations have a 30-second total deadline; provider
requests have a 25-second deadline. These per-request limits do not expire sessions.
Bridge logs contain status/categories only, never bodies or tokens. The Windows
desktop entry point appends its lifecycle messages to `ctrnf-p2p/bridge.log`.
Native
upstream itself logs short body prefixes: keep the port's logs and
`ctrnf-p2p/host.log` private. Server logs are also private. Do not paste raw
runtime logs into public issues.

Steam overlay injection into the separate game window and native push invitation
delivery are outside this implementation. Two-PC live Steam qualification needs
separate accounts and machines; see the integration procedures in `docs/`.
