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

B3 original-game pair, B4 live single-account game and B5 two-PC execution are
not accepted by the fixtures above. The two-PC procedure is supplied separately.
macOS and Linux are not compiled or runtime-qualified in this record.
