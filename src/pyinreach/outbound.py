"""Parsing for outbound (device -> webhook) event payloads.

Garmin pushes JSON to your web service describing one or more inReach events.
:func:`parse_events` turns that JSON into immutable, typed objects covering
event schema versions 2, 3 and 4. Parsing is deliberately *lenient about values
it does not recognise* (an unknown ``messageCode`` stays an ``int``; a future
field is preserved in ``raw``) but *strict about structure* (a payload that is
not the documented ``{"Version", "Events": [...]}`` shape raises
:class:`~pyinreach.exceptions.ParseError`).

Every object keeps a read-only ``raw`` view of its source mapping, so no data
is ever lost even as Garmin extends the schema.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from numbers import Real
from types import MappingProxyType
from typing import Any

from .constants import GpsFix, MessageCode, TransportMode, is_predefined_message, message_code_name
from .dates import from_epoch_ms
from .exceptions import ParseError

__all__ = ["DEFAULT_MAX_PAYLOAD_BYTES", "Event", "EventBatch", "Point", "Status", "parse_events"]

#: Default ceiling on the raw payload size accepted by :func:`parse_events`.
#: Generous enough for v4 media events; set ``max_bytes=None`` to disable.
DEFAULT_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Point:
    """Location reported with an event. Fields are ``None`` when omitted."""

    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    gps_fix: int | None = None
    course: float | None = None
    speed: float | None = None

    @property
    def gps_fix_enum(self) -> GpsFix | None:
        """The fix as a :class:`GpsFix`, or ``None`` if unknown/absent."""

        if self.gps_fix is None:
            return None
        try:
            return GpsFix(self.gps_fix)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class Status:
    """Device status reported with an event. Fields are ``None`` when omitted."""

    autonomous: int | None = None
    low_battery: int | None = None
    interval_change: int | None = None
    reset_detected: int | None = None

    @property
    def is_autonomous(self) -> bool | None:
        """``True`` if the message originated on the inReach itself."""

        return None if self.autonomous is None else self.autonomous == 1

    @property
    def battery_low(self) -> bool | None:
        """``True`` if the battery is below 25% (``None`` if not reported)."""

        if self.low_battery is None or self.low_battery == 2:
            return None
        return self.low_battery == 1

    @property
    def factory_reset_detected(self) -> bool | None:
        """``True`` if a factory reset was detected on the device."""

        return None if self.reset_detected is None else self.reset_detected == 1


@dataclass(frozen=True, slots=True)
class Event:
    """A single transmission from an inReach device."""

    imei: str
    message_code: int
    free_text: str | None = None
    timestamp_ms: int | None = None
    pingback_received_ms: int | None = None
    pingback_responded_ms: int | None = None
    addresses: tuple[str, ...] = ()
    point: Point | None = None
    status: Status | None = None
    payload: str | None = None
    transport_mode: str | None = None
    media_bytes: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    transcription: str | None = None
    raw: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    # -- derived views -----------------------------------------------------

    @property
    def imeis(self) -> tuple[str, ...]:
        """The IMEI(s); split on commas for multi-device Internet messages."""

        return tuple(part.strip() for part in self.imei.split(",") if part.strip())

    @property
    def message_code_name(self) -> str:
        """Human-readable name for the message code, even if unknown."""

        return message_code_name(self.message_code)

    @property
    def message_code_enum(self) -> MessageCode | None:
        """The code as a :class:`MessageCode`, or ``None`` if not enumerated."""

        try:
            return MessageCode(self.message_code)
        except ValueError:
            return None

    @property
    def is_predefined_message(self) -> bool:
        """``True`` if the code is a tenant pre-defined message (24-63)."""

        return is_predefined_message(self.message_code)

    @property
    def transport_mode_enum(self) -> TransportMode | None:
        """The transport mode as an enum (event schema v3+), or ``None``."""

        if self.transport_mode is None:
            return None
        try:
            return TransportMode(self.transport_mode)
        except ValueError:
            return None

    @property
    def timestamp(self) -> datetime | None:
        """Event creation time as a UTC datetime (``None`` if out of range)."""

        return _safe_from_epoch_ms(self.timestamp_ms)

    @property
    def pingback_received(self) -> datetime | None:
        return _safe_from_epoch_ms(self.pingback_received_ms)

    @property
    def pingback_responded(self) -> datetime | None:
        return _safe_from_epoch_ms(self.pingback_responded_ms)

    def decoded_payload(self) -> bytes | None:
        """Decode the Base64 ``payload`` to bytes (``None`` if absent)."""

        return _decode_b64(self.payload, "payload")

    def decoded_media(self) -> bytes | None:
        """Decode the Base64 ``mediaBytes`` to bytes (``None`` if absent)."""

        return _decode_b64(self.media_bytes, "mediaBytes")


@dataclass(frozen=True, slots=True)
class EventBatch:
    """A parsed push payload: a schema version plus its events."""

    version: str
    events: tuple[Event, ...]
    raw: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, index: int) -> Event:
        return self.events[index]


def parse_events(
    data: str | bytes | bytearray | Mapping[str, Any],
    *,
    max_bytes: int | None = DEFAULT_MAX_PAYLOAD_BYTES,
) -> EventBatch:
    """Parse an outbound push payload into an :class:`EventBatch`.

    Args:
        data: Raw JSON (``str``/``bytes``) or an already-decoded mapping.
        max_bytes: Reject raw input larger than this many bytes/characters to
            bound memory use. Pass ``None`` to disable.

    Raises:
        ParseError: If the payload is not valid JSON or not the documented
            ``{"Version", "Events": [...]}`` structure.
    """

    document = _load(data, max_bytes)
    if not isinstance(document, Mapping):
        raise ParseError(f"payload must be a JSON object, got {type(document).__name__}")
    if "Version" not in document:
        raise ParseError("payload is missing the 'Version' field")
    raw_events = document.get("Events")
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        raise ParseError("payload 'Events' must be a JSON array")

    events = tuple(_parse_event(item, index) for index, item in enumerate(raw_events))
    return EventBatch(
        version=str(document["Version"]),
        events=events,
        raw=MappingProxyType(dict(document)),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load(data: str | bytes | bytearray | Mapping[str, Any], max_bytes: int | None) -> Any:
    if isinstance(data, Mapping):
        return data
    if isinstance(data, (bytes, bytearray)):
        if max_bytes is not None and len(data) > max_bytes:
            raise ParseError(f"payload exceeds {max_bytes} bytes")
        text: str | bytes = bytes(data)
    elif isinstance(data, str):
        if max_bytes is not None and len(data) > max_bytes:
            raise ParseError(f"payload exceeds {max_bytes} characters")
        text = data
    else:
        raise ParseError(f"data must be str, bytes or a mapping, got {type(data).__name__}")
    try:
        return json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"payload is not valid JSON: {exc}") from exc
    except RecursionError:
        # Deeply nested JSON (e.g. "[[[[...") exhausts the decoder's stack.
        # Surface it as a ParseError so a receiver that only guards against
        # ParseError is not crashed by a hostile payload.
        raise ParseError("payload nesting is too deep") from None


def _parse_event(item: Any, index: int) -> Event:
    if not isinstance(item, Mapping):
        raise ParseError(f"Events[{index}] must be a JSON object, got {type(item).__name__}")

    raw_imei = item.get("imei")
    imei = "" if raw_imei is None else str(raw_imei)

    if "messageCode" not in item:
        raise ParseError(f"Events[{index}] is missing 'messageCode'")
    message_code = _coerce_int(item.get("messageCode"), f"Events[{index}].messageCode")

    point = _parse_point(item.get("point"))
    status = _parse_status(item.get("status"))

    return Event(
        imei=imei,
        message_code=message_code,
        free_text=_opt_str(item.get("freeText")),
        timestamp_ms=_coerce_int_opt(item.get("timeStamp")),
        pingback_received_ms=_coerce_int_opt(item.get("pingbackReceived")),
        pingback_responded_ms=_coerce_int_opt(item.get("pingbackResponded")),
        addresses=_parse_addresses(item.get("addresses")),
        point=point,
        status=status,
        payload=_opt_str(item.get("payload")),
        transport_mode=_opt_str(item.get("transportMode")),
        media_bytes=_opt_str(item.get("mediaBytes")),
        media_id=_opt_str(item.get("mediaId")),
        media_type=_opt_str(item.get("mediaType")),
        transcription=_opt_str(item.get("transcription")),
        raw=MappingProxyType(dict(item)),
    )


def _parse_point(value: Any) -> Point | None:
    if not isinstance(value, Mapping):
        return None
    return Point(
        latitude=_coerce_float_opt(value.get("latitude")),
        longitude=_coerce_float_opt(value.get("longitude")),
        altitude=_coerce_float_opt(value.get("altitude")),
        gps_fix=_coerce_int_opt(value.get("gpsFix")),
        course=_coerce_float_opt(value.get("course")),
        speed=_coerce_float_opt(value.get("speed")),
    )


def _parse_status(value: Any) -> Status | None:
    if not isinstance(value, Mapping):
        return None
    return Status(
        autonomous=_coerce_int_opt(value.get("autonomous")),
        low_battery=_coerce_int_opt(value.get("lowBattery")),
        interval_change=_coerce_int_opt(value.get("intervalChange")),
        reset_detected=_coerce_int_opt(value.get("resetDetected")),
    )


def _parse_addresses(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    result: list[str] = []
    for entry in value:
        if isinstance(entry, Mapping):
            address = entry.get("address")
            if address is not None:
                result.append(str(address))
        elif entry is not None:
            result.append(str(entry))
    return tuple(result)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _coerce_int(value: Any, field: str) -> int:
    result = _coerce_int_opt(value)
    if result is None:
        raise ParseError(f"{field} must be an integer, got {_brief(value)}")
    return result


def _coerce_int_opt(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        # Bound the cost of int() on attacker-supplied text: converting a
        # multi-megabyte run of digits is super-linear, and Python < 3.11 has
        # no built-in cap. A legitimate field here is at most ~20 digits.
        if len(stripped) > _MAX_INT_DIGITS:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _coerce_float_opt(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        number = float(value)
        return number if not (math.isnan(number) or math.isinf(number)) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if not (math.isnan(number) or math.isinf(number)) else None
    return None


def _decode_b64(value: str | None, field: str) -> bytes | None:
    if value is None:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ParseError(f"{field} is not valid Base64: {exc}") from exc


def _safe_from_epoch_ms(milliseconds: int | None) -> datetime | None:
    """Convert an epoch-ms value to UTC, or ``None`` if it is out of range.

    A hostile or buggy payload can carry a millisecond count outside the range
    a :class:`datetime` can represent. Returning ``None`` keeps reading a
    derived timestamp from untrusted input from raising ``OverflowError`` in a
    consumer's request handler.
    """

    if milliseconds is None:
        return None
    try:
        return from_epoch_ms(milliseconds)
    except (OverflowError, ValueError, OSError):
        return None


#: Maximum digit count accepted when coercing a numeric *string* to an int.
#: Mirrors CPython's own default ``int``-string limit so behaviour is uniform
#: across supported versions and the conversion stays cheap.
_MAX_INT_DIGITS = 4300


def _brief(value: object, limit: int = 80) -> str:
    """``repr(value)`` truncated, so a huge hostile value can't bloat a message."""

    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}... ({len(text)} chars)"
