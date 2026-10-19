# OCTR integration

The optional `game.host = octr` adapter uses OCTR's PSN backend extension. It
requires the proposed OCTR changes; an unmodified OCTR release does not provide
this extension. `host = native` keeps the existing GetLostIn integration.

Build OCTR with its PSN host module and build its optional `psn-bridge-backend`
target. Place `psn-bridge-backend.dll` and its runtime dependencies in the port
root beside `CTR-NitroFueled-PC.exe`, the bridge, provider and publisher server.
Use an orbiSteamworks build exposing PSN events version 1. Set:

```ini
[game]
host = octr
```

The normal bridge entry point still opens the port's launcher. The bridge passes
an absolute adapter path and a fresh private connection capability through the
child environment. Do not save that capability in the INI, logs or a shortcut.
Game files, preferences, saves and patch selection remain owned by the port.
The required signature patch is enabled in the same way as the native adapter.

orbiSteamworks performs the Steam-to-PSN notification mapping. The bridge only
relays copied notifications. OCTR owns guest callback registration, filters,
memory and SystemService delivery. It re-fetches friend/session data through
the provider's existing WebAPI surface. Accepting a Steam invitation and joining
the game party remain separate operations. Steam continues to run in the bridge;
the OCTR adapter does not initialize a second Steam client context.

The OCTR route uses the existing companion capability for admission. It disables
the fabricated-token admission needed by the unmodified native host. RyuNET
nickname claims, tunnels and synthetic friend lists are disabled only when
OCTR explicitly selects this external backend; ordinary OCTR startup is unchanged.

The scope is live presence invalidations and delivery of invitations accepted
through Steam while the supervised session is running. This does not implement
an in-game invitation picker, cold-start `+connect_lobby` handling, every PSN API,
or guarantee that the game's UI refreshes correctly before human validation.
Provider, relay and guest-ABI tests are offline contract checks, not game or
multi-PC acceptance. No installed native port is replaced by this source change.

See the [local PSN relay protocol](PSN_RELAY.md) for ownership, version negotiation,
request bounds and event acknowledgement.
