# CTR:NF P2P mod for Windows x64

This experimental package adds Steam multiplayer to the native Crash Team Racing
Nitro-Fueled port. It combines builds of ctrnf-p2p, orbiSteamworks and
Demonware Server, plus the CTR:NF Server Signature Patch. The native port, your
game files and the Steam API library are not included.

## Install

1. Set up the GetLostIn native port at online revision
   b1b4bf9647132822147e76aeec47390c6cb157bf with your own CUSA13795 01.21 game
   files, following the port's instructions.
2. Close the port. Extract this ZIP into the folder containing
   CTR-NitroFueled-PC.exe. It replaces none of the port's settings or saves.
3. Copy steam_api64.dll into the same folder. It is in Valve's Steamworks SDK,
   under redistributable_bin/win64/.
4. The included ctrnf-p2p.ini is ready for Steam with AppID 480 and normal
   progression (unlock_all = false). When updating, keep your existing INI
   instead of overwriting it.
5. Start Steam and sign in.
6. Double-click ctrnf-p2p.exe, then start the game from the native launcher.
   The first start enables the signature patch automatically.

Always start the game through ctrnf-p2p.exe. Do not start demonware-server.exe
yourself.

## Play with a friend

Both players install the same mod version on their own PC, with their own Steam
account and game files, and keep the same settings in ctrnf-p2p.ini. Steam shows
you as playing Spacewar (AppID 480); nobody needs to own another game.

Add each other as Steam friends, enter Online, then use the game's friend Join
or matchmaking.

Pit Stop items, coins and statistics stay on your own PC. Setting
unlock_all = true in ctrnf-p2p.ini makes the whole Pit Stop catalog available
without spending coins; switching back restores your real purchases and coins.
Players using either setting can race together.

## Known limits

- Experimental preview: play between different networks is not guaranteed.
- Invitations are not delivered to the game; use friend Join or matchmaking.
- The friend list may need a refresh or restart before a friend appears.
- A room ends when the player who created it leaves.
- Closing the game or launcher, Apply and restart, or switching Steam account
  ends the session; start ctrnf-p2p.exe again.

## Troubleshooting

Run these from a terminal in the port folder; neither starts the game:

- ctrnf-p2p-cli.exe --check checks files and settings without changing them.
  Before the first normal start it reports that the patch is not enabled yet.
- ctrnf-p2p-cli.exe --probe also starts Steam and the local server briefly.

Logs are under ctrnf-p2p/ and demonware-server/logs/. They can contain account
details, so do not post them unedited. ctrnf-p2p-docs/INSTALLATION.md covers
updating, uninstalling and common problems.

## Source and licenses

- [ctrnf-p2p](https://github.com/pierluigizagaria/ctrnf-p2p): MIT.
- [orbiSteamworks](https://github.com/pierluigizagaria/orbisteamworks): MIT.
- [Demonware Server](https://github.com/pierluigizagaria/demonware-server):
  PolyForm Shield 1.0.0. Required Notice: Copyright 2026 Nextendo Network.
- [Server Signature Patch](https://github.com/pierluigizagaria/ctrnf-server-signature-patch): MIT.

ctrnf-p2p-manifest.json lists the exact source revision of each component and
ctrnf-p2p-SHA256SUMS.txt the file hashes. Full license texts and third-party
notices are under licenses/. The combined archive does not relicense its
components. No game, firmware or Steamworks files are included.
