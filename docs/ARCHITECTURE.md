# Architecture and runtime contracts

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
keeps each account's progression under its SteamID, with separate progression records for each account, and
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

For Steam sessions the bridge also sets `SteamAppId` and `SteamGameId` to the
configured `steam.app_id` for the launcher and its descendants. Steam initializes
in the bridge, while its overlay attaches to the separate native renderer; both
processes need the same application association. Inherited app/shortcut IDs are
still discarded, and simulated Lab sessions receive neither variable. This does
not inject an overlay DLL or call Steam from the native host. The overlay can
attach to both the native launcher and the game.

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
