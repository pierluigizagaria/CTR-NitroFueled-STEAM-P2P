# Installing and running the mod

Download the Windows mod ZIP from
[Releases](https://github.com/pierluigizagaria/ctrnf-p2p/releases).
It contains the bridge, orbiSteamworks, Demonware Server, Valve's Steam API
runtime, a ready-to-use INI, the signature patch XML and the component licenses.
`CTR-P2P-README.md` in the ZIP is the short version of this guide.

Full `channel-a` and `channel-b` packages also contain the integrated portable
host, PSN adapter and dependencies. Extract a full package into a new folder,
configure your own game files with its launcher, and start `ctrnf-p2p.exe`.
Keep the supplied host mode (`psn` for channel-a, `octr` for channel-b). Do not
mix host files from different channels or use the stock updater to replace a
P2P build. The source archive beside the download matches its manifest.
The instructions below for adding the standalone mod apply to the legacy host.

## Install

The mod goes directly into the root folder of an existing native port
installation: the folder with `CTR-NitroFueled-PC.exe`, `run.py`, `bbport.ini`
and `patches/`. After installation it looks like this:

```text
<port root>/
├── CTR-NitroFueled-PC.exe        native launcher (unchanged)
├── bbport.ini, launcher.ini, user/, out/    native settings and data
├── patches/, patches.json        native patch definitions and selection
├── ctrnf-p2p.exe, ctrnf-p2p.ini  the bridge and its configuration
├── ctrnf-p2p-cli.exe             console version, for troubleshooting
├── ctrnf-p2p/                    bridge logs and state
├── demonware-server.exe          the local server
├── demonware-server/             server database (data/ctrnf.db) and logs
├── orbisteamworks.dll            the Steam provider
└── steam_api64.dll               Valve runtime (included)
```

1. Set up the port and your game files with the port's own instructions.
2. Close the port, then extract the ZIP into the port root.
3. The included `ctrnf-p2p.ini` is ready for Steam with AppID 480 and normal
   progression (`unlock_all = false`). No copying or editing is needed.

The ZIP includes the unmodified Windows x64 `steam_api64.dll` redistributable.
No SDK download or `steam_appid.txt` is needed. Its Valve license notice is under
`licenses/steamworks/NOTICE.txt` in the ZIP.

### Signature patch

The ZIP adds `patches/CrashTeamRacingNitroFueled.xml`, which contains the
[CTR:NF Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch).
The local server's authentication replies are unsigned, and the game only
accepts them with this patch. It supports only the CUSA13795 01.21 `eboot.bin`.

On every normal start the bridge checks the XML and makes sure the patch is
enabled in the port's `patches.json`. All other patch selections and settings
are kept. If the XML or `patches.json` is invalid, the bridge stops with an error
and leaves the file unchanged.

## Run

Double-click `ctrnf-p2p.exe`. It opens the native launcher without a terminal
window; start the game from there as usual. Everything native (game folder,
saves, preparation, patches, graphics, input, language) keeps working through
the port's own settings.

The online session belongs to the game started from that launcher. It ends, and
the launcher closes, when:

- you close the game or the launcher;
- you use the game's **Apply and restart** action;
- the Steam account changes;
- the provider or the local server stops.

Start `ctrnf-p2p.exe` again to play online. Sessions have no time limit.

Messages go to `ctrnf-p2p/bridge.log`; errors appear in a dialog.

## Update

Close the port and the bridge, then extract the new ZIP over the old files,
skipping `ctrnf-p2p.ini` to keep your existing configuration. If your extraction
tool cannot skip individual files, extract into a temporary folder and copy
everything except `ctrnf-p2p.ini` into the port root. The ZIP contains no
`demonware-server/` data. Every player should use the same mod version.

## Uninstall

Close the port and the bridge, then delete the files the ZIP added:
`ctrnf-p2p.exe`, `ctrnf-p2p-cli.exe`, `ctrnf-p2p.example.ini`, `ctrnf-p2p.ini`,
`ctrnf-p2p/`, `demonware-server.exe`, `orbisteamworks.dll`,
`patches/CrashTeamRacingNitroFueled.xml`, `CTR-P2P-README.md`,
`ctrnf-p2p-docs/`, `licenses/`, `ctrnf-p2p-manifest.json` and
`ctrnf-p2p-SHA256SUMS.txt`. Without its XML file the signature patch is no longer
applied. Delete `demonware-server/` only if you no longer need your Pit Stop
progress, and `steam_api64.dll` if nothing else uses it.

## Troubleshooting

`ctrnf-p2p-cli.exe` shows the same checks in a terminal, with exit codes. None of
these commands starts the game:

```powershell
.\ctrnf-p2p-cli.exe --check
.\ctrnf-p2p-cli.exe --probe
.\ctrnf-p2p-cli.exe --directory-check
```

- `--check` checks the configuration, the required files and the signature
  patch, without starting anything or changing files. Before the first normal
  start it reports that the patch is not enabled yet; that is expected.
- `--probe` also starts the provider and the local server briefly, then stops
  them. Use it when Steam or the server fails to start.
- `--directory-check` additionally creates, searches for and leaves a test room
  through Steam.

Common problems:

| Symptom | Check |
| --- | --- |
| Steam library missing or signed out | `steam_api64.dll` is in the port root, Steam is running and signed in |
| Patch XML or `patches.json` invalid | Extract `patches/CrashTeamRacingNitroFueled.xml` again. Repair `patches.json`, or delete it and choose your other patches again in the launcher |
| A friend does not appear | Both use the same mod version and settings, are Steam friends and started the game through `ctrnf-p2p.exe`; refresh the friend list |
| Address or port already in use | Another bridge or server is already running; close it, or see `network.address` in [configuration](CONFIGURATION.md) |

Logs in `ctrnf-p2p/`, `demonware-server/logs/` and the port's own logs can
contain account details. Do not paste them unedited into public issues.
