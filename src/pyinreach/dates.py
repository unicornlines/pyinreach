"""Deterministic date/time conversions for the IPC API.

The API speaks two timestamp dialects:

* **Microsoft JSON dates** -- ``"/Date(1296557000000)/"`` -- used by the
  ``Message`` and ``Binary`` endpoints and by older payloads. The number is a
  signed millisecond count since the Unix epoch in UTC.
* **ISO 8601 with a ``Z`` suffix** -- ``"2024-04-07T21:28:24.968Z"`` -- used by
  the v2 ``Emergency/SendMessage`` and ``Media`` endpoints.

Every function here normalises to timezone-aware UTC :class:`datetime`
instances. Naive datetimes are *assumed* to be UTC (the API is UTC-only); this
choice is explicit and documented rather than left to chance.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

__all__ = [
    "ensure_utc",
    "from_epoch_ms",
    "parse_dotnet_date",
    "parse_iso8601",
    "to_dotnet_date",
    "to_epoch_ms",
    "to_iso8601",
]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_MS = timedelta(milliseconds=1)

# /Date(<signed-ms>[<+|-><HHMM offset>])/  -- the optional offset is a display
# hint only; the millisecond count is already UTC, so we ignore it.
_DOTNET_RE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")


def ensure_utc(value: datetime) -> datetime:
    """Return *value* as a timezone-aware UTC datetime.

    A naive datetime is interpreted as UTC. An aware datetime is converted.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_epoch_ms(value: datetime) -> int:
    """Whole milliseconds since the Unix epoch (UTC), computed exactly."""

    return (ensure_utc(value) - _EPOCH) // _ONE_MS


def from_epoch_ms(milliseconds: int) -> datetime:
    """UTC datetime for a millisecond epoch count, computed exactly."""

    return _EPOCH + timedelta(milliseconds=int(milliseconds))


def to_dotnet_date(value: datetime) -> str:
    """Serialise to the Microsoft JSON date form ``/Date(<ms>)/``."""

    return f"/Date({to_epoch_ms(value)})/"


def parse_dotnet_date(value: str) -> datetime:
    """Parse a Microsoft JSON date string into a UTC datetime.

    Tolerates the JSON-escaped variant ``\\/Date(...)\\/`` by stripping
    backslashes first.
    """

    match = _DOTNET_RE.match(value.replace("\\", "").strip())
    if match is None:
        raise ValueError(f"not a Microsoft JSON date: {value!r}")
    return from_epoch_ms(int(match.group(1)))


def to_iso8601(value: datetime) -> str:
    """Serialise to ISO 8601 with millisecond precision and a ``Z`` suffix."""

    utc = ensure_utc(value)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` or explicit offset) to UTC."""

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"not an ISO 8601 timestamp: {value!r}") from exc
    return ensure_utc(parsed)
