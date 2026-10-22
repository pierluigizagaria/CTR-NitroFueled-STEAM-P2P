# Installing CTR-NitroFueled-STEAM-P2P

Choose a complete Windows x64 `getlostin-ctr-nitrofueled-pc` or `ryu7w7-octr-nitrofueled-pc` package from
[Releases](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/releases).
Both contain the portable host, its PSN backend and runtime dependencies, plus
the bridge, orbiSteamworks, Demonware Server, Valve's Steam API runtime and the
signature patch. You supply your own CUSA13795 01.21 game files and a signed-in
Steam account. `CTR-P2P-README.md` in the ZIP covers that package's installation.

## Complete package

1. Extract one package into a new folder, keeping existing installations in place.
2. Configure your game files using the included `CTR-NitroFueled-PC.exe` launcher
   and that port's preparation instructions.
3. Keep the supplied `ctrnf-p2p.ini`: GetLostIn/CTR-NitroFueled-PC uses `host = psn`; Ryu7w7/OCTR-NitroFueled-PC uses
   `host = octr`. Both default to AppID 480 and normal progression.
4. Start Steam and sign in, then run `ctrnf-p2p.exe` and start the game from its
   launcher.

GetLostIn/CTR-NitroFueled-PC rebuilds stable releases of the
[GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC);
Ryu7w7/OCTR-NitroFueled-PC rebuilds stable releases of
[Ryu7w7/OCTR-NitroFueled-PC](https://github.com/Ryu7w7/OCTR-NitroFueled-PC).
Each includes the matching adapter. Do not mix distributions or use a stock
upstream updater to replace a P2P build. The source archive beside each binary
download matches its manifest.

## Standalone mod: manual installation

The separate `ctrnf-p2p-mod-*.zip` remains available for an existing compatible
host. It includes the mod components and Valve runtime, but no host executable,
`psn-bridge-backend.dll` or backend runtime dependencies.

Its default `host = native` supports the unchanged
[GetLostIn `online` revision `b1b4bf9`](https://github.com/GetLostIn/CTR-NitroFueled-PC/tree/b1b4bf9647132822147e76aeec47390c6cb157bf).
For `host = psn` or `host = octr`, first obtain the matching integrated host,
backend DLL and dependencies described in the
[PSN integration guide](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/blob/main/docs/OCTR.md).
Current stock upstream releases do not provide the required backend interface.

The mod goes directly into the root folder of an existing native port
installation: the folder with `CTR-NitroFueled-PC.exe`, `run.py`, `bbport.ini`
and `patches/`. After installation it looks like this:

```text
<port root>/
├── CTR-NitroFueled-PC.exe        the compatible host's launcher
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

1. Set up the compatible port and your game files with the port's instructions.
2. Close the port, then extract the standalone mod ZIP into its root.
3. Keep your existing `ctrnf-p2p.ini` when updating. For a fresh installation,
   the included INI selects the legacy `native` host, Steam AppID 480 and normal
   progression (`unlock_all = false`). An integrated host needs its matching
   `psn` or `octr` mode and backend files before starting the bridge.

The layout above shows the mod files common to all routes. Integrated hosts also
have `psn-bridge-backend.dll` and its runtime dependencies beside the launcher.

The ZIP includes the unmodified Windows x64 `steam_api64.dll` redistributable.
No SDK download or `steam_appid.txt` is needed. Its Valve license notice is under
`licenses/steamworks/NOTICE.txt` in the ZIP.

## Signature patch

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

### Complete packages

Download the new complete package for the same upstream project and extract it into a new
folder. Keep the matching host, backend and mod together. Leave the old
installation intact while configuring the new one. Use the port's instructions
to select or transfer your existing game saves and settings; publisher progress
is separate, under `demonware-server/data/`. Copy that directory only while both
installations are closed, and keep the original until the update is checked.
Do not replace a package's host mode with the standalone ZIP's `native` default.

### Standalone mod

Close the port and bridge, then extract the new standalone ZIP over the existing
mod files, skipping `ctrnf-p2p.ini` to keep your configuration. If your extraction
tool cannot skip individual files, extract into a temporary folder and copy
everything except `ctrnf-p2p.ini` into the port root. The ZIP contains no
`demonware-server/` data. On integrated hosts, check the backend requirements in
[the PSN integration guide](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/blob/main/docs/OCTR.md)
before replacing a component. Players should use the same
package version and upstream project.

## Uninstall

Close the port and bridge first. To remove a complete portable installation,
retain its native saves, settings and `demonware-server/data/` before removing
the package folder.

To remove only the standalone mod, use `ctrnf-p2p-manifest.json` to identify the
files it added. Keep files shared with the host or other mods, including any
shared license directories or Steam runtime. Remove the mod's executables,
configuration, logs and signature patch XML only when they are no longer needed.
Without its XML file the signature patch is no longer applied. Keep
`demonware-server/` if you want to preserve your Pit Stop progress. Removing the
mod does not turn an integrated host into a stock upstream build.

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
| PSN backend missing or incompatible | Use the matching full package, or supply the integrated host, `psn-bridge-backend.dll` and its dependencies for manual installation; keep the correct host mode |
| Patch XML or `patches.json` invalid | Extract `patches/CrashTeamRacingNitroFueled.xml` again. Repair `patches.json`, or delete it and choose your other patches again in the launcher |
| A friend does not appear | Both use the same mod version and settings, are Steam friends and started the game through `ctrnf-p2p.exe`; refresh the friend list |
| Address or port already in use | Another bridge or server is already running; close it, or see `network.address` in [configuration](CONFIGURATION.md) |

Logs in `ctrnf-p2p/`, `demonware-server/logs/` and the port's own logs can
contain account details. Do not paste them unedited into public issues.
