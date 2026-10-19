# Project instructions

Independent MIT bridge. Code, comments and documentation are English.
Use portable C++20/CMake; isolate Windows and POSIX code for future macOS use.
Consume the provider's documented public `osw.h` only; never compile sibling
sources or copy host/shadNet/publisher implementations. Steam symbols, endpoint
allocation, peer authorization and CTR/Demonware parsing are outside this project.
Protocol adapters are written from scratch. Native host source remains unchanged.
An ordinary bridge launch may enable only the required signature patch in the
native patch-selection file after validating its XML. Preserve other settings
and selections; diagnostic modes remain read-only. Do not alter native saves,
game preparation or preferences as part of patch activation.
Keep all build output, private configuration and test evidence ignored. Do not
commit Steamworks files, game assets, tokens, IDs or signing keys. Never log bodies
or credentials. Each request is bounded; sessions have no idle cutoff.
Review staged paths before local commits. Keep distribution packages separate
from source history; include component licenses and no user runtime state.
Publication requires an explicit user request. The 2026-10-19 distribution
request authorizes publishing this project and its experimental Windows mod
package, with the independent provider/server binaries and signature patch.
It does not authorize Steamworks or game-file distribution.
Tests use fake providers/hosts by default; actual provider/publisher/game checks
are optional, take explicit artifact paths and remain separate evidence.
