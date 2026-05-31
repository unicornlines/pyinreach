"""Enumerations and fixed limits defined by the Garmin IPC API.

Every value in this module is taken directly from the *Developer Guide for IPC
Inbound* (v3.1.1) and *Developer Guide for IPC Outbound* (v2.0.9). Keeping them
in one place means validation, serialisation and parsing all agree on the same
authoritative numbers.
"""

from __future__ import annotations

from enum import Enum, IntEnum

# ---------------------------------------------------------------------------
# Device / message limits (IPC Inbound -- "Device Limits" and validation rules)
# ---------------------------------------------------------------------------

#: Inclusive bounds for altitude, in metres above the WGS84 ellipsoid.
ALTITUDE_MIN_M = -1000
ALTITUDE_MAX_M = 18000

#: Inclusive bounds for speed, in kilometres per hour.
SPEED_MIN_KMH = 0
SPEED_MAX_KMH = 1854

#: Inclusive bounds for course, expressed as degrees offset from true north.
COURSE_MIN_DEG = -360
COURSE_MAX_DEG = 360

#: Inclusive bounds for the tracking interval, in seconds.
INTERVAL_MIN_S = 30
INTERVAL_MAX_S = 65535

#: Inclusive bounds for a WGS84 coordinate, in decimal degrees.
LATITUDE_MIN = -90.0
LATITUDE_MAX = 90.0
LONGITUDE_MIN = -180.0
LONGITUDE_MAX = 180.0

#: Maximum combined length of a text message (and, when present, the reference
#: point label counts towards this same budget).
MESSAGE_MAX_LEN = 160

#: A binary payload must be Base64 and decode to at most this many bytes.
BINARY_PAYLOAD_MAX_BYTES = 268

#: The earliest timestamp the API will accept for an outbound message.
#: Stored as a naive ``date`` tuple to avoid importing datetime here.
MIN_TIMESTAMP_YEAR = 2011


# ---------------------------------------------------------------------------
# Inbound request enumerations
# ---------------------------------------------------------------------------


class LocationType(IntEnum):
    """Type of location attached to a reference point."""

    REFERENCE_POINT = 0
    GPS = 1


class BinaryType(IntEnum):
    """Type discriminator for a binary message payload."""

    ENCRYPTED = 0
    GENERIC = 1
    ENCRYPTED_PINPOINT = 2


# ---------------------------------------------------------------------------
# Outbound event enumerations
# ---------------------------------------------------------------------------


class GpsFix(IntEnum):
    """Quality of the GPS fix reported in an outbound ``point``."""

    NONE = 0
    FIX_2D = 1
    FIX_3D = 2
    FIX_3D_PLUS = 3


class LowBattery(IntEnum):
    """Battery status reported in an outbound ``status`` object."""

    OK = 0
    LOW = 1  # below 25%
    NOT_REPORTED = 2


class TransportMode(str, Enum):
    """How an outbound message reached the gateway (event schema v3+)."""

    SATELLITE = "Satellite"
    INTERNET = "Internet"


#: Inclusive range of message codes reserved for tenant pre-defined messages.
PREDEFINED_MESSAGE_RANGE = range(24, 64)  # 24..63 inclusive


class MessageCode(IntEnum):
    """Outbound message codes (IPC Outbound "Message Codes Table").

    Codes in the 24-63 range are tenant pre-defined messages and are *not*
    enumerated individually; use :func:`is_predefined_message` for those.
    Unknown codes are preserved as plain integers when parsing events, so a
    future code added by Garmin will never raise.
    """

    POSITION_REPORT = 0
    RESERVED_1 = 1
    LOCATE_RESPONSE = 2
    FREE_TEXT = 3
    DECLARE_SOS = 4
    RESERVED_5 = 5
    CONFIRM_SOS = 6
    CANCEL_SOS = 7
    REFERENCE_POINT = 8
    START_TRACK = 10
    TRACK_INTERVAL = 11
    STOP_TRACK = 12
    UNKNOWN_INDEX = 13
    PUCK_MESSAGE_1 = 14
    PUCK_MESSAGE_2 = 15
    PUCK_MESSAGE_3 = 16
    MAP_SHARE = 17
    MAIL_CHECK = 20
    AM_I_ALIVE = 21
    ENCRYPTED_BINARY = 64
    PINGBACK = 65
    GENERIC_BINARY = 66
    ENCRYPTED_PINPOINT = 67
    ENCRYPTION_NEGOTIATION = 68  # event schema v4+
    ENCRYPTION_NACK = 69
    CANNED_MESSAGE = 3099  # event schema v4+


def is_predefined_message(code: int) -> bool:
    """Return ``True`` if *code* is in the tenant pre-defined message range."""

    return code in PREDEFINED_MESSAGE_RANGE


def message_code_name(code: int) -> str:
    """Human-readable name for a message *code*, even when unknown."""

    try:
        return MessageCode(code).name
    except ValueError:
        if is_predefined_message(code):
            return "PREDEFINED_MESSAGE"
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Error codes (IPC Inbound "Error Codes" table)
# ---------------------------------------------------------------------------


class ErrorCode(IntEnum):
    """Numeric error codes returned in the JSON error object."""

    INTERNAL = 1
    TOO_MANY_REQUESTS = 2
    AUTHENTICATION = 3
    UNKNOWN_DEVICE = 4
    INVALID_MESSAGE = 5
    INVALID_TIMESTAMP = 6
    INVALID_SENDER = 7
    INVALID_ALTITUDE = 8
    INVALID_SPEED = 9
    INVALID_COURSE = 10
    INVALID_POSITION = 11
    INVALID_INTERVAL = 12
    INVALID_LOCATION_TYPE = 13
    INVALID_LABEL = 14
    ILLEGAL_EMERGENCY_ACTION = 15
    INVALID_BINARY_TYPE = 16
    INVALID_PAYLOAD = 17
