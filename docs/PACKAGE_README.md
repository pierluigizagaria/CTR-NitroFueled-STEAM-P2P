# CTR-NitroFueled-STEAM-P2P: standalone Windows mod

This experimental standalone mod adds Steam multiplayer to a compatible native
Crash Team Racing Nitro-Fueled port. It combines builds of ctrnf-p2p, orbiSteamworks and
Demonware Server, plus the CTR:NF Server Signature Patch and Valve's unmodified
Steam API runtime. This ZIP contains no native host, psn-bridge-backend.dll or
its runtime dependencies. Your game files are not included.

For a complete host and mod installation, download a `GetLostIn/CTR-NitroFueled-PC`
or `Ryu7w7/OCTR-NitroFueled-PC`
package from [Releases](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/releases)
and follow its included guide. The executable and configuration filenames remain
ctrnf-p2p for compatibility.

## Install manually on the legacy host

1. Set up GetLostIn/CTR-NitroFueled-PC at online revision
   b1b4bf9647132822147e76aeec47390c6cb157bf with your own CUSA13795 01.21 game
   files, following the port's instructions.
2. Close the port. Extract this ZIP into the folder containing
   CTR-NitroFueled-PC.exe. It replaces none of the port's settings or saves.
3. The included ctrnf-p2p.ini selects host = native for this legacy build,
   Steam AppID 480 and normal progression (unlock_all = false). When updating,
   keep your existing INI instead of overwriting it.
4. Start Steam and sign in.
5. Double-click ctrnf-p2p.exe, then start the game from the native launcher.
   The first start enables the signature patch automatically.

Always start the game through ctrnf-p2p.exe. Do not start demonware-server.exe
yourself.

## Install manually on an integrated host

The psn and octr modes require the corresponding integrated
GetLostIn/CTR-NitroFueled-PC or Ryu7w7/OCTR-NitroFueled-PC host,
psn-bridge-backend.dll and all of that DLL's runtime dependencies. Supply
those files separately or use the complete distribution package. Place the backend
beside CTR-NitroFueled-PC.exe, then select host = psn for GetLostIn/CTR-NitroFueled-PC or host = octr
for Ryu7w7/OCTR-NitroFueled-PC in the INI's [game] section. Keep that mode when updating the mod.

Stock upstream releases currently lack this backend interface. Changing the INI
cannot add it. See the [PSN integration guide](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/blob/main/docs/OCTR.md)
for compatibility requirements and the proposed upstream interfaces.

## Play with a friend

Both players install the same mod version on their own PC, with their own Steam
account and game files, and keep the same settings in ctrnf-p2p.ini. Steam shows
you as playing Spacewar because this preview uses the SDK example's AppID 480.
Valve has not assigned that ID to this mod. Runtime redistribution permission
does not establish permission to operate a permanent public service under 480.

Add each other as Steam friends, enter Online, then use the game's friend Join
or matchmaking.

Pit Stop items, coins and statistics stay on your own PC. Setting
unlock_all = true in ctrnf-p2p.ini makes the whole Pit Stop catalog available
without spending coins; switching back restores your real purchases and coins.
Players using either setting can race together.

## Known limits

- Experimental preview: play between different networks is not guaranteed.
- With host = native, invitations are not delivered to the game; use friend Join
  or matchmaking. Integrated PSN hosts can relay Steam invitation acceptance and,
  with the matching latest backend, send to the friend selected in the game.
  Cold-start invitations and a separate in-game friend picker are unsupported.
- The friend list may need a refresh or restart before a friend appears.
- A room ends when the player who created it leaves.
- Closing the game or launcher, Apply and restart, or switching Steam account
  ends the session; start ctrnf-p2p.exe again.

## Troubleshooting

Run these from a terminal in the port folder; neither starts the game:

- ctrnf-p2p-cli.exe --check checks files and settings without changing them.
  Before the first normal start it reports that the patch is not enabled yet.
- ctrnf-p2p-cli.exe --probe also starts the provider and local server briefly;
  Steam must already be running and signed in.

Logs are under ctrnf-p2p/ and demonware-server/logs/. They can contain account
details, so do not post them unedited. ctrnf-p2p-docs/INSTALLATION.md covers
updating, uninstalling and common problems.

## Source and licenses

- [CTR-NitroFueled-STEAM-P2P](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P): MIT bridge.
- [orbiSteamworks](https://github.com/pierluigizagaria/orbisteamworks): MIT.
- [Demonware Server](https://github.com/pierluigizagaria/demonware-server):
  PolyForm Shield 1.0.0. Required Notice: Copyright 2026 Nextendo Network.
- [Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch): MIT.
- Steam Client API (steam_api64.dll): proprietary Valve runtime; see
  licenses/steamworks/NOTICE.txt and the
  [Steamworks SDK Access Agreement](https://partner.steamgames.com/documentation/sdk_access_agreement).

ctrnf-p2p-manifest.json lists the exact source revision of each component and
ctrnf-p2p-SHA256SUMS.txt the file hashes. Full license texts and third-party
notices are under licenses/. The combined archive does not relicense its
components. No game, firmware, native-port binary or other Steamworks SDK files
are included. This project is not affiliated with or endorsed by Valve.
