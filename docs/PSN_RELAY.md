# Local PSN relay, version 1

This is a private host-to-bridge transport binding. It is not a Sony endpoint or
an emulation of Sony's network protocol. PSN notification names and payloads
come from orbiSteamworks' public PSN events API; the relay does not translate
Steam callbacks or interpret game packets.

The opt-in OCTR adapter receives `BB_PSN_BACKEND_CONFIG` as UTF-8 JSON:

```json
{"url":"http://127.0.0.2:31380","token":"<64 lowercase hexadecimal characters>"}
```

The bridge generates 256 random bits per supervised launch, inherits this only
into its child process tree, never writes it to disk, and listens on loopback.
Every request requires `Authorization: Bearer <token>`. Browser-origin requests
are rejected; no CORS, redirects, proxies, remote URL or unauthenticated
notification access is part of this contract. Local processes with access to
the user's process environment are within the same trust boundary.

There is one consumer and one fixed account per supervised session. A new game
session requires a new bridge session; an account change is a failure, not a
silent rebind. HTTP failures have fixed-category JSON errors without credentials
or provider payloads. Responses use `Cache-Control: no-store`.

## Operations

| Request | Response |
|---|---|
| `GET /psn/v1/info` | `version:1`, decimal-string `accountId`, `onlineId`, `signedIn`, and `capabilities` |
| `POST /psn/v1/token` | `status` (OSW result), `issuerId:256`, `token` |
| `POST /psn/v1/webapi` | `status` (OSW result), `httpStatus`, `contentType`, `bodyHex` |
| `GET /psn/v1/events?after=N` | `version:1`, `events:[{sequence,event}]` |

The required capabilities are `identity`, `id-token`, `webapi`, `push` and
`invitation-accepted`. Unknown versions/capabilities are not assumed compatible.
Account IDs are always decimal strings; sequence numbers are unsigned integers.

Token input is `{kind:1,client_id,scope}`. It delegates `OSW_TOKEN` to the current
provider/companion context. `issuerId` is the local adapter's value, not an assertion
of Sony issuance. Authorization codes are unsupported. Tokens are bounded to
4096 bytes and returned only after successful completion.

WebAPI input contains `method` (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`),
`api_group`, `path` including the original query, `content_type`, `headers` as an
object and `bodyHex`. Bodies are binary encoded as lowercase hexadecimal,
bounded to 256 KiB in either direction. Metadata is bounded to 64 KiB, headers
to 64, and each HTTP request to 1 MiB. Header names are case-insensitive;
duplicates must be rejected rather than collapsed. All processing goes through
`OSW_WEBAPI`; arbitrary URLs cannot be forwarded. The existing provider returns
content type, HTTP status and body, not arbitrary response headers.

The host's adapter owns asynchronous operation handles, cancellation, buffers
and guest error conversion. These HTTP calls finish a single provider request;
they do not hold guest callback or registry locks. A transport failure after a
mutating request has an unknown outcome: never automatically retry token or
WebAPI operations. Only event reads have the replay guarantee below.

## Notification delivery

`event` is the unmodified version-1 JSON object copied from
`osw_poll_psn_event`. The bridge assigns a monotonically increasing `sequence`,
starting at 1. The first read uses `after=0`. The host copies and validates each
batch before advancing its cursor. The next read acknowledges the last sequence
it retained. Repeating the same cursor returns all still-unacknowledged events;
the host must not enqueue a sequence twice. New events can be appended between
retries. This prevents a lost HTTP response from consuming an invitation.

Reads return at most 64 events and acknowledge only a sequence previously
offered by this session. An obsolete or future cursor returns HTTP 409. At most
512 unacknowledged events are retained. Overflow, malformed provider envelopes
or provider stream loss latch HTTP 503 for the notification stream. The host
must fail explicitly and require a fresh session, never silently discard an
accepted invitation or invent a replacement presence event.

Push filters and subscriptions stay in the host adapter. The relay does not
contain guest pointers, callback IDs or PS4 memory layouts. Invitation receipt,
acceptance and committed game membership are distinct provider events/actions;
the relay cannot convert one into another.
