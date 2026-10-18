# Two-PC Steam qualification procedure

This is an execution procedure, not a record of a passed two-PC test. Each PC
needs its own Steam account, its own legally owned game files, and a separately
source-built compatible native host/provider/publisher. No SDK or game files are
distributed by this project. Current qualification status belongs to VALIDATION.md.

## Prepare independently on each PC

1. Build the pinned upstream native host and prepare its supported owned game
   using upstream scripts. Keep the signature patch and publisher response key
   matched. Use a dedicated existing save root for the chosen economy, or the
   bridge defaults. Never share databases across machines or economy modes.
2. Build/install ctrnf-p2p, a provider supporting loopback-v1, and the compatible
   local publisher. Retain their commits and SHA-256 hashes in a private record.
   Supply the correct Steam API runtime beside the bridge executable.
3. Copy the example configuration. Both PCs must use the same steam.app_id,
   session.title, session.build and session.realm. Use480 for the first test.
   Accounts must be licensed for the selected AppID. Local filesystem paths and
   listener addresses can differ. `lab.enabled` remains false, with no Lab ID/root.
4. Choose normal or unlock-all independently. This does not change the room
   namespace. A useful test uses one of each, with separate saves/databases.
5. Confirm Steam is running and the intended accounts are friends. Never put
   credentials in bridge configuration. Run `ctrnf-p2p --check` and then `--probe`.
   Probe success confirms initialization only; it does not establish peer traffic.
6. Launch ctrnf-p2p on each PC. It starts only loopback publisher/HTTP listeners;
   do not forward router ports or expose these listeners publicly. Do not disable
   system security to work around a failure.

## Record observable acceptance

Record commit/hash, OS, selected AppID, economy mode, and pseudonymous player A/B.
Keep raw host/provider logs private because the upstream host logs body prefixes.
Use screenshots or sanitized event/category records for shared evidence.

1. On each game, confirm the local name, enter Online and visit Pit Stop. Verify
   distinct local progression appropriate to each configured economy. Record the
   native NP-name versus local UserService-name behavior for punctuation/short names.
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
5. Leave, re-enter and join again; terminate one bridge and verify its owned game
   and local publisher exit. The surviving player should receive the game's
   ordinary departure/failure behavior. A failure is evidence, not a reason to
   fabricate a pass or relax original identity/MAC checks.

## Failures

Missing DLL/export, signed-out provider, incompatible namespace/transport mode,
publisher capability refusal, occupied canonical endpoint and OS-reserved port
are explicit failure cases. The provider never changes a canonical endpoint or
silently falls back. Preserve the error category and hashes. Do not edit CTR
packets, bypass identity checks, or modify native source to make this gate pass.

Two loopback-v1 players on one PC are at most a Lab carrier possibility: a third
can require duplicate canonical binds. The unchanged native host additionally
has no per-instance source-bind/port setting. Its same-PC feasibility must be
measured separately; the library's two-process fixture does not prove two games
can bind and receive correctly.
