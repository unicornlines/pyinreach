# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
