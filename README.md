# ctrnf-p2p

A Windows multiplayer mod for the native **Crash Team Racing Nitro-Fueled** port.
It connects the port to Steam identity, friends and peer transport through
[orbiSteamworks](https://github.com/pierluigizagaria/orbisteamworks), with a local
[Demonware Server](https://github.com/pierluigizagaria/demonware-server) for
matchmaking, Pit Stop and progression.

The mod starts the port's own launcher. Game settings, preparation and saves stay
with the port. No native source changes are required.

**Experimental.** See [compatibility and limitations](#compatibility-and-limitations)
before installing.

## Requirements

- Windows x64 and the [GetLostIn native port](https://github.com/GetLostIn/CTR-NitroFueled-PC/tree/b1b4bf9647132822147e76aeec47390c6cb157bf)
  at `online` revision `b1b4bf9`.
- Your own supported PS4 game files: CUSA13795, update 01.21.
- Steam running with the intended account.
- A user-supplied `steam_api64.dll` beside the bridge executable.
- The included [CTR:NF Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch),
  enabled automatically when the bridge starts.

## Install

Download the Windows mod ZIP from [Releases](https://github.com/pierluigizagaria/ctrnf-p2p/releases).
It includes the bridge, provider, local server, patch XML and separate license
notices. See the [package instructions](docs/PACKAGE_README.md).

1. Set up the native port and its game files using the port's instructions.
2. Extract the mod ZIP into the port's root folder, preserving your existing
   configuration and saves.
3. Add your `steam_api64.dll` to that folder.
4. Copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini` for a new installation.
5. Double-click `ctrnf-p2p.exe`. It validates the included patch XML and enables
   that patch in the native configuration, preserving all other settings.

The [installation guide](docs/INSTALLATION.md) includes the directory layout,
patch activation and troubleshooting. The native port, game files and Steamworks
runtime are separate prerequisites, not part of this project's distribution.

## Run

Double-click **`ctrnf-p2p.exe`**, then start the game from the native launcher.
No terminal window is opened. Lifecycle messages go to `ctrnf-p2p/bridge.log`;
startup errors appear in a dialog.

Closing the launcher or game ends the online session. After the native
**Apply and restart** action, relaunch the bridge. Switching Steam accounts also
ends the session.

## Playing together

Each player installs the mod with their own Steam account and game files.
Use matching component versions, AppID and session realm. Add each other as
Steam friends, enter Online and use the game's friend Join or matchmaking.

The local server keeps progression on each player's PC; it does not provide a
shared online economy. The room ends when its owner leaves.

## Configuration

The example contains only the four basic settings:

```ini
[platform]
provider = steam

[steam]
app_id = 480

[game]
host = native

[server]
unlock_all = false
```

All players need the same AppID, title/build and realm. Normal and unlock-all
players can play together. Both modes share the native saves and the server's
database; server progression is keyed by Steam account. Native saves are shared
unless you separate them using the port's own settings.

See [configuration](docs/CONFIGURATION.md) for advanced settings and
[architecture](docs/ARCHITECTURE.md) for identity, persistence and local admission.

## Build

Requires CMake 3.20+, C/C++20 compilers, the public orbiSteamworks header and
nlohmann/json headers. No Steamworks SDK or sibling source checkout is required.

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DOSW_INCLUDE_DIR=/path/to/include -DJSON_INCLUDE_DIR=/path/to/json/include
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

[Build instructions](docs/BUILDING.md) cover dependencies, tests and platform
support. The provider is loaded at runtime; its implementation is not linked
into the bridge.

## Compatibility and limitations

- Only the pinned native host adapter and Steam provider are implemented.
- Native game launch is Windows-only. Linux and macOS are not qualified.
- The native host does not deliver live presence or invitation push callbacks.
  Its friend list can require a refresh or restart after another player joins.
- The local server is loopback-only. Its native-token admission is not suitable
  for a public server.
- Internet multiplayer remains experimental; compatibility across different
  networks is not guaranteed.

Maintainers can [assemble a release](docs/RELEASING.md) from explicit component
artifacts without sharing their source trees or private runtime state.

## License

The bridge is [MIT licensed](LICENSE). The bundled Expat parser retains its
[own license](third_party/expat/upstream/COPYING).
orbiSteamworks is MIT licensed; Demonware Server uses PolyForm Shield 1.0.0.
Each component remains a separate project with its own source and license.
No game, firmware or Steamworks files are included.
