"""Deterministic, side-effect-free validators for inbound request data.

Each command sent to a device costs money and produces a real-world effect, so
inputs are validated *locally* before anything is transmitted. The rules and
their error codes are copied verbatim from the IPC Inbound guide, which means a
value rejected here is exactly a value the server would have rejected -- only
faster, cheaper and without a wasted satellite round trip.

All validators are pure: given the same input (and, where relevant, the same
``now``) they always raise or return identically. They never perform I/O.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from datetime import datetime, timezone
from numbers import Real

from . import constants as C
from .dates import ensure_utc
from .exceptions import ValidationError

__all__ = [
    "validate_altitude",
    "validate_binary_type",
    "validate_course",
    "validate_imei",
    "validate_imeis",
    "validate_interval",
    "validate_label",
    "validate_latitude",
    "validate_location_type",
    "validate_longitude",
    "validate_message",
    "validate_payload",
    "validate_sender",
    "validate_speed",
    "validate_timestamp",
]

_IMEI_RE = re.compile(r"^\d{15}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{5,15}$")
_PHONE_STRIP_RE = re.compile(r"[\s\-().]")


def _require_number(value: object, field: str, code: C.ErrorCode) -> float:
    """Coerce *value* to a finite real number or raise ``ValidationError``.

    ``bool`` is rejected explicitly: although ``bool`` is a subclass of ``int``
    in Python, accepting ``True``/``False`` as a coordinate or altitude would be
    a silent foot-gun.
    """

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValidationError(f"{field} must be a number, got {value!r}", code=code, field=field)
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValidationError(f"{field} must be finite, got {value!r}", code=code, field=field)
    return number


def validate_imei(imei: str) -> str:
    """Validate a single 15-digit IMEI string. Returns it unchanged."""

    if not isinstance(imei, str) or not _IMEI_RE.match(imei):
        raise ValidationError(
            f"IMEI must be 15 digits, got {imei!r}",
            code=C.ErrorCode.UNKNOWN_DEVICE,
            field="imei",
        )
    return imei


def validate_imeis(imeis: object) -> tuple[str, ...]:
    """Validate a non-empty collection of IMEIs. Returns a tuple."""

    if isinstance(imeis, str) or not hasattr(imeis, "__iter__"):
        raise ValidationError(
            "IMEIs must be a non-string iterable of IMEI strings",
            code=C.ErrorCode.UNKNOWN_DEVICE,
            field="imei",
        )
    result = tuple(validate_imei(i) for i in imeis)
    if not result:
        raise ValidationError(
            "at least one IMEI is required",
            code=C.ErrorCode.UNKNOWN_DEVICE,
            field="imei",
        )
    return result


def validate_altitude(value: object) -> float:
    """Altitude in metres above the WGS84 ellipsoid, ``-1000..18000``."""

    number = _require_number(value, "altitude", C.ErrorCode.INVALID_ALTITUDE)
    if not (C.ALTITUDE_MIN_M <= number <= C.ALTITUDE_MAX_M):
        raise ValidationError(
            f"altitude {number} is invalid, it must be between "
            f"{C.ALTITUDE_MIN_M} and {C.ALTITUDE_MAX_M}",
            code=C.ErrorCode.INVALID_ALTITUDE,
            field="altitude",
        )
    return number


def validate_speed(value: object) -> float:
    """Speed in km/h, ``0..1854``."""

    number = _require_number(value, "speed", C.ErrorCode.INVALID_SPEED)
    if not (C.SPEED_MIN_KMH <= number <= C.SPEED_MAX_KMH):
        raise ValidationError(
            f"speed {number} is invalid, it must be between "
            f"{C.SPEED_MIN_KMH} and {C.SPEED_MAX_KMH} km/h",
            code=C.ErrorCode.INVALID_SPEED,
            field="speed",
        )
    return number


def validate_course(value: object) -> float:
    """Course in degrees from true north, ``-360..360``."""

    number = _require_number(value, "course", C.ErrorCode.INVALID_COURSE)
    if not (C.COURSE_MIN_DEG <= number <= C.COURSE_MAX_DEG):
        raise ValidationError(
            f"course {number} is invalid, it must be between "
            f"{C.COURSE_MIN_DEG} and {C.COURSE_MAX_DEG} degrees",
            code=C.ErrorCode.INVALID_COURSE,
            field="course",
        )
    return number


def validate_interval(value: object) -> int:
    """Tracking interval in whole seconds, ``30..65535``."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"interval must be an integer number of seconds, got {value!r}",
            code=C.ErrorCode.INVALID_INTERVAL,
            field="interval",
        )
    if not (C.INTERVAL_MIN_S <= value <= C.INTERVAL_MAX_S):
        raise ValidationError(
            f"interval {value} is invalid, it must be between "
            f"{C.INTERVAL_MIN_S} and {C.INTERVAL_MAX_S} seconds",
            code=C.ErrorCode.INVALID_INTERVAL,
            field="interval",
        )
    return value


def validate_latitude(value: object) -> float:
    """Latitude in decimal degrees, ``-90..90``."""

    number = _require_number(value, "latitude", C.ErrorCode.INVALID_POSITION)
    if not (C.LATITUDE_MIN <= number <= C.LATITUDE_MAX):
        raise ValidationError(
            f"latitude {number} is invalid, it must be between "
            f"{C.LATITUDE_MIN} and {C.LATITUDE_MAX}",
            code=C.ErrorCode.INVALID_POSITION,
            field="latitude",
        )
    return number


def validate_longitude(value: object) -> float:
    """Longitude in decimal degrees, ``-180..180``."""

    number = _require_number(value, "longitude", C.ErrorCode.INVALID_POSITION)
    if not (C.LONGITUDE_MIN <= number <= C.LONGITUDE_MAX):
        raise ValidationError(
            f"longitude {number} is invalid, it must be between "
            f"{C.LONGITUDE_MIN} and {C.LONGITUDE_MAX}",
            code=C.ErrorCode.INVALID_POSITION,
            field="longitude",
        )
    return number


def validate_location_type(value: object) -> C.LocationType:
    """Location type: ``0`` (reference point) or ``1`` (GPS)."""

    try:
        return C.LocationType(value)  # type: ignore[arg-type]
    except ValueError:
        raise ValidationError(
            f"location type {value!r} is invalid, it must be 0 or 1",
            code=C.ErrorCode.INVALID_LOCATION_TYPE,
            field="location_type",
        ) from None


def validate_binary_type(value: object) -> C.BinaryType:
    """Binary type: ``0`` (encrypted), ``1`` (generic) or ``2`` (enc. pinpoint)."""

    try:
        return C.BinaryType(value)  # type: ignore[arg-type]
    except ValueError:
        raise ValidationError(
            f"binary type {value!r} is invalid, it must be 0, 1 or 2",
            code=C.ErrorCode.INVALID_BINARY_TYPE,
            field="type",
        ) from None


def validate_message(text: object, *, label_len: int = 0) -> str:
    """Message text: non-empty, and ``len(text) + label_len <= 160``.

    Per the spec, a reference-point label shares the 160-character budget with
    the message, hence *label_len*.
    """

    if not isinstance(text, str):
        raise ValidationError(
            f"message must be a string, got {text!r}",
            code=C.ErrorCode.INVALID_MESSAGE,
            field="message",
        )
    if text == "":
        raise ValidationError(
            "message may not be empty",
            code=C.ErrorCode.INVALID_MESSAGE,
            field="message",
        )
    if len(text) + label_len > C.MESSAGE_MAX_LEN:
        raise ValidationError(
            f"message length {len(text)} (+{label_len} label) exceeds the "
            f"{C.MESSAGE_MAX_LEN}-character limit",
            code=C.ErrorCode.INVALID_MESSAGE,
            field="message",
        )
    return text


def validate_label(label: object, *, message_len: int) -> str:
    """Reference-point label: ``len(label) <= 160 - message_len``."""

    if not isinstance(label, str):
        raise ValidationError(
            f"label must be a string, got {label!r}",
            code=C.ErrorCode.INVALID_LABEL,
            field="label",
        )
    if len(label) > C.MESSAGE_MAX_LEN - message_len:
        raise ValidationError(
            f"label length {len(label)} exceeds the remaining "
            f"{C.MESSAGE_MAX_LEN - message_len} characters",
            code=C.ErrorCode.INVALID_LABEL,
            field="label",
        )
    return label


def validate_timestamp(value: datetime, *, now: datetime | None = None) -> datetime:
    """Message timestamp: on/after 2011-01-01 UTC and not in the future.

    *now* is injectable to keep the check deterministic and testable.
    """

    if not isinstance(value, datetime):
        raise ValidationError(
            f"timestamp must be a datetime, got {value!r}",
            code=C.ErrorCode.INVALID_TIMESTAMP,
            field="timestamp",
        )
    moment = ensure_utc(value)
    current = ensure_utc(now) if now is not None else datetime.now(timezone.utc)
    earliest = datetime(C.MIN_TIMESTAMP_YEAR, 1, 1, tzinfo=timezone.utc)
    if moment < earliest:
        raise ValidationError(
            f"timestamp {moment.isoformat()} is invalid, it must be on or "
            f"after {earliest.date().isoformat()}",
            code=C.ErrorCode.INVALID_TIMESTAMP,
            field="timestamp",
        )
    if moment > current:
        raise ValidationError(
            f"timestamp {moment.isoformat()} is invalid, it may not be in the future",
            code=C.ErrorCode.INVALID_TIMESTAMP,
            field="timestamp",
        )
    return moment


def validate_sender(sender: object) -> str:
    """Sender: a valid email address or phone number. Returns it unchanged."""

    if not isinstance(sender, str) or not sender:
        raise ValidationError(
            f"sender must be a non-empty string, got {sender!r}",
            code=C.ErrorCode.INVALID_SENDER,
            field="sender",
        )
    if "@" in sender:
        if _EMAIL_RE.match(sender):
            return sender
    elif _PHONE_RE.match(_PHONE_STRIP_RE.sub("", sender)):
        return sender
    raise ValidationError(
        f"sender {sender!r} is not a valid phone number or email address",
        code=C.ErrorCode.INVALID_SENDER,
        field="sender",
    )


def validate_payload(payload: str) -> bytes:
    """Validate a Base64 payload and return its decoded bytes.

    Enforces strict Base64 and the ``<= 268`` decoded-byte limit.
    """

    if not isinstance(payload, str):
        raise ValidationError(
            f"payload must be a Base64 string, got {payload!r}",
            code=C.ErrorCode.INVALID_PAYLOAD,
            field="payload",
        )
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError(
            "payload contains invalid Base64 characters",
            code=C.ErrorCode.INVALID_PAYLOAD,
            field="payload",
        ) from None
    if len(decoded) > C.BINARY_PAYLOAD_MAX_BYTES:
        raise ValidationError(
            f"payload decodes to {len(decoded)} bytes, the limit is "
            f"{C.BINARY_PAYLOAD_MAX_BYTES}",
            code=C.ErrorCode.INVALID_PAYLOAD,
            field="payload",
        )
    return decoded
