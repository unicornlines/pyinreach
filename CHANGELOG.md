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
