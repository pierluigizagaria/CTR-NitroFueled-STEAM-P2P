# Configuration

`ctrnf-p2p.ini` sits beside `ctrnf-p2p.exe` and holds only the bridge's own
settings. The port's paths, saves and preferences stay in the port's settings.

Every player in a session needs the same `steam.app_id` and `session.realm`.
The defaults work for normal play.

## Basic settings

| Setting | Default and meaning |
| --- | --- |
| `platform.provider` | `steam`, the only supported provider |
| `steam.app_id` | `480` (the Steamworks SDK example, Spacewar). A different nonzero AppID must be authorized for this integration and available to every player's Steam account; owning an unrelated game is not sufficient authorization |
| `game.host` | `native` (default, legacy GetLostIn online build), `psn` (channel-a), or `octr` (channel-b); full packages preselect the matching [PSN backend integration](OCTR.md) |
| `server.unlock_all` | `false`. `true` makes the whole Pit Stop catalog available without spending coins and without recording purchases; see the [README](../README.md#configuration) |

## Advanced settings

These are omitted from the example and rarely need changing.

| Setting | Default and meaning |
| --- | --- |
| `platform.library` | `orbisteamworks.dll` on Windows, `liborbisteamworks.dylib` on macOS, `liborbisteamworks.so` on other POSIX targets |
| `steam.library` | `steam_api64.dll` on Windows, `libsteam_api.dylib` on macOS, `libsteam_api.so` otherwise; must be beside the bridge executable |
| `server.executable` | `demonware-server.exe` on Windows, `demonware-server` elsewhere, beside the bridge. Its working folder is `demonware-server/` beside that executable, with `data/` and `logs/` |
| `session.realm` | `ctrnf-p2p`; at most 64 bytes. Players only see each other in the same realm. It does not separate progression |
| `network.address` | `127.0.0.2`; a loopback address in 127.0.0.2–254 for the bridge and the local server. Two bridges on one PC need different addresses |
| `network.http_port` | `31380`; the bridge's HTTP port for the game; must not collide with the local server's ports |

## File format

- Unknown or duplicate sections and settings, and invalid values, stop startup
  with an error.
- Boolean values are exactly `true` or `false`; integers are decimal.
- Full-line comments start with `;` or `#`. An unquoted inline comment starts
  after whitespace; put a value in JSON double quotes to keep such characters.
- Paths must be printable ASCII. Relative paths resolve beside the executable.

`ctrnf-p2p-cli.exe --config path` reads another file; that path itself resolves
from the current directory.
