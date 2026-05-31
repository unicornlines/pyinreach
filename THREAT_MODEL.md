# Threat Model / Security Assessment — pyinreach

This document records the security assessment for `pyinreach`. It covers the
library itself and gives deployment guidance for applications that embed it
(e.g. a Django site that lets friends view a location and exchange texts with an
inReach device). It is written so a reviewer can see *what was considered* and
*why each decision was made*, not just the conclusions.

## 1. Scope and assets

`pyinreach` sits on two trust boundaries:

```
                 X-API-Key (secret)                  push + token (secret)
  Your app  ───────────────────────▶  Garmin IPC  ───────────────────────▶  Your web service
 (Inbound client)   HTTPS               gateway          HTTPS POST            (Outbound parser)
```

**Assets to protect**

| Asset | Why it matters |
|---|---|
| IPC Inbound **API key** / Basic credentials | Grants the ability to send paid commands to devices. |
| Outbound **webhook token** / OAuth credential | Authenticates Garmin to your service; a leak lets an attacker forge device events. |
| **Location data & messages** | Personal/safety-sensitive; reveals a person's real-time position. |
| **Device IMEIs** | Identify and address specific hardware. |
| **Account billing** | Every delivered command costs money; abuse is a financial DoS. |

**Adversaries considered:** a network attacker (passive eavesdropper / active
MITM), a malicious or buggy caller of the library, an attacker who can POST to
your public webhook URL, and an attacker who can read your logs or process
memory.

## 2. Trust boundaries and data flow

1. **App → Garmin (Inbound).** Outbound HTTPS requests carry the API key. The
   library controls request construction; the network is untrusted.
2. **Garmin → App (Outbound).** Inbound HTTPS POSTs to a URL you host. The body
   is attacker-influenceable (anyone who learns the URL can POST to it), so it
   is treated as **untrusted input** until the token is verified.

## 3. Threats and mitigations (STRIDE)

### Spoofing
- *Forged webhook calls.* An attacker who discovers your webhook URL can POST
  arbitrary "events." **Mitigation:** `verify_static_token` performs a
  **constant-time** (`hmac.compare_digest`) comparison of the shared token, so
  acceptance cannot be brute-forced via timing. `parse_bearer_token` safely
  extracts the credential. *Deployer action:* require and verify the token on
  every request before trusting the body; serve the webhook over HTTPS only.
- *Server impersonation (MITM).* **Mitigation:** TLS certificate verification is
  **on by default** (`verify=True`) and cannot be disabled by accident. Disabling
  it is possible only via an explicit constructor argument, documented as
  production-unsafe.

### Tampering
- *In-flight modification.* Mitigated by mandatory TLS for both directions.
- *Mutable shared state.* Request/response models are **frozen dataclasses** and
  the parsed event's `raw` view is a read-only `MappingProxyType`, so a parsed
  object cannot be mutated by one consumer and observed changed by another.

### Repudiation
- The library does not itself provide an audit log. *Deployer action:* log the
  IMEI, timestamp and message code of accepted events (but **not** secrets) for
  traceability.

### Information disclosure
- *Credential leakage via logs/tracebacks.* **Mitigation:** `ApiKeyAuth` and
  `BasicAuth` redact secrets in `__repr__` (`api_key='***'`). The library never
  logs request bodies or headers.
- *Sensitive data at rest.* Location and messages are sensitive. *Deployer
  action:* encrypt at rest, restrict access, and apply a retention policy.
- *Error verbosity.* `ResponseError` surfaces the API's own message/IMEIs to the
  caller for debugging; ensure your app does not echo these to untrusted users.

### Denial of service
- *Oversized push payloads.* `parse_events` enforces a configurable
  `max_bytes` ceiling (default 16 MiB, generous enough for v4 media) to bound
  memory; set it lower if your transport does not already cap body size.
- *Algorithmic/parse abuse.* Parsing is plain `json.loads` (no `eval`, no
  regex backtracking on untrusted input) plus linear field extraction — O(n) in
  payload size.
- *Unbounded retries / cost amplification.* The client's retries are **bounded**
  (`max_retries`, default 3) with deterministic, capped back-off; a server
  `Retry-After` is honoured but capped (`retry_after_max`, default 60 s) so a
  hostile/buggy header cannot stall the caller indefinitely.
- *Accidental double-spend.* Non-idempotent POSTs (which send paid commands) are
  **never replayed** on ambiguous failures (read timeouts, 5xx). Only failures
  that prove the request was *not* processed (connection errors) or *not*
  accepted (HTTP 429) are retried. This is the single most important reliability
  decision in the codebase and is enforced in `InboundClient._request`.

### Elevation of privilege
- The library holds no ambient authority; it acts only with the credentials the
  caller supplies. No `eval`/`exec`, no shelling out, no dynamic imports of
  untrusted names.

## 4. Input validation (defense in depth)

All inbound request data is validated locally *before* transmission, mirroring
the server's documented rules (altitude, speed, course, interval, lat/long,
message length incl. reference-point label budget, timestamp window, sender
format, Base64 payload size, IMEI shape, binary/location-type enums). This:

- prevents wasted, costly satellite round-trips on requests the server would
  reject anyway;
- gives deterministic, typed errors (`ValidationError.code` matches the server's
  error code); and
- shrinks the set of values that ever leave the process.

Outbound parsing is **lenient about unknown values** (a new `messageCode` stays
an `int`; unknown fields are preserved in `raw`) but **strict about structure**
(non-conforming payloads raise `ParseError`), so a schema addition by Garmin
cannot crash a receiver, while malformed/hostile input is rejected cleanly.

## 5. Dependencies and supply chain

- Single runtime dependency: `httpx` (a widely used, maintained HTTP client).
  Fewer dependencies means a smaller attack surface.
- No native build steps. Pin/verify versions and enable Dependabot or
  equivalent. Consider hash-pinned installs for production.

## 6. Cryptography

- The library relies on TLS (via `httpx`/the system trust store) for transport
  security and does not roll its own crypto. The only crypto-adjacent primitive
  it uses directly is `hmac.compare_digest` for constant-time token comparison.
- Garmin "encrypted messaging" payloads are passed through opaquely
  (`payload`/`mediaBytes` as Base64); their key management is out of scope.

## 7. Residual risks / explicitly out of scope

- **OAuth/JWT verification** for the outbound webhook is application-specific and
  is not implemented; only the static-token path is provided. If you use OAuth,
  validate the token with your authorization server before calling
  `parse_events`.
- **Secret storage/rotation** is the deployer's responsibility (use a secrets
  manager; rotate the API key — up to three may be active — and the webhook
  token).
- **Authorization of end users** (who in your app may send a text or see a
  location) is out of scope for the library and must be enforced by the app.
- **Replay of captured webhook calls:** a static token does not prevent replay
  of a previously valid request. If replay matters, add a nonce/timestamp check
  or prefer signed/OAuth tokens.

## 8. Deployer checklist

- [ ] Store the API key and webhook token in a secrets manager, not in code.
- [ ] Serve the webhook endpoint over HTTPS only and verify the token on every
      request (constant-time) before trusting the body.
- [ ] Keep `verify=True` (TLS) in production.
- [ ] Return HTTP 200 from the webhook only after durably storing the event.
- [ ] Cap request body size at the web-server layer in addition to `max_bytes`.
- [ ] Encrypt location/message data at rest and set a retention policy.
- [ ] Log IMEI/timestamp/message-code for accepted events — never secrets.
- [ ] Enforce per-user authorization for any inbound (send) action.
- [ ] Monitor billing/usage to detect cost-amplification abuse.
