# Host PSN integrations

The complete [CTR-NitroFueled-STEAM-P2P packages](https://github.com/pierluigizagaria/CTR-NitroFueled-STEAM-P2P/releases)
rebuild stable upstream releases with a shared PSN backend extension and include
the matching mod. Their host modes are:

| Package | Upstream host | `[game]` setting |
| --- | --- | --- |
| `getlostin-ctr-nitrofueled-pc` | [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC) | `host = psn` |
| `ryu7w7-octr-nitrofueled-pc` | [Ryu7w7/OCTR-NitroFueled-PC](https://github.com/Ryu7w7/OCTR-NitroFueled-PC) | `host = octr` |

Both currently require our integrated host build; stock upstream releases do
not provide this extension. The separate `host = native` route supports the
unmodified GetLostIn `online` build at
[`b1b4bf9`](https://github.com/GetLostIn/CTR-NitroFueled-PC/tree/b1b4bf9647132822147e76aeec47390c6cb157bf).

## Upstream proposals

The open [GetLostIn/CTR-NitroFueled-PC #79](https://github.com/GetLostIn/CTR-NitroFueled-PC/pull/79)
and [Ryu7w7/OCTR-NitroFueled-PC #38](https://github.com/Ryu7w7/OCTR-NitroFueled-PC/pull/38) PRs propose
the shared `PsnBackendV1` interface; the GetLostIn proposal targets `main`.
If accepted and included in upstream releases, compatible builds could load an
independently supplied backend and mod after compatibility validation. That
would allow manual installation without our rebuilt host for those releases.
It would still require the backend DLL, its dependencies and validation of the
host's routing and Steam transport. A merged interface alone does not establish
working multiplayer.

## Manual backend installation

The standalone `ctrnf-p2p-mod-*.zip` is available separately. It includes the
bridge, orbiSteamworks, publisher server, signature patch and Valve runtime,
but does not include `psn-bridge-backend.dll` or its runtime dependencies.

For either PSN route:

1. Reconstruct the corresponding host using the pinned recipe under
   `integrations/` (see [Releasing](RELEASING.md)), or use the matching complete package. A stock upstream binary is not sufficient.
2. Build that host's optional `psn-bridge-backend` target with
   `PSN_BRIDGE_BACKEND=ON`, or obtain the backend and its dependency set from the
   same complete package. Keep the host, backend ABI and mod versions matched.
3. Place `psn-bridge-backend.dll` and its runtime dependencies in the port root
   beside `CTR-NitroFueled-PC.exe`, the bridge, provider and publisher server.
   Supplying only that DLL can fail if its dependent libraries are missing.
4. Use an orbiSteamworks build exposing PSN events version 1. Set `[game]`
   `host = psn` for GetLostIn/CTR-NitroFueled-PC or `host = octr` for Ryu7w7/OCTR-NitroFueled-PC in `ctrnf-p2p.ini`.
   The standalone ZIP's default `host = native` is for the legacy host only.

Complete packages already contain these files and the matching INI. The backend
comes from the host's PSN module and retains its license; distributing the mod
separately does not relicense the host or backend. Keep the package's component
notices and corresponding sources.

## Runtime behavior

The normal bridge entry point still opens the port's launcher. The bridge passes
an absolute adapter path and a fresh private connection capability through the
child environment. Do not save that capability in the INI, logs or a shortcut.
Game files, preferences, saves and patch selection remain owned by the port.
The required signature patch is enabled in the same way as the native adapter.

orbiSteamworks performs the Steam-to-PSN notification mapping. The bridge only
relays copied notifications. Each host owns guest callback registration, filters,
memory and SystemService delivery. It re-fetches friend/session data through
the provider's existing WebAPI surface. Accepting a Steam invitation and joining
the game party remain separate operations. Steam continues to run in the bridge;
the Ryu7w7/OCTR-NitroFueled-PC adapter does not initialize a second Steam client context.

Both PSN routes use the existing companion capability for admission. They disable
the fabricated-token admission needed by the unmodified legacy host. RyuNET
nickname claims and synthetic friend lists are disabled when Ryu7w7/OCTR-NitroFueled-PC selects an
external PSN backend. Transport is configured separately: the bridge sets
`BB_ONLINE=1`, `BB_ONLINE_TUNNEL=0` and `BB_NET_PRESERVE_ENDPOINTS=1` so its route
uses the guest's endpoints without Ryu7w7/OCTR-NitroFueled-PC port remapping or UPnP-body rewriting.
Selecting a PSN backend alone does not change Ryu7w7/OCTR-NitroFueled-PC's socket policy; ordinary
Ryu7w7/OCTR-NitroFueled-PC startup is unchanged.

The v0.6.3 integration also keeps RyuNET's clock synchronization, HTTP request-form
fallbacks and inventory headers out of external publisher requests. Its new Room
panel directs Steam/P2P players to the game's lobby; RyuNET ping information is
not presented as Steam lobby state.

GetLostIn/CTR-NitroFueled-PC keeps its native private-server routing with `BB_ONLINE_SERVER` and
`BB_ONLINE_HTTP_PORT`; it does not use Ryu7w7/OCTR-NitroFueled-PC's transport switches. Both full
packages include the adapter and select their host mode in `ctrnf-p2p.ini`.

The scope is live presence invalidations, delivery of invitations accepted
through Steam while the supervised session is running, and sending an invitation
to the one friend already selected in the game's friend list. The fixed-recipient
send uses the provider's existing friend-list and session-invitation WebAPI. It
reports success only after the provider accepts the send; remote delivery and
joining remain separate actions. No additional picker opens when pressing the
game's Invite button.

This does not implement an in-game invitation picker, cold-start `+connect_lobby`
handling, custom invitation messages, multiple recipients, every PSN API, or
guarantee that the game's UI refreshes correctly before human validation.
Provider, relay and guest-ABI tests are offline contract checks, not game or
multi-PC acceptance.

See the [local PSN relay protocol](PSN_RELAY.md) for ownership, version negotiation,
request bounds and event acknowledgement.
