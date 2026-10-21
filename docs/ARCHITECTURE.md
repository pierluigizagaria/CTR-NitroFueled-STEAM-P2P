# Architecture

The bridge supervises three independent components: the native port's launcher
and game, the orbiSteamworks provider (loaded through its public C API) and the
Demonware Server, which the provider starts as its local companion. The bridge
contains no Steam calls and no CTR or Demonware protocol parsing.

## Identity

The SteamID and the displayed name always come from the connected Steam
account; no setting overrides them. The name is mapped to ASCII: printable
0x20–0x7e is kept, non-ASCII characters and control bytes become `_`, spaces
are trimmed and the result is limited to 16 bytes. An all-blank persona stops
startup. The same name goes to the provider, `BB_ONLINE_ID` and `BB_USER_NAME`.

The native port then rewrites its NP ID to `[A-Za-z0-9_-]` and pads names
shorter than 3 characters, while its UserService keeps `BB_USER_NAME`. The bridge
does not change this behavior. AppID identifies the application, SteamID the
account; the online ID is only the displayed name.

The identity is read once per session. If another Steam account signs in behind
the same client, the provider fails the context and the bridge ends the session;
relaunch to play as that account.

## Local admission

The SteamID64 is passed to the port as decimal `BB_ONLINE_ACCOUNT_ID`. The
legacy `host = native` port fabricates its own `sacredfire` token, so the bridge starts the
local server with its native-token admission (`CTR_LOCAL_WEAK_TOKEN=1`). That
mode only checks that the token names the account that owns the provider's pipe
and that the request comes from loopback. **Any local process able to produce
that token format can attempt admission.** This is weaker than the provider's
random pipe capability, and the name is never the authentication key. It must
never be used for a central or public server; the server's own default leaves
the mode disabled.

The integrated `psn` and `octr` hosts use the provider's random companion
capability instead. Their PSN backend receives it through a private local
relay; neither enables fabricated-token admission. See [PSN integrations](OCTR.md).

The native adapter fixes the rest of the server contract: Demonware title `5760`
(the PS4 title CUSA13795 is a different identifier), build `01.21`, the game's
UDP source as observed at `127.0.0.1`, and the server's auth listener on port
`8460` of `network.address`.

## Persistence

The server's database (`demonware-server/data/ctrnf.db`) keeps each account's
progression under its SteamID and is shared by both economy modes. Unlock-all
makes the catalog available without recording it as owned, while races,
challenges and statistics count in both modes; returning to normal shows real
purchases, coins and progress again.

The native save belongs to the port and is shared by every account and both
modes. The bridge never selects, copies, resets or edits saves; use the port's
own save-folder settings to separate them. Peers exchange only room messages
and race traffic; progression and server files stay local.

## Launch environment

The launcher inherits the bridge's environment, except bridge, provider, server
and online settings (`OSW_*`, `CTR_*`, `NEXTENDO_*`, `SHADNET_*`, `D3_*`,
`DASH_*`, `BB_ONLINE_*`, `BB_USER_NAME`, `STEAMAPPID`, `STEAMGAMEID`; compared
case-insensitively on Windows). Other native `BB_*` values pass through
unchanged. The bridge then sets only `BB_ONLINE_SERVER`, `BB_ONLINE_HTTP_PORT`,
`BB_ONLINE_ID`, `BB_USER_NAME`, `BB_ONLINE_ACCOUNT_ID` and
`BB_ONLINE_ALLOW=127.0.0.1`. The port's launch script lets these values win over
`bbport.ini`; the explicit loopback allow list keeps `bbport.ini` `online_allow`
from widening the game's reachable addresses. The native launcher may still show
its own online fields.

The bridge also sets `SteamAppId` and `SteamGameId` to the configured
`steam.app_id` for the launcher and its descendants. Steam initializes in the
bridge, while its overlay attaches to the separate native renderer; both
processes need the same application association. The bridge does not inject an
overlay DLL or call Steam from the native host.

## Signature patch activation

Before a normal launch the bridge reads the patch selection that the native
launch script will use: `BB_PATCHES_CONFIG`, else `patches.json` in
`BB_DATA_DIR` (else the port root), and `BB_PATCHES_DIR`, else `patches/`.
Relative values resolve from the port root, as the script does.

The XML is parsed as a complete document with the bundled Expat parser;
comments and CDATA cannot supply patch elements, and malformed documents and
DTDs are refused. The selected patch must name CUSA13795, AppVer 01.21,
`eboot.bin` and the supported write. The bridge then adds the patch key to
`enabled` and removes it from `disabled`, keeping all other fields and
selections; it writes nothing when the patch is already enabled. Invalid input
fails without replacing the file. `--check` only validates. The launcher can
change the selection afterwards, and other selected patches are not inspected
for conflicts.

## Session ownership

On Windows the launcher and all its descendants run in a kill-on-close Job
Object. The bridge discovers the IPv4 UDP socket owned by exactly one process of
that job and accepts one port bound to the wildcard address or `127.0.0.1`;
several owning processes or ports fail closed, and an unrelated process cannot
supply it. The session is pinned to that process (ID and start time) and port.

The provider starts with `osw_defer_game_endpoint` and requires the server's
`game.endpoint.v1` capability. NAT responses and room or peer advertisement stay
blocked until `game.endpoint.bind` receives the server's correlated
acknowledgement. A closed or changed socket of the still-running game ends the
session. `--directory-check` uses a diagnostic loopback UDP socket of its own
instead of a game.

The session ends when the game or launcher exits, the bridge stops, the
provider or server fails, or the Steam account changes.

## HTTP front

The port forwards HTTP and HTTPS as plain HTTP to the bridge's loopback front.
Exact `<group>.np.community.playstation.net` hosts, including the native host's
`sdk:` authority prefix, go to the provider's WebAPI operation with method,
path, group, headers, content type and opaque binary body. Other hosts go only
to the local server, with the Host, scheme and end-to-end headers preserved.
There is no external DNS or proxy destination and no redirect following.
Hop-by-hop headers and framing are rebuilt; duplicate or ambiguous framing is
rejected. Unsupported provider routes return explicit HTTP errors.

Limits: 32 KiB headers, 100 header fields, 1 MiB body, 8 concurrent handlers and
16 queued connections. Socket operations have a 30-second total deadline;
provider requests have a 25-second deadline. These are per-request limits.

## Logs

Bridge logs contain status and categories only, never bodies or tokens. The
desktop entry point appends its lifecycle messages to `ctrnf-p2p/bridge.log`.
The port itself logs short body prefixes, so keep the port's logs,
`ctrnf-p2p/host.log` and the server logs private.

## Platforms

Configuration, provider, server and HTTP code are platform-neutral. The POSIX
native launcher detaches the game into its own session, beyond the bridge's
process-group teardown, so the native adapter refuses to launch on POSIX.

Steam overlay injection into the game window and in-game invitation delivery
are not implemented.
