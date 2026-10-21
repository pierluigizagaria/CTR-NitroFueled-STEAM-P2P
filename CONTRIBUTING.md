# Contributing

Keep changes focused on the bridge. Describe the observable behavior, the
interface it changes and how it was checked.

## Component boundaries

- Use portable C++20 and CMake. Keep Windows and POSIX code isolated in
  `platform.cpp` and `http.cpp`.
- Consume only the provider's public `orbisteamworks/osw.h`. Do not compile
  provider, server or host sources, or copy their implementations. Protocol
  adapters in this repository are written from scratch.
- Steam calls, endpoint allocation, peer authorization and CTR/Demonware parsing
  belong to the provider and the server, not the bridge.
- Host source integration belongs to the separate GPL host branches. A normal
  bridge launch may only enable the
  required signature patch in the port's patch selection, after validating its
  XML; other settings, saves, game preparation and preferences are never changed.
  Diagnostic modes are read-only.
- Bound individual requests, but do not add idle or elapsed-time limits to
  sessions.

## Tests

Use the commands in [Building](docs/BUILDING.md). Ordinary tests use the fake
provider and host and must keep working without Steam, the game or the server.
Checks against real components are optional, take explicit artifact paths and
are reported separately from the automated tests.

## Repository contents

Write documentation in English. Keep build output, private configuration and
test output out of the repository. Never commit Steamworks files, game assets,
tokens, account IDs or signing keys, and never log request bodies or credentials.
Release packages are assembled separately ([Releasing](docs/RELEASING.md)), with
each component's license notices and no user runtime state.
