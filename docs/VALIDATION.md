# Validation record

## 2026-10-19

Evidence categories follow the owning projects: I for explicit replacement
contracts and synthetic fixtures; C for owned game bytes/execution; H/U for the
relevant public host reconstruction. Build/fixture success is not live Steam,
original-game or WAN acceptance.

- B0 native: pinned upstream b1b4bf9 built from source in an ignored worktree;
  no host source change. Executable SHA-256
  `de03b2a853e2ce9fc335f0027783ab49858e28244d987a5a2ad180907f94d5d0`.
  Full upstream Python run:99 tests,67 passed,28 skipped,2 failures and2 errors
  due to platform-specific Windows/Linux fixture limitations. Portable GPU
  motion-history/UI tests pass; the network fixture passes with an explicitly
  test-only Windows shim. This is not a clean full upstream test-suite pass.
- B0/B1 provider: 8008154, Windows static/shared48/48 tests pass. New transport,
  collision/revocation/source validation, mixed-mode/AppID rejection and persona
  API covered. DLL SHA-256
  `c0025482bac7ffc98a45139b826761f0df182535234e3436555021c1cbd8119f`.
- B0/B1 publisher:26ccb86, complete suite22 tested packages plus vet/build pass;
  targeted race detector6 packages passed at16b9bbe. The final change requires
  explicit AppID in every loopback owner descriptor. EXE SHA-256
  `1afafd03417b89ae64a95b8292774deaefbaa15bbf933494f9809a6d71e1082f`.
- Actual provider DLL + two hidden publisher fixture passes in loopback-v1,
  with mixed economies and weak native admission at AppID480, and party/mixed
  economies at AppID482. The owned-instruction CommonAddr proof accepts the
  returned document and rejects the wrong identity. All67 bytes are preserved.
  This is synthetic I evidence using C instruction provenance, not game play.
- Windows socket measurement: wildcard source appears as127.0.0.1 at the
  canonical proxy; reply retains proxy IP/port. OS-reserved canonical ports
  cause fail-closed route rejection. An explicit AppID481 fixture encountered
  that refusal; it was not silently remapped.
- B2 bridge: public-API fake-provider and fake-host fixtures cover missing
  DLL/export, strict configuration,
  persona conversion, binary HTTP forwarding and chunked publisher response,
  UDP socket use, separate economy saves, early host exit, abrupt bridge death
  killing host/descendants, and lost publisher readiness while identity remains
  signed in. HTTP cases also cover empty/conflicting framing, HEAD/204/304 and
  large bodyless representation lengths. Final counts are recorded below.
- Actual bridge startup with the final provider DLL and local publisher passed
  in explicit Lab mode. It required the correct Demonware title5760 (not PS4
  asset ID CUSA13795) and the publisher's documented OpenSSL runtime on PATH.
- The unchanged native executable was launched through the bridge and reached
  its title screen using the existing Lab A normal save root. It later exited
  normally with code0. This establishes launch/teardown only, not Online/Join.

### Final B2 verification

- 43 contract assertions and12 integration methods pass. Stateful directory
  fixtures cover delayed discovery, read/search failure cleanup and no game
  launch. Windows bridge SHA-256:
  `70570250c48f1bec87da17546f1ec38427d5e7d1bced25941b7424cf1253ca5f`.
- Actual bridge/provider/two-publisher HTTP fixture passes friends, unknown
  route refusal, owner admission and RSA-PSS response verification, foreign
  owner/malformed refusal, mixed economy isolation and complete teardown.
  This optional fixture used bridge `eceac418749277b80fac64a1f72e52cce31df8a387dae2de377e9603d1f36524`
  before the default-preserving configurable rendering-profile change.
- Live Steam AppID480 `--directory-check` passed on the final bridge: raw
  persona bootstrap, explicit final identity, hidden publisher readiness,
  temporary invisible room creation/read/search/leave. One account only; no
  game, invitations, second peer or WAN transport is implied. The upstream
  Steam API prints identity diagnostics itself, so capture its output privately.

### B3 bounded original-game observation and remaining gate

Both unchanged native games reached their animated title screens. Lab A was
normal; Lab B unlock-all used a separate save/database root inside the existing
Lab B profile. Windows reported A's actual UDP socket as0.0.0.0:3074. B's native
log recorded bind3074 failure with errno48, then a successful Socket1 bind3098;
Windows independently reported0.0.0.0:3098. Thus the game itself selects an
alternate port when3074 is occupied. No host source change is needed to describe
that observed source to the provider. B's private bridge configuration was set
to expected game_port3098 and the provider/publisher readiness probe passed.
This is only bind/readiness evidence, not successful proxy traffic or Join.

The available UI tool's brief Space presses did not move either game beyond
the title screen, including after focus was explicitly restored. The cause is
not established; upstream samples SDL held-key state and the tool exposes no
key-hold duration. No custom input injection or host modification was introduced.
Alt+F4 closed both games normally (exit0), and their bridges/publishers exited.
Online, Pit Stop, local/NP name placement, friend Join, public matchmaking and
race-through-results remain unverified for this architecture. Existing native
fork acceptance must not be transferred to these new builds.

B4 has passed only the one-account Steam directory/identity bootstrap described
above; the in-game name and Online menu remain unverified. B5 is complete as a
written two-PC procedure in TWO_PC.md; two-PC execution is not part of that
written deliverable and has not occurred. Further progress on the game gates
needs reliable game input. No original-game canonical-identity rejection or
architectural need for a native source edit has been demonstrated.
macOS and Linux are not compiled or runtime-qualified in this record.

### 2026-10-19 human retest: Online routing

The pinned host preserves `sdk:` in the HTTP authority, for example
`sdk:userProfile.np.community.playstation.net`. The bridge formerly treated
that colon as a port separator and forwarded the request to publisher auth,
which refused it. The native HTTP adapter now recognizes that explicit marker,
validates the optional port, and dispatches the exact platform suffix to WebAPI.
No host source change or alternate compatibility route was introduced.

51 contract assertions and 12 integration methods pass. An optional actual
provider/two-publisher fixture also passes SDK-authority friends, signed owner
admission, foreign-owner refusal, mixed economies and teardown. The bridge
SHA-256 is `d6c9e9f8c798d1131fdadb07512ac9abde209edf49dab3f1156de91b6cb7c011`.
After installing that executable, the human operator confirmed that Lab A's
Online menu works (H). The remaining B3 gameplay checks are still open.

The second native instance selected port 3104 on this launch, rather than its
previous 3098. A fixed source-port configuration therefore cannot describe the
unchanged host reliably. Endpoint registration must use the owned child's
observed socket before NAT or peer advertisement; this is a separate correction.
The human subsequently confirmed that Pit Stop also opens in Lab A (H).

### Owned game endpoint registration

The bridge now requires `osw_defer_game_endpoint` and submits a single
`game.endpoint.bind` after observing its exact supervised child's IPv4 UDP
socket. Missing, ambiguous, closed or changed sources cannot remain authorized.
The publisher acknowledges the source before NAT discovery or peer operations
are enabled. The manual `network.game_port` key is removed, without a fallback.
The directory diagnostic holds its own reserved loopback UDP socket instead.

Windows: 52 contract assertions and 16 integration methods pass. Additional
standalone platform fixtures verify that an unrelated parent socket is excluded,
wildcard/specific loopback ports are observed, ambiguous/wrong-address sources
are refused, and diagnostic sockets are released. The bridge executable SHA-256
is `71df3ee49fb9e62d017b035a30570533ba6ec5d561703018880b6065d9c468fd`.
The final actual-component HTTP fixture passes SDK-authority friends, signed
admission, foreign/malformed refusal, owned endpoint registration, separate
economies and teardown with these independent components:

- Provider `6d074ee2a071509efd5474c5612f5920e3f3c6e4`, DLL SHA-256
  `ba5b969044b29c7430b03b7e82c98d0015dc48c34371fd3ba2c365697348131d`;
  49/49 component tests pass.
- Publisher `27123aa8070fa0fc8a29e92558eace233a85d459`, executable SHA-256
  `2e1f12d3678683047a9e872448d4a00099493e62a8d2c2ca0a7f291015a90be0`;
  full Go suite, vet and targeted race tests pass.
- Optional two-publisher actual-DLL fixtures pass with AppIDs480 and482,
  pending NAT silence, exact acknowledgement, rebind refusal, preserved
  CommonAddr, bidirectional canonical UDP and peer departure.

These remain fixture results (I). No native source edits were made. Linux and
macOS code was reviewed against OS APIs but was neither compiled nor exercised
on those systems. Join, public matchmaking and race results still require the
human-operated B3 test; B4 in-game checks remain separate.

### Paired human retest and current limitations

With the updated components, both publishers returned canonical NAT endpoints
for the observed original-game sources. A used3074, B initially3129. The bridge
stopped that B session because its source observation was absent or changed;
the combined error category and untraced native socket closes do not establish
which occurred. No explicit native crash marker was captured. At the user's
request, B was relaunched and used3091.

The human then confirmed friend Join reaches a shared lobby (H). Public
matchmaking and a complete race/results still need confirmation. The human
also reported that A does not list B and B's Pit Stop does not work:

- Current HTTP front reads return one reciprocal online friend on both sides.
  The original A game had issued one earlier friend-list GET and received an
  empty list before B was present; B's one GET returned the other player.
  Pinned native HTTP is a pass-through, but its push registration is a stub.
  A new guest GET is needed to update that snapshot. A was subsequently closed
  normally and restarted while B remained present. The native host then received
  the populated250-byte HTTP200 response instead of the earlier53-byte empty
  response. UI visibility still needs human confirmation; no provider/bridge
  code defect was demonstrated by these observations.
- B is the intended unlock-all profile. Its publisher replies with801 inventory
  items (request capacity856) and three currencies, without marketplace errors.
  The human clarified that Pit Stop opens but is empty or indicates everything
  purchased (H). Together with the inventory response, this is consistent with
  expected full ownership in unlock-all mode. It does not demonstrate an economy
  failure and needs no database reset or publisher change.

The final bridge/provider/publisher also passed live single-account Steam480
`--directory-check` with a reserved diagnostic UDP socket and the deferred
registration contract. No game window was launched; B4 name/Online and live
peer transport remain distinct unverified checks.

### Diagnostic follow-up, prepared without interrupting the pair

The endpoint-lifetime error now distinguishes an unobservable registered port
from an observed replacement, recording the old/new port where applicable.
An absent observation is not labelled a proven socket close. Lifecycle stdout
is flushed during redirected runs, so registration is visible before exit.
This changes diagnostics only: source authorization and fail-closed behavior
are unchanged. 52 contract assertions and16 integration methods pass, including
separate absent/changed cases with exact port diagnostics. Candidate SHA-256:
`2f6b2341450a23ddbf7da92be662b9f7a8621067558049df08a55e673af47eeb`.
The active pair retains the earlier installed binary until its next update.
