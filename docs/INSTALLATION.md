# Installing and running the mod

Download the Windows mod ZIP from
[Releases](https://github.com/pierluigizagaria/ctrnf-p2p/releases).
It contains the bridge, provider, server, signature patch XML and component
licenses. The [package instructions](PACKAGE_README.md) provide the short setup.
For manual builds, select the same four runtime binaries shown below.

The mod is installed directly into the root folder of an existing native port
installation (the folder with `CTR-NitroFueled-PC.exe`, `run.py`, `bbport.ini` and
`patches/`). The bridge executable's folder is the port root: no setting names it.

```text
<port root>/
├── CTR-NitroFueled-PC.exe        native launcher (unchanged)
├── bbport.ini, launcher.ini, user/, out/, patches/, patches.json   native, unchanged
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

Install the CTR:NF Server Signature Patch XML into the port's `patches/` folder and
enable `CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch` in the port's
existing `patches.json` (`enabled` list), keeping its other selections. The release
file is disabled by default; copying it alone does not activate it. The local server
sends unsigned authentication replies: the game's verifier then fails and this patch
removes the rejection of that failure. No response-signing key or OpenSSL is needed.
The patch supports only the verified CUSA13795 01.21 `eboot.bin` (see its own
documentation); the bridge does not inspect the game files.

## Run

On Windows, double-click `ctrnf-p2p.exe`. It opens the native launcher without a
terminal window. Lifecycle messages go to `ctrnf-p2p/bridge.log`; a startup or
session error appears in a dialog. Close the native launcher to end the session.
The console entry point runs the same bridge logic and keeps stdout, stderr and
exit codes available to terminals and scripts:

```text
ctrnf-p2p-cli --check
ctrnf-p2p-cli --probe
ctrnf-p2p-cli --directory-check
ctrnf-p2p-cli
```

On POSIX the console executable is still named `ctrnf-p2p`; there is no desktop
entry point, and native game launch remains unsupported there.

Copy `ctrnf-p2p.example.ini` to `ctrnf-p2p.ini` beside the executable. Relative
paths resolve beside the executable, even with `--config`; `--config path` itself
resolves from the current working directory.

`--check` validates the configuration, the provider, Steam and server files, and the
launch prerequisites (native launcher and signature patch selection) without
starting anything. `--probe` starts the provider, the hidden local server and the
HTTP listener, verifies readiness and stops them; it does not start a game or
qualify game/peer transport. `--directory-check` additionally creates a temporary
room, reads it, requires that exact room in search and leaves it. These two
portable diagnostics do not need the native launcher or the patch.

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
