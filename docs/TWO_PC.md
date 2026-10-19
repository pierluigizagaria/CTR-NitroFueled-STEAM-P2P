# Two-PC Steam qualification procedure

This is an execution procedure, not a record of a passed two-PC test. Each PC
needs its own Steam account, its own legally owned game files, and a separately
source-built compatible native host/provider/local server. No SDK or game files are
distributed by this project. Current qualification status belongs to VALIDATION.md.

## Prepare independently on each PC

1. Install the native port as usual and start the game once from its own launcher,
   so its game folder, preparation and settings exist. Add the CTR:NF Server
   Signature Patch XML to the port's `patches/` folder and enable it in the port's
   `patches.json`. The local server sends unsigned replies; no key or OpenSSL is used.
2. Build/install ctrnf-p2p, a provider supporting loopback-v1 and account-change
   failure, and the compatible local server into the port root (the [installation guide](INSTALLATION.md)).
   Retain their commits and SHA-256 hashes in a private record. Supply the correct
   Steam API runtime beside the bridge executable.
3. Copy the example configuration. Both PCs must use the same `steam.app_id` and
   `session.realm` (title and build are fixed by the native adapter). Use 480 for
   the first test. Accounts must be licensed for the selected AppID. `lab.*` stays
   unset.
4. Choose normal or unlock-all independently with `server.unlock_all`. This does not
   change the room namespace, the saves or the server database.
5. Confirm Steam is running and the intended accounts are friends. Never put
   credentials in bridge configuration. On Windows run `ctrnf-p2p-cli --check`
   and then `ctrnf-p2p-cli --probe`.
   Probe success confirms initialization only; it does not establish peer traffic.
6. Double-click `ctrnf-p2p.exe` on each Windows PC (no console window) and start
   the game from the native launcher it opens. Lifecycle logs are in
   `ctrnf-p2p/bridge.log`; errors appear in a dialog.
   It starts only loopback server/HTTP listeners; do not forward router ports or
   expose these listeners publicly. Do not disable system security to work around a
   failure.

## Record observable acceptance

Record commit/hash, OS, selected AppID, economy mode, and pseudonymous player A/B.
Keep raw host/provider logs private because the upstream host logs body prefixes.
Use screenshots or sanitized event/category records for shared evidence.

1. On each game, confirm the local name, enter Online and visit Pit Stop. Verify
   local progression appropriate to each configured economy. Record the native
   NP-name versus local UserService-name behavior for punctuation/short names.
2. Confirm the other player appears among current in-game friends. Enter a
   private room via the game's friend Join action. Check both screens show the
   same group. Native push invitation delivery and Steam overlay injection are
   outside this bridge; do not make them prerequisites or report them as passed.
3. Enter public matchmaking separately, then as a group if the game permits it.
   Confirm a shared lobby on both PCs and a synchronized race start.
4. Complete a race through results on both clients. Record bidirectional provider
   race counters/errors if supported by the public diagnostic interface, and the
   original-game result on each PC. Two machines plus provider evidence matters:
   same-PC loopback exchange is not proof of Steam transport.
5. Leave, re-enter and join again; terminate one bridge and verify its launcher,
   game and local server exit. Use the native "Apply and restart" once and verify the
   bridge session ends with no surviving launcher, game or server process. The surviving player should receive the game's
   ordinary departure/failure behavior. A failure is evidence, not a reason to
   fabricate a pass or relax original identity/MAC checks.

## Failures

Missing DLL/export, signed-out provider, incompatible namespace/transport mode,
server capability refusal, missing or unselected signature patch, a Steam account
change, occupied canonical endpoint and OS-reserved port
are explicit failure cases. The provider never changes a canonical endpoint or
silently falls back. Preserve the error category and hashes. Do not edit CTR
packets, bypass identity checks, or modify native source to make this gate pass.

The pinned native host does not deliver presence push callbacks. A game that
read its friend list before the other player started can keep that initial
snapshot, even while the provider's current list is correct. If reopening
Online does not cause a new list request, restart that player's bridge while
the other player's bridge remains running. In the Lab retest this forced a
fresh nonempty friend response; it does not implement live presence updates.
Restarting exits the current lobby and retains the native saves and server database.

Historical overlay experiments and their process-local settings are recorded in
[the validation history](VALIDATION.md); they are not installation steps. The
current bridge passes the configured Steam AppID to the launcher and game.

Two loopback-v1 players on one PC are at most a Lab carrier possibility: a third
can require duplicate canonical binds. The unchanged native host has no
per-instance source-bind/port setting. The game chooses another port when3074
is occupied; observed second-instance ports have differed across launches.
The bridge reads the socket of the one supervised game process and registers
that source through the public provider API. No manual port setting is accepted.
NAT and room/peer operations remain gated until the local server acknowledges it.
This discovery never alters the game's bind or its canonical endpoint. Same-PC
proxy traffic, Join and races remain separate acceptance checks.
