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
- Steam running and signed in with your account.
- `steam_api64.dll`, which you supply yourself. It is in the
  [Steamworks SDK](https://partner.steamgames.com/doc/sdk) under
  `redistributable_bin/win64/`.

The mod ZIP already contains the
[CTR:NF Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch);
the bridge enables it automatically.

## Install

Download the Windows mod ZIP from [Releases](https://github.com/pierluigizagaria/ctrnf-p2p/releases).

1. Set up the native port and its game files using the port's instructions.
2. Close the port, then extract the mod ZIP into the port's root folder (the
   folder containing `CTR-NitroFueled-PC.exe`). The ZIP replaces none of the
   port's settings or saves.
3. Copy `steam_api64.dll` into that folder.
4. For a new installation, copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini`.
5. Double-click `ctrnf-p2p.exe`. On first start it enables the signature patch
   in the port's patch selection and leaves all other settings unchanged.

The [installation guide](docs/INSTALLATION.md) shows the resulting folder layout
and covers updating, uninstalling and troubleshooting.

## Run

Double-click **`ctrnf-p2p.exe`**, then start the game from the native launcher.
No terminal window opens. Messages go to `ctrnf-p2p/bridge.log`; startup errors
appear in a dialog.

Closing the launcher or the game ends the online session. After the game's
**Apply and restart** action, start `ctrnf-p2p.exe` again. Switching Steam
accounts also ends the session.

## Playing together

Each player installs the mod with their own Steam account and game files, using
the same mod version and settings. Steam shows you as playing **Spacewar**: the
mod uses Steam's public test AppID 480, so nobody needs to own another Steam game.

Add each other as Steam friends, start the game through the mod, enter Online
and use the game's friend Join or matchmaking.

Pit Stop items, coins and statistics are stored on each player's own PC; they
are not shared between players. A room ends when the player who created it leaves.

## Configuration

`ctrnf-p2p.ini` needs no changes for normal play:

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

Set `unlock_all = true` to make the whole Pit Stop catalog available without
spending coins. Nothing is recorded as purchased: switching back to `false`
shows your real purchases and coins again. Races, challenges and statistics count
in both modes, and players using either mode can race together.

Server progression is kept per Steam account in
`demonware-server/data/ctrnf.db`. The game's own save is managed by the port and
is shared by every account; use the port's save-folder settings to keep saves apart.

See [configuration](docs/CONFIGURATION.md) for advanced settings.

## Build

Requires CMake 3.20+, C/C++20 compilers, the public orbiSteamworks header and
nlohmann/json headers. No Steamworks SDK is required.

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DOSW_INCLUDE_DIR=/path/to/include -DJSON_INCLUDE_DIR=/path/to/json/include
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

[Build instructions](docs/BUILDING.md) cover dependencies, tests and platform
support. [Architecture](docs/ARCHITECTURE.md) describes identity, the native
adapter and the local server's admission. Maintainers can follow
[Releasing](docs/RELEASING.md) to assemble the mod ZIP.

## Compatibility and limitations

- Only the native port at the revision above is supported, with Steam as the
  platform provider.
- Windows only. Linux and macOS are not supported.
- Invitations are not delivered to the game; use friend Join or matchmaking.
  The in-game friend list may need a refresh, or a restart, before a newly
  started friend appears.
- Rooms do not move to another player when their creator leaves.
- Internet play between different networks is experimental and not guaranteed
  to work.
- The local server only accepts connections from the same PC and must not be
  exposed as a public server.

## License

The bridge is [MIT licensed](LICENSE). The bundled Expat parser retains its
[own license](third_party/expat/upstream/COPYING).
orbiSteamworks is MIT licensed; Demonware Server uses PolyForm Shield 1.0.0.
Each component remains a separate project with its own source and license.
No game, firmware or Steamworks files are included.
