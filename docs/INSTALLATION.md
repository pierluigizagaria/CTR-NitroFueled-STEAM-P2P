# Installing and running the mod

Download the Windows mod ZIP from
[Releases](https://github.com/pierluigizagaria/ctrnf-p2p/releases).
It contains the bridge, provider, server, signature patch XML and component
licenses. The included `CTR-P2P-README.md` provides the short setup.
For manual builds, select the same four runtime binaries shown below.

The mod is installed directly into the root folder of an existing native port
installation (the folder with `CTR-NitroFueled-PC.exe`, `run.py`, `bbport.ini` and
`patches/`). The bridge executable's folder is the port root: no setting names it.

```text
<port root>/
├── CTR-NitroFueled-PC.exe        native launcher (unchanged)
├── bbport.ini, launcher.ini, user/, out/    native settings and data
├── patches/, patches.json                 native patch definitions and selection
├── ctrnf-p2p.exe, ctrnf-p2p.ini  desktop bridge and its configuration
├── ctrnf-p2p-cli.exe             console entry point for diagnostics/scripts
├── ctrnf-p2p/                    bridge-owned state and diagnostics only
├── demonware-server.exe          the independent local server
├── demonware-server/             its data/ctrnf.db and logs/
├── orbisteamworks.dll            the provider
└── steam_api64.dll               user-supplied Steam API library
```

Place the user-supplied Steam API library beside the bridge executable; nothing
from Steamworks is included or distributed. `steam_appid.txt` is neither required
nor consulted: `steam.app_id` is the only AppID source.

The [Steamworks SDK documentation](https://partner.steamgames.com/doc/sdk)
describes Valve's runtime library. Obtain it separately; the mod does not
download it or change the Steam client's installation.

The ZIP includes the CTR:NF Server Signature Patch XML under `patches/`. On a normal
launch, the bridge validates the XML and adds
`CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch` to the native
configuration's `enabled` list, removing that same key from `disabled` if present.
It preserves all other patch selections and settings. An already enabled patch
requires no change. Invalid XML or an invalid patch configuration stops startup
without replacing the configuration with defaults.

The local server
sends unsigned authentication replies: the game's verifier then fails and this patch
removes the rejection of that failure. No response-signing key or OpenSSL is needed.
The patch supports only the verified CUSA13795 01.21 `eboot.bin` (see its own
documentation); the bridge does not inspect the game files.

## Run

On Windows, double-click `ctrnf-p2p.exe`. It opens the native launcher without a
terminal window. Lifecycle messages go to `ctrnf-p2p/bridge.log`; a startup or
session error appears in a dialog. Close the native launcher to end the session.

On POSIX the console executable is still named `ctrnf-p2p`; there is no desktop
entry point, and native game launch remains unsupported there.

Copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini` beside the executable. Relative
paths resolve beside the executable, even with `--config`; `--config path` itself
resolves from the current working directory.

An ordinary launch starts the port's own launcher; the player starts the game from
it as usual. Everything native (game folder, saves, preparation, patches, graphics,
input, language, restart) is handled by the port with its own settings. The session
belongs to the first game process that opens the game's UDP socket: when that game
exits, including the native in-game "Apply and restart", the bridge ends the session
and closes the launcher. Relaunch the bridge to play online again. Closing the
launcher before starting a game also ends it. Windows uses a kill-on-close Job
Object for the launcher and all its descendants; the provider owns its own server.
Host exit, bridge teardown, provider/server failure or a Steam account change tears
the session down. There is no menu-idle or elapsed-session cutoff.

## Troubleshooting

The console entry point keeps stdout, stderr and exit codes available to terminals
and scripts. These commands do not start the game:

```powershell
.\ctrnf-p2p-cli.exe --check
.\ctrnf-p2p-cli.exe --probe
```

`--check` is read-only: it checks configuration, required files and the selected
signature patch without starting components or enabling the patch. Before the
first normal launch it can therefore report that the patch is not enabled yet.
`--probe` briefly starts the provider and local server to check initialization,
then stops them. It does not change the native patch configuration or test a
multiplayer session. Keep raw runtime logs private when reporting a problem.
