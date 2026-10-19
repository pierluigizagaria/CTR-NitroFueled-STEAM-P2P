# Configuration

Unknown/duplicate sections or settings and invalid values stop startup. There are
no aliases for removed settings. Boolean values are exactly `true` or `false`.
Integers are decimal. Full-line `;`/`#` comments are accepted. Unquoted inline
comments start after whitespace; a JSON quoted string keeps such punctuation.
Paths passed to the bridge must be printable ASCII.

The configuration holds only bridge settings and the links between its components.
Native paths, saves and preferences are never copied here.

| Setting | Default and meaning |
| --- | --- |
| platform.provider | `steam`; other providers are currently unsupported |
| steam.app_id | `480`; nonzero uint32. Every peer must use the same licensed AppID |
| game.host | `native`; selects the bridge's host adapter, not a native setting |
| server.unlock_all | `false`; forwarded to the server's `CTR_UNLOCK_ALL`. Same saves and database in both modes |

Advanced settings, omitted from the example:

| Setting | Default and meaning |
| --- | --- |
| platform.library | `orbisteamworks.dll` on Windows, `liborbisteamworks.dylib` on macOS, `liborbisteamworks.so` on other POSIX targets |
| steam.library | `steam_api64.dll` on Windows, `libsteam_api.dylib` on macOS, `libsteam_api.so` otherwise; must be beside the bridge executable |
| server.executable | `demonware-server.exe` on Windows, `demonware-server` elsewhere, beside the bridge. Its working folder is `demonware-server/` beside that executable, with `data/` (passed as `DATA_DIR`) and `logs/` |
| session.realm | `ctrnf-p2p`; at most 64 bytes, same for all peers. Matchmaking namespace only: never economy or progression |
| network.address | `127.0.0.2`; loopback address in 127.0.0.2–254 for the bridge front and the server listeners. Distinct instances on one PC need distinct addresses |
| network.http_port | `31380`; the native HTTP front; must not collide with the server listeners |

The native adapter fixes the rest of the contract: Demonware title `5760` (the PS4
asset title CUSA13795 is a different identifier), build `01.21`, the game's UDP
source as observed at `127.0.0.1`, the server's auth listener on port `8460` of
`network.address`, and native-token admission (`CTR_LOCAL_WEAK_TOKEN=1`), because
the unchanged host fabricates its token. The server's own default for that mode
stays disabled; a future host adapter declares its own requirements.
