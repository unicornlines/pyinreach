# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- The `Event` and `EventBatch` `raw` fields used a `MappingProxyType` default,
  which Python 3.11 rejects as a mutable dataclass default (the type is
  unhashable there), making the package fail to import on 3.11. They now use a
  `default_factory`, so import works across 3.10-3.13.
- `request_location` is a GET but triggers a *paid* locate command, so it is no
  longer treated as a side-effect-free GET: it is never replayed after an
  ambiguous failure (read timeout or 5xx), closing a double-spend gap. It is
  still retried after a connection error, which proves the command was not sent.
- A server `Retry-After` header in the RFC 7231 *HTTP-date* form (e.g.
  `Retry-After: Wed, 21 Oct 2025 07:28:00 GMT`) is now honoured instead of being
  silently ignored in favour of exponential back-off; a fractional second count
  is also accepted. Non-finite or unparseable hints still fall back to the
  client's own bounded back-off.

### Changed
- `parse_events` no longer makes a redundant defensive copy of a payload it
  decoded itself from `str`/`bytes` (it wraps the privately-owned tree in
  read-only views directly), trimming container overhead for large payloads. A
  caller-supplied mapping is still copied so later external mutation cannot be
  observed through the parsed views.

### Security
- `parse_dotnet_date` now bounds the digit count it will convert to an `int`,
  mirroring the cap already applied in outbound parsing, so a hostile
  `/Date(99999...)/` string cannot trigger a super-linear `int()` conversion on
  Python < 3.11 (which has no built-in cap).
- `MediaMessage` now enforces a generous local size ceiling (`MEDIA_MAX_BYTES`,
  16 MiB) on the decoded media payload and rejects an oversized blob *before*
  decoding it, so an accidental or hostile multi-gigabyte payload fails fast
  without being materialised. This is a client-side guard, not Garmin's
  authoritative media limit.
- `build_data_url` now validates the MIME type against an RFC 6838
  `type/subtype` token (anchored with `\A`/`\Z` so a trailing newline is
  rejected) rather than only checking for a `/`.

### Security
- `parse_events` now raises `ParseError` (instead of leaking an uncaught
  `RecursionError`) on deeply nested JSON, so a hostile webhook body cannot
  crash a receiver that only guards `ParseError`.
- Reading `Event.timestamp` / `pingback_received` / `pingback_responded` from an
  out-of-range epoch value now returns `None` instead of raising `OverflowError`
  in the consumer's request handler.
- Coercing a numeric *string* to an `int` during outbound parsing is now bounded
  in length, preventing a super-linear `int()` conversion on a multi-megabyte
  digit run (Python < 3.11 has no built-in cap). Oversized values are also
  truncated in parse-error messages to avoid log amplification.
- `InboundClient` now refuses a non-`https://` `base_url` while TLS verification
  is enabled, so the API key cannot be sent in plaintext via a stray scheme.
  Pass `verify=False` to opt out for local, non-production testing.

## [0.1.0]

Initial release.

### Added
- `InboundClient` covering the IPC Inbound v2 API:
  - Messaging: `send_message`, `send_messages`, `send_binary`, `send_binaries`,
    `send_media`.
  - Location: `request_location`, `last_known_location`, `send_location_request`,
    `location_history`.
  - Tracking: `set_tracking`, `set_interval`, and `enable_tracking` /
    `disable_tracking` / `set_device_interval` helpers.
  - Emergency: `get_respondent`, `get_emergency_state`, `acknowledge_emergency`,
    `send_emergency_message`.
- Authentication strategies `ApiKeyAuth` (X-API-Key) and `BasicAuth`, with
  credential redaction.
- Immutable request models: `Coordinate`, `ReferencePoint`, `Message`,
  `BinaryMessage`, `MediaMessage`, `TrackingDevice`, plus `build_data_url`.
- Outbound event parsing (`parse_events`) for event schema v2/v3/v4, with
  `EventBatch`, `Event`, `Point`, `Status` and lossless `raw` views.
- Webhook authentication helpers: `verify_static_token` (constant-time) and
  `parse_bearer_token`.
- Deterministic UTC date helpers for the Microsoft JSON and ISO 8601 formats.
- Deterministic local validators mirroring the server-side rules.
- Safe, bounded retry policy that never replays non-idempotent POSTs on
  ambiguous failures.
- Full type hints (`py.typed`), test suite, and a threat assessment.
