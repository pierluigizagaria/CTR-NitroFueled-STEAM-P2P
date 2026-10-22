# CTR-NitroFueled-STEAM-P2P

<a href="https://buymeacoffee.com/pierluigizagaria"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="217" height="60"></a>

Complete Windows builds of **Crash Team Racing Nitro-Fueled** PC ports
with a Steam/P2P adapter and matching mod. This project rebuilds stable releases
from [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC) and
[Ryu7w7/OCTR-NitroFueled-PC](https://github.com/Ryu7w7/OCTR-NitroFueled-PC), preserving their credits,
licenses and corresponding sources.

The mod connects the port to Steam identity, friends and peer transport through
[orbiSteamworks](https://github.com/pierluigizagaria/orbisteamworks), with a local
[Demonware Server](https://github.com/pierluigizagaria/demonware-server) for
matchmaking, Pit Stop and progression.

The mod starts the port's own launcher. Game settings, preparation and saves stay
with the port. The executable, configuration and package filenames retain
`ctrnf-p2p` for compatibility.

| Complete package | Upstream project | Included host mode |
| --- | --- | --- |
| `getlostin-ctr-nitrofueled-pc` | [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC) | `psn` |
| `ryu7w7-octr-nitrofueled-pc` | [Ryu7w7/OCTR-NitroFueled-PC](https://github.com/Ryu7w7/OCTR-NitroFueled-PC) | `octr` |

Upstream pins, adapter patches and build recipes live in this repository under
[`integrations/`](integrations/) and [`distribution-lock.json`](distribution-lock.json).
Builds fetch the original upstream release, verify and apply the recorded patches,
and produce the complete package and its matching source archive. Historical
integration branches and published assets remain available; new builds do not
depend on those branches. Each manifest records exact source and dependency
revisions. Both packages include the shared [PSN backend](docs/OCTR.md)
and its runtime dependencies. Steam invitation acceptance and lobby joining have
a user-confirmed test on `GetLostIn/CTR-NitroFueled-PC`. The selected-friend
invitation send and `Ryu7w7/OCTR-NitroFueled-PC` still need in-game validation;
this is not broad multiplayer acceptance.

A `GetLostIn/CTR-NitroFueled-PC` run crashed in the host's mutex code while loading
a matchmaking race. Its P2P build includes the mutex storage protection already
present in `Ryu7w7/OCTR-NitroFueled-PC`; that crash still needs a human retest.
A subsequent bridge
message about the missing game UDP endpoint can be a consequence of a host crash.

The [automatic release workflow](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/actions/workflows/check-upstreams.yml)
checks new stable upstream releases daily, reapplies the adapters and publishes
complete packages only after both distributions pass their build and offline checks.
Conflicts or failed checks stop updates and open an issue for the maintainer.
Installed copies are updated manually from Releases; saves and settings stay local.

The standalone mod ZIP remains available for manual installation. The open
[GetLostIn/CTR-NitroFueled-PC #79](https://github.com/GetLostIn/CTR-NitroFueled-PC/pull/79) and
[Ryu7w7/OCTR-NitroFueled-PC #38](https://github.com/Ryu7w7/OCTR-NitroFueled-PC/pull/38) PRs propose the
shared host backend interface. If merged into released versions, they would let
compatible upstream builds load an independently supplied backend and mod, after
compatibility validation. Acceptance alone would not establish working Steam
transport or gameplay. Until then, the `psn` and `octr` routes require our
integrated hosts; the standalone ZIP's default remains the legacy native route.

**Experimental.** See [compatibility and limitations](#compatibility-and-limitations)
before installing.

## Requirements

- Windows x64 and one complete distribution package from this project's Releases.
- Your own supported PS4 game files: CUSA13795, update 01.21.
- Steam running and signed in with your account.

Both complete and standalone packages contain the
[CTR:NF Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch);
the bridge enables it automatically. Valve's unmodified `steam_api64.dll`
runtime is also included; players do not need to download the Steamworks SDK.

## Install

Download a complete Windows `getlostin-ctr-nitrofueled-pc` or `ryu7w7-octr-nitrofueled-pc` package from
[Releases](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/releases).

1. Extract the package into a new folder. It includes the portable port, backend,
   runtime dependencies and matching mod configuration.
2. Set up your own supported game files using the included port's launcher.
3. Start Steam, sign in and run `ctrnf-p2p.exe` to open the online launcher.

Keep the package's supplied host mode: `psn` for GetLostIn/CTR-NitroFueled-PC or `octr` for Ryu7w7/OCTR-NitroFueled-PC.
Do not overlay one distribution onto the other or replace its host with a stock
upstream release. Existing installations and saves stay where they are. The
matching source archive accompanies each full binary archive.

### Manual mod installation

The separate `ctrnf-p2p-mod-*.zip` contains the bridge, provider, local server,
signature patch and Valve runtime. It contains no host or `psn-bridge-backend.dll`.
Its default `host = native` targets the unchanged [GetLostIn `online` build at
`b1b4bf9`](https://github.com/GetLostIn/CTR-NitroFueled-PC/tree/b1b4bf9647132822147e76aeec47390c6cb157bf).
Extract it into that port's root beside `CTR-NitroFueled-PC.exe`, keeping your
existing `ctrnf-p2p.ini` when updating.

Manual installation with `host = psn` or `host = octr` additionally needs the
matching integrated host, `psn-bridge-backend.dll` and its runtime dependencies.
Follow the [PSN integration guide](docs/OCTR.md); selecting a different host mode
does not add the required interface to a stock upstream executable.

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

Each player installs the same package version and upstream project with their own Steam
account and game files. Steam shows you as playing **Spacewar** because
this experimental preview uses the SDK example's AppID 480. This is not an AppID
assigned to this mod or confirmation that Valve authorizes a permanent public
service under 480. Use an AppID authorized for your own integration for production;
ownership of an unrelated Steam game does not provide that authorization.

Add each other as Steam friends, start the game through the mod, enter Online
and use the game's friend Join or matchmaking.

The complete packages also relay invitations accepted in Steam while the game
is already running. The game's Invite action sends to the one friend selected
in its friend list; it does not open another friend picker. Starting the game by
accepting an invitation while it is closed is not supported.

Pit Stop items, coins and statistics are stored on each player's own PC; they
are not shared between players. A room ends when the player who created it leaves.

## Configuration

The supplied `ctrnf-p2p.ini` needs no changes for normal play. Keep its host mode
for the package you installed; these settings are common to both distributions:

```ini
[platform]
provider = steam

[steam]
app_id = 480

[server]
unlock_all = false
```

The `[game]` section uses `host = psn` in GetLostIn/CTR-NitroFueled-PC, `host = octr` in Ryu7w7/OCTR-NitroFueled-PC,
and `host = native` only for the standalone ZIP's legacy integration.

Set `unlock_all = true` to make the whole Pit Stop catalog available without
spending coins. Nothing is recorded as purchased: switching back to `false`
shows your real purchases and coins again. Races, challenges and statistics count
in both modes, and players using either mode can race together.

Server progression is kept per Steam account in
`demonware-server/data/ctrnf.db`. The game's own save is managed by the port and
is shared by every account; use the port's save-folder settings to keep saves apart.

See [configuration](docs/CONFIGURATION.md) for advanced settings.

## Build the bridge

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
[Releasing](docs/RELEASING.md) to assemble the standalone mod or complete distribution
packages with their corresponding sources.

## Compatibility and limitations

- The standalone ZIP defaults to the legacy native revision above. Full packages
  target only the host and dependency revisions recorded in their manifests;
  compatibility with later upstream releases requires a new build and checks.
- Windows only. Linux and macOS are not supported.
- With `host = native`, invitations are not delivered to the game; use friend Join or matchmaking.
  The in-game friend list may need a refresh, or a restart, before a newly
  started friend appears.
- Rooms do not move to another player when their creator leaves.
- Internet play between different networks is experimental and not guaranteed
  to work.
- The local server only accepts connections from the same PC and must not be
  exposed as a public server.

## License

The bridge is [MIT licensed](LICENSE). Host patches under `integrations/` retain
the host GPL licensing and attribution; they are not covered by the bridge MIT
license. The bundled Expat parser retains its
[own license](third_party/expat/upstream/COPYING).
orbiSteamworks is MIT licensed; Demonware Server uses PolyForm Shield 1.0.0.
Each component remains a separate project with its own source and license.
The ZIP also includes Valve's proprietary Steam API runtime under the
[Steamworks SDK Access Agreement](https://partner.steamgames.com/documentation/sdk_access_agreement);
see the [runtime notice](third_party/steamworks/NOTICE.txt). It is not MIT licensed.
Full distribution packages retain the host's original GPL-2.0-or-later notice;
the host build linked to GPLv3 FFmpeg is distributed under GPLv3 or later,
with its corresponding source archive and dependency notices.
The standalone mod ZIP contains no host binary. Neither package includes game
files, firmware or other Steamworks SDK files.
