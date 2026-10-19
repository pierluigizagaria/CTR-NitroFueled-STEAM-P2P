# ctrnf-p2p

A local process that connects an unchanged native host to a platform provider
through the public orbiSteamworks C API. It owns configuration, HTTP adaptation
and process lifetime. Steam, endpoint allocation, peer authorization and opaque
transport belong to the provider. Demonware, CTR matchmaking and local progression
belong to the separate publisher. No source from either host or publisher is
incorporated here. License: MIT.

The first host adapter targets GetLostIn `online` at
`b1b4bf9647132822147e76aeec47390c6cb157bf`. It does not require a host source change.
The provider must support `loopback-v1`, configurable AppID and raw persona lookup.
An older or incomplete provider is refused before starting the game. There is no
fallback to another provider. A future shadNet provider can implement the same C
API; a future shadPS4 host protocol adapter is a separate concern.

## Build

C++20 and CMake 3.20 or newer. Dependencies are the provider's public C header
(`orbisteamworks/osw.h`) and nlohmann/json headers. Neither dependency needs a
sibling source checkout: pass their installed include directories explicitly.
No provider code is linked into the bridge. No Steamworks SDK is needed to build.

```text
cmake -S . -B build -DOSW_INCLUDE_DIR=/path/to/public-sdk/include -DJSON_INCLUDE_DIR=/path/to/json/include
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Tests default on and use Python 3, a fake provider DLL/shared library and a fake
HTTP/UDP host written for these tests. They need no Steam account, game, publisher
binary or sibling runtime state. Set `-DBUILD_TESTING=OFF` for a build without
Python/tests. Real-provider/publisher and original-game acceptance are separate
optional integration work, never implied by these fixtures.

Windows is the tested execution platform. Shared code uses standard C++20;
platform.cpp isolates library loading and child supervision, and http.cpp isolates
Winsock/POSIX sockets. The POSIX implementation uses a guardian process and an EOF
pipe for child lifetime, including on macOS where Linux parent-death signals are
unavailable. **macOS and Linux builds/runtime are not yet qualified.** The provider
and native game must independently support the target OS; bridge portability does
not establish their compatibility.

## Run

Place the user-supplied Steam API library beside the bridge executable; nothing
from Steamworks is included or distributed. Place the provider DLL there too, or
configure an explicit provider library path. Install the independently built
publisher and supply its response-signing key and the supported game server-signature patch.
The retained CTR patch permits responses signed by a different server key; it
does not embed a profile-specific public key. It leaves account admission and
lobby message authentication unchanged.
The publisher requires OpenSSL on its process PATH for response signing; use its
own installation or configure publisher.runtime_dir with an existing tool folder.
Do not put private keys/configuration in version control.

Copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini` beside the executable and fill in
paths. All relative paths resolve beside the executable, even with `--config`.
`--config path` itself resolves from the current working directory.

```text
ctrnf-p2p --check
ctrnf-p2p --probe
ctrnf-p2p --directory-check
ctrnf-p2p
```

`--check` validates configuration/files without starting anything. `--probe`
starts the provider, hidden publisher and HTTP listener, verifies readiness and
then stops them; it does not start a game or qualify game/peer transport.
`--directory-check` additionally creates a temporary room, reads it, requires
that exact room in search and leaves it. This can qualify one-account directory
operations without launching a game; it cannot qualify Steam peer transport.
Ordinary launch supervises the game until it exits. Windows uses a kill-on-close Job
Object for the host and its descendants; the provider owns its own publisher.
Host exit, bridge teardown or provider/publisher failure tears the session down.
There is no menu-idle or elapsed-session cutoff. An in-game restart request exits
the bridge; relaunch it after preparing any changed native settings.

## Configuration

Unknown/duplicate sections or settings and invalid values stop startup. Boolean
values are exactly `true` or `false`. Integers are decimal. Full-line `;`/`#`
comments are accepted. Unquoted inline comments start after whitespace; to retain
such punctuation in names, use a JSON quoted string, for example `"A ; B"`.
Paths and environment values passed to this native host must be printable ASCII.

| Setting | Default and meaning |
| --- | --- |
| platform.provider | `steam`; other providers are currently unsupported |
| platform.library | `orbisteamworks.dll` on Windows, `liborbisteamworks.dylib` on macOS, `liborbisteamworks.so` on other POSIX targets |
| steam.app_id | `480`; nonzero uint32. Every peer must use the same licensed AppID |
| steam.library | `steam_api64.dll` on Windows, `libsteam_api.dylib` on macOS, `libsteam_api.so` otherwise; must be beside the bridge executable |
| player.online_id | Empty: obtain the raw Steam persona via public API, map to ASCII, then create the final context with that explicit name. An explicit override uses the same mapping |
| player.unlock_all | `false`; boolean publisher economy choice, excluded from matchmaking namespace |
| game.host | `native`; other host adapters are currently unsupported |
| game.profile | `ctr`; upstream rendering profile name, separate from save directories |
| game.executable | Required raw native executable, built from the pinned source |
| game.game_dir | Required owned merged game directory with eboot.bin |
| game.prepared_dir | Required output of upstream preparation: boot-linked.bin, import_names.txt, content.bin, patches.bin |
| game.patches_dir | Required source patch directory, passed as BB_PATCHES_DIR; prepared patches.bin must already contain the supported server-signature patch |
| game.profile_dir | `runtime/player`; base for separate normal/unlock-all state |
| game.runtime_dir | Empty; optional native runtime dependency directory prepended to the child's PATH |
| game.config | Empty: `<profile>/<economy>/bbport.ini`; optional existing native settings file. It must match prepared rendering patches |
| game.normal_saves | Empty: `<profile>/normal/user`; optional existing normal save root |
| game.unlock_all_saves | Empty: `<profile>/unlock-all/user`; optional existing unlock-all save root. Effective save roots must not overlap |
| publisher.executable | Required independent publisher executable |
| publisher.signing_key | Required private publisher response-signing key; kept local to that publisher |
| publisher.runtime_dir | Empty; optional existing dependency directory (for example OpenSSL) prepended to the publisher process PATH |
| publisher.weak_admission | `false`; native upstream requires explicitly setting `true`. Maps to CTR_LOCAL_WEAK_TOKEN=1 |
| session.title | `5760`, the publisher's Demonware title ID; at most16 bytes. The PS4 asset title CUSA13795 is a different identifier |
| session.build | `01.21`; at most64 bytes, same for all peers |
| session.realm | `ctrnf-p2p`; at most64 bytes, same for all peers; never encode economy here |
| network.server | `127.0.0.2`; bridge/publisher listener address in127.0.0.2–254, separate from the game |
| network.http_port | `31380`; native HTTP front, must not collide with publisher listeners |
| network.auth_port | `8460`; publisher's plain HTTP auth listener |
| network.game_address | `127.0.0.1`; measured Windows source of the unchanged wildcard game socket |
| lab.enabled | `false`; explicitly simulated local backend for fixtures/Lab only, never a Steam fallback |
| lab.account_id | `0`; nonzero synthetic ID required when Lab is enabled |
| lab.root | Empty; shared private Lab hub directory required when Lab is enabled |

Lab also requires an explicit player.online_id. With Lab disabled, account_id/root
must remain empty/default. Lab results are not Steam transport acceptance.

The bridge discovers the IPv4 UDP socket of the exact native child it owns.
It accepts only one distinct port bound to wildcard or `127.0.0.1`; an unrelated
process cannot supply it. There is no configured game source port. The provider
starts with `osw_defer_game_endpoint` and requires the publisher's
`game.endpoint.v1` capability. NAT responses and room/peer advertisement remain
blocked until `game.endpoint.bind` receives the publisher's correlated
acknowledgement. A closed, changed or ambiguous source fails closed. Socket discovery
has no menu-idle timeout. `--directory-check` instead reserves a diagnostic
loopback UDP socket for its own lifetime; it never claims game acceptance.

## Identity, persistence and security boundary

The ASCII mapping retains printable0x20–0x7e, replaces non-ASCII Unicode characters
with `_`, trims spaces and limits to16 bytes. Control bytes become `_`; an empty
result requires an override. The identical explicit name goes to the provider,
BB_ONLINE_ID and BB_USER_NAME. Native upstream then separately rewrites its NP ID
to `[A-Za-z0-9_-]` and pads names shorter than3 characters; UserService retains
BB_USER_NAME. This difference is documented rather than patched. Explicit names
do not follow live renames; relaunch to recompute the Steam persona.

The SteamID64 is passed as decimal BB_ONLINE_ACCOUNT_ID. Native upstream fabricates
its sacredfire token; weak admission only checks that its account is the current
pipe owner and the actual request source is loopback. **Any local process able to
impersonate that owner format can attempt admission.** This is weaker than the
provider's random pipe capability and is off by default. Name text is not the
authentication key. This option must never be exposed as central/public admission.

Normal/unlock-all databases reside in `<profile>/<economy>/publisher/data/ctrnf.db`.
Their save directories remain separate even when the players share rooms. Each
publisher exposes only the documented room/opaque race contracts to peers;
progression and publisher files stay local. Existing save overrides are used in
place; the bridge does not copy, reset or delete them.

## Native adapter and HTTP front

Prepare the owned game with the pinned upstream scripts; the bridge does not
reimplement the native loader/linker or download game assets. Launch arguments
provide --app0, --user and the prepared artifacts. **--timeout0 is always passed**
because the raw upstream executable otherwise defaults to ten seconds.
BB_GPU_USER_DIR and --user agree. BB_GAME_PROFILE selects `ctr`, not a save root.
The adapter uses the documented Windows run.py defaults (base resolution, PS4
mode, GPU buffer-copy settings). Changed rendering/60FPS settings require upstream
preparation with matching patches. Old BB_*/OSW_*/publisher settings are removed
from the child environment before the selected mapping is installed.

Upstream forwards HTTP and HTTPS as plain HTTP to this loopback front. Exact
`<group>.np.community.playstation.net` hosts, including the pinned native host's
`sdk:` authority prefix, dispatch OSW_WEBAPI with method, path,
group, headers, content type and opaque binary body. Other hosts go only to the
configured loopback publisher; the Host/scheme/end-to-end headers are preserved.
There is no external DNS/proxy destination or redirect following. Hop-by-hop
headers and framing are rebuilt. Duplicate/ambiguous framing is rejected.
Unsupported provider routes retain explicit HTTP errors.

Limits:32KiB headers,100 header fields,1MiB body,8 concurrent handlers and16 queued
connections. Socket operations have a30-second total deadline; provider requests
have a25-second deadline. These per-request limits do not expire sessions.
Bridge logs contain status/categories only, never bodies or tokens. Native
upstream itself logs short body prefixes: keep `<state>/host.log` private. Publisher
logs are also private. Do not paste raw runtime logs into public issues.

Steam overlay injection into the separate game window and native push invitation
delivery are outside this implementation. Two-PC live Steam qualification needs
separate accounts and machines; see the integration procedures in `docs/`.
