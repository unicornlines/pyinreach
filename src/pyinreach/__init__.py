"""pyinreach -- a typed Python client for the Garmin inReach IPC API.

This package implements both halves of the Garmin inReach Portal Connect (IPC)
interface:

* **Inbound** (client -> device): :class:`InboundClient` sends text, binary and
  media messages, requests locations, controls tracking and handles emergencies.
* **Outbound** (device -> your web service): :func:`parse_events` decodes the
  JSON Garmin pushes to your webhook, and :mod:`pyinreach.webhook` helps you
  authenticate those requests.

The library is framework-agnostic; see the README for Django integration notes.

Note: this is an unofficial, community-maintained client and is not affiliated
with or endorsed by Garmin Ltd.
"""

from __future__ import annotations

from ._version import __version__
from .auth import ApiKeyAuth, BasicAuth
from .constants import (
    BinaryType,
    ErrorCode,
    GpsFix,
    LocationType,
    LowBattery,
    MessageCode,
    TransportMode,
    is_predefined_message,
    message_code_name,
)
from .dates import (
    from_epoch_ms,
    parse_dotnet_date,
    parse_iso8601,
    to_dotnet_date,
    to_epoch_ms,
    to_iso8601,
)
from .exceptions import (
    AuthenticationError,
    ConfigurationError,
    ParseError,
    PyInreachError,
    RateLimitError,
    ResponseError,
    ServerError,
    TransportError,
    UnprocessableError,
    ValidationError,
)
from .inbound import DEFAULT_BASE_URL, InboundClient
from .models import (
    BinaryMessage,
    Coordinate,
    MediaMessage,
    Message,
    ReferencePoint,
    TrackingDevice,
    build_data_url,
)
from .outbound import Event, EventBatch, Point, Status, parse_events
from .webhook import parse_bearer_token, verify_static_token

__all__ = [  # noqa: RUF022 - grouped by concern for readability, not sorted
    "__version__",
    # client
    "InboundClient",
    "DEFAULT_BASE_URL",
    # auth
    "ApiKeyAuth",
    "BasicAuth",
    # request models
    "Coordinate",
    "ReferencePoint",
    "Message",
    "BinaryMessage",
    "MediaMessage",
    "TrackingDevice",
    "build_data_url",
    # outbound parsing
    "parse_events",
    "EventBatch",
    "Event",
    "Point",
    "Status",
    # webhook auth
    "verify_static_token",
    "parse_bearer_token",
    # enums / constants
    "MessageCode",
    "GpsFix",
    "LowBattery",
    "TransportMode",
    "BinaryType",
    "LocationType",
    "ErrorCode",
    "is_predefined_message",
    "message_code_name",
    # date helpers
    "to_dotnet_date",
    "parse_dotnet_date",
    "to_iso8601",
    "parse_iso8601",
    "to_epoch_ms",
    "from_epoch_ms",
    # exceptions
    "PyInreachError",
    "ConfigurationError",
    "ValidationError",
    "TransportError",
    "ParseError",
    "ResponseError",
    "AuthenticationError",
    "RateLimitError",
    "UnprocessableError",
    "ServerError",
]
