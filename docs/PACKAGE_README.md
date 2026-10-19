# CTR:NF P2P mod for Windows x64

This experimental package combines independent builds of ctrnf-p2p,
orbiSteamworks and Demonware Server. Each project retains its own license.
The signature patch XML is included. The native port, game files and Steam API
runtime are supplied separately.

## Install into an existing native port

1. Use the GetLostIn port's online revision
   b1b4bf9647132822147e76aeec47390c6cb157bf with your own CUSA13795 01.21 files.
   Configure the game folder, preparation and preferences in its native launcher.
2. Close the port and bridge before updating. Extract this ZIP into the folder
   containing CTR-NitroFueled-PC.exe and run.py. Preserve your existing settings,
   saves, ctrnf-p2p.ini and demonware-server data directory.
3. Supply steam_api64.dll beside ctrnf-p2p.exe. This package contains no
   Steamworks files. Start Steam with the intended account.
4. For a new installation, copy ctrnf-p2p.example.ini to ctrnf-p2p.ini.
5. Enable the signature patch in the port's existing patches.json: add
   "CrashTeamRacingNitroFueled.xml/CTR:NF Server Signature Patch" to its
   "enabled" list and remove that key from "disabled" if present. Keep every
   other patch selection. The XML alone does not enable it.
6. Optionally run the checks below, then double-click ctrnf-p2p.exe and start
   the game from the native launcher. No terminal window is needed.

```powershell
.\ctrnf-p2p-cli.exe --check
.\ctrnf-p2p-cli.exe --probe
```

The checks do not start the game. The probe briefly starts the provider and
local server; it does not prove multiplayer connectivity.
Do not start demonware-server.exe separately for this mod.

## Play with another player

Install the same compatible components on both PCs, using a separate Steam
account and owned game files on each. Both players need the same AppID and
session realm, and should be Steam friends for friend Join. Start both games,
enter Online, then use the game's friend Join or matchmaking.

Leave AppID 480 unless your integration is configured for another available
AppID on both accounts. Normal and unlock-all players use the same namespace.
The server keeps progression locally; it is not a shared online economy.
See ctrnf-p2p-docs/TWO_PC.md for the full procedure.

## Known limits

This is a preview, not a qualified Internet multiplayer release. Game startup,
Online, Pit Stop and Steam overlay have human confirmation; two-PC Steam
races still need validation. The host's friend snapshot can require a refresh
or restart; native push invitations are not delivered. The P2P room ends if
its owner leaves. Linux and macOS game launch are unsupported.

Closing the game or launcher ends the session. After Apply and restart, start
ctrnf-p2p.exe again. Changing Steam account also ends the session.
Native saves are shared; server progression is keyed by account. Inventory
and equipped-item behavior across economy changes needs separate validation.

Diagnostics are written under ctrnf-p2p/. Keep raw runtime logs private.
Check ctrnf-p2p-manifest.json for exact component revisions and
ctrnf-p2p-SHA256SUMS.txt for file hashes.

## Source and licenses

- [ctrnf-p2p](https://github.com/pierluigizagaria/ctrnf-p2p): MIT.
- [orbiSteamworks](https://github.com/pierluigizagaria/orbisteamworks): MIT.
- [Demonware Server](https://github.com/pierluigizagaria/demonware-server):
  PolyForm Shield 1.0.0. Required Notice: Copyright 2026 Nextendo Network.
- [Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch): MIT.

Full license texts and third-party notices are under licenses/. The combined
archive does not relicense its components. No game, firmware or Steamworks
files are included.
