"""Immutable request models for the inbound (client -> device) API.

Every model validates its inputs on construction, so an invalid object simply
cannot exist. Models are frozen (hashable, thread-safe to share) and expose
``to_*_dict`` methods that emit the precise JSON shapes documented for each
endpoint -- including the quirks (some numbers are serialised as strings, the
``Media`` endpoint takes a comma-joined recipients string, ...).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import validation as V
from .constants import BinaryType, ErrorCode, LocationType
from .dates import to_dotnet_date, to_iso8601
from .exceptions import ValidationError

__all__ = [
    "MEDIA_MAX_BYTES",
    "BinaryMessage",
    "Coordinate",
    "MediaMessage",
    "Message",
    "ReferencePoint",
    "TrackingDevice",
    "build_data_url",
]

#: Generous local sanity ceiling on the *decoded* size of a media payload, used
#: to reject an accidental huge blob before it is encoded and transmitted. This
#: is a client-side guard, not Garmin's authoritative media limit (which is
#: undocumented here and far smaller over satellite); it only catches gross
#: misuse. Matches the outbound parser's default payload ceiling for symmetry.
MEDIA_MAX_BYTES = 16 * 1024 * 1024

#: Maximum Base64 length corresponding to ``MEDIA_MAX_BYTES`` decoded bytes
#: (Base64 encodes 3 bytes as 4 characters). Checking the encoded length lets us
#: reject an oversized payload *before* decoding it.
_MEDIA_B64_MAX_LEN = 4 * ((MEDIA_MAX_BYTES + 2) // 3)

#: An RFC 6838 ``type/subtype`` token (no parameters), used to validate a MIME
#: type before it is placed in a ``data:`` URL.
_MIME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z")


def _num_to_str(value: float) -> str:
    """Render a number the way the API's reference-point fields expect.

    Integral floats become plain integers (``20.0 -> "20"``) to match the
    documented examples; genuine fractions are preserved (``22.5 -> "22.5"``).
    """

    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 latitude/longitude pair in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "latitude", V.validate_latitude(self.latitude))
        object.__setattr__(self, "longitude", V.validate_longitude(self.longitude))

    def to_dict(self) -> dict[str, float]:
        return {"Latitude": self.latitude, "Longitude": self.longitude}


@dataclass(frozen=True, slots=True)
class ReferencePoint:
    """A location attached to a text message.

    ``location_type`` distinguishes a manually placed reference point from a
    live GPS fix. ``label`` shares the 160-character budget with the message it
    accompanies (validated by :class:`Message`).
    """

    coordinate: Coordinate
    location_type: LocationType = LocationType.GPS
    altitude: float = 0.0
    speed: float = 0.0
    course: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.coordinate, Coordinate):
            raise ValidationError(
                "coordinate must be a Coordinate instance",
                code=ErrorCode.INVALID_POSITION,
                field="coordinate",
            )
        object.__setattr__(self, "location_type", V.validate_location_type(self.location_type))
        object.__setattr__(self, "altitude", V.validate_altitude(self.altitude))
        object.__setattr__(self, "speed", V.validate_speed(self.speed))
        object.__setattr__(self, "course", V.validate_course(self.course))
        if not isinstance(self.label, str):
            raise ValidationError(
                "label must be a string",
                code=ErrorCode.INVALID_LABEL,
                field="label",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "LocationType": str(int(self.location_type)),
            "Altitude": _num_to_str(self.altitude),
            "Speed": _num_to_str(self.speed),
            "Course": _num_to_str(self.course),
            "Coordinate": self.coordinate.to_dict(),
            "Label": self.label,
        }


@dataclass(frozen=True, slots=True)
class Message:
    """A text message bound for one or more devices.

    *timestamp* defaults to "now" at serialisation time. A non-empty reference
    point label is counted against the 160-character message limit.
    """

    recipients: tuple[str, ...]
    sender: str
    text: str
    timestamp: datetime | None = None
    reference_point: ReferencePoint | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipients", V.validate_imeis(self.recipients))
        object.__setattr__(self, "sender", V.validate_sender(self.sender))
        label_len = (
            len(self.reference_point.label)
            if self.reference_point is not None and self.reference_point.label
            else 0
        )
        object.__setattr__(self, "text", V.validate_message(self.text, label_len=label_len))
        if self.reference_point is not None and self.reference_point.label:
            V.validate_label(self.reference_point.label, message_len=len(self.text))
        if self.timestamp is not None:
            V.validate_timestamp(self.timestamp)

    def to_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = self.timestamp if self.timestamp is not None else (now or _utcnow())
        payload: dict[str, Any] = {
            "Recipients": list(self.recipients),
            "Sender": self.sender,
            "Timestamp": to_dotnet_date(moment),
            "Message": self.text,
        }
        if self.reference_point is not None:
            payload["ReferencePoint"] = self.reference_point.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class BinaryMessage:
    """A binary message bound for one or more devices.

    *payload* may be raw ``bytes`` (Base64-encoded for you) or an existing
    Base64 string. Either way it must decode to at most 268 bytes.
    """

    recipients: tuple[str, ...]
    payload: str | bytes
    type: BinaryType = BinaryType.GENERIC

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipients", V.validate_imeis(self.recipients))
        object.__setattr__(self, "type", V.validate_binary_type(self.type))
        payload = self.payload
        if isinstance(payload, (bytes, bytearray)):
            payload = base64.b64encode(bytes(payload)).decode("ascii")
            object.__setattr__(self, "payload", payload)
        V.validate_payload(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "Recipients": list(self.recipients),
            "Type": int(self.type),
            "Payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class MediaMessage:
    """A media (image/audio) message bound for one or more devices.

    *media* is a ``data:`` URL (see :func:`build_data_url`). The ``Media``
    endpoint, unlike the others, encodes recipients as a comma-joined string.
    """

    recipients: tuple[str, ...]
    sender: str
    text: str
    media: str
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipients", V.validate_imeis(self.recipients))
        object.__setattr__(self, "sender", V.validate_sender(self.sender))
        object.__setattr__(self, "text", V.validate_message(self.text))
        _validate_data_url(self.media)
        if self.timestamp is not None:
            V.validate_timestamp(self.timestamp)

    def to_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = self.timestamp if self.timestamp is not None else (now or _utcnow())
        return {
            "Recipients": ",".join(self.recipients),
            "Sender": self.sender,
            "Message": self.text,
            "Timestamp": to_iso8601(moment),
            "Media": self.media,
        }

    @classmethod
    def from_bytes(
        cls,
        recipients: Iterable[str],
        sender: str,
        text: str,
        data: bytes,
        mime_type: str,
        *,
        timestamp: datetime | None = None,
    ) -> MediaMessage:
        """Build a media message from raw bytes and a MIME type."""

        return cls(
            recipients=tuple(recipients),
            sender=sender,
            text=text,
            media=build_data_url(data, mime_type),
            timestamp=timestamp,
        )


@dataclass(frozen=True, slots=True)
class TrackingDevice:
    """A device whose tracking state and/or interval is being changed.

    Used by both the tracking on/off endpoint and the interval endpoint; the
    relevant serialiser validates that the fields it needs are present.
    """

    imei: str
    tracking: bool | None = None
    interval: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "imei", V.validate_imei(self.imei))
        if self.tracking is not None and not isinstance(self.tracking, bool):
            raise ValidationError(
                "tracking must be a bool or None",
                code=ErrorCode.INTERNAL,
                field="tracking",
            )
        if self.interval is not None:
            object.__setattr__(self, "interval", V.validate_interval(self.interval))

    def to_tracking_dict(self) -> dict[str, Any]:
        if self.tracking is None:
            raise ValidationError(
                "tracking must be set to enable/disable tracking",
                code=ErrorCode.INTERNAL,
                field="tracking",
            )
        body: dict[str, Any] = {"Imei": self.imei, "Tracking": self.tracking}
        if self.interval is not None:
            body["Interval"] = self.interval
        return body

    def to_interval_dict(self) -> dict[str, Any]:
        if self.interval is None:
            raise ValidationError(
                "interval must be set to change the tracking interval",
                code=ErrorCode.INVALID_INTERVAL,
                field="interval",
            )
        return {"Imei": self.imei, "Interval": self.interval}


def build_data_url(data: bytes, mime_type: str) -> str:
    """Build a ``data:<mime>;base64,<payload>`` URL from raw bytes."""

    if not isinstance(data, (bytes, bytearray)):
        raise ValidationError(
            "data must be bytes",
            code=ErrorCode.INVALID_PAYLOAD,
            field="media",
        )
    if not isinstance(mime_type, str) or not _MIME_RE.match(mime_type):
        raise ValidationError(
            f"mime_type must look like 'type/subtype', got {mime_type!r}",
            code=ErrorCode.INVALID_PAYLOAD,
            field="media",
        )
    encoded = base64.b64encode(bytes(data)).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _validate_data_url(media: object) -> None:
    if not isinstance(media, str) or not media.startswith("data:") or ";base64," not in media:
        raise ValidationError(
            "media must be a 'data:<mime>;base64,<payload>' URL",
            code=ErrorCode.INVALID_PAYLOAD,
            field="media",
        )
    b64 = media.split(";base64,", 1)[1]
    # Size-gate on the encoded length before decoding, so a hostile or accidental
    # multi-gigabyte payload is rejected without first materialising its bytes.
    if len(b64) > _MEDIA_B64_MAX_LEN:
        raise ValidationError(
            f"media payload exceeds the {MEDIA_MAX_BYTES}-byte limit",
            code=ErrorCode.INVALID_PAYLOAD,
            field="media",
        )
    try:
        base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError(
            "media payload contains invalid Base64 characters",
            code=ErrorCode.INVALID_PAYLOAD,
            field="media",
        ) from None


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
