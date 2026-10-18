# Project instructions

Independent MIT bridge. Code, comments and documentation are English.
Use portable C++20/CMake; isolate Windows and POSIX code for future macOS use.
Consume the provider's documented public `osw.h` only; never compile sibling
sources or copy host/shadNet/publisher implementations. Steam symbols, endpoint
allocation, peer authorization and CTR/Demonware parsing are outside this project.
Protocol adapters are written from scratch. Native host source remains unchanged.
Keep all build output, private configuration and test evidence ignored. Do not
commit Steamworks files, game assets, tokens, IDs or signing keys. Never log bodies
or credentials. Each request is bounded; sessions have no idle cutoff.
No publication or push. Local commits are authorized after staged-path review.
Tests use fake providers/hosts by default; actual provider/publisher/game checks
are optional, take explicit artifact paths and remain separate evidence.
