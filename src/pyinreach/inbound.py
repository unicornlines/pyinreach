"""The inbound (client -> device) HTTP client.

:class:`InboundClient` is a thin, explicit wrapper over an :class:`httpx.Client`
that implements every documented IPC Inbound v2 operation:

* **Messaging** -- text, binary and media messages.
* **Location** -- live location requests, last-known location, history.
* **Tracking** -- enable/disable and interval changes.
* **Emergency** -- respondent flag, state, SOS acknowledgement, SOS messaging.

Design priorities, in order: *secure* (TLS verified by default, credentials
redacted, inputs validated before transmission), *reliable* (bounded, explicit
retries that never silently re-send a money-spending command), *deterministic*
(no hidden randomness; an injectable ``sleep`` makes back-off testable) and
*efficient* (a single pooled, keep-alive connection reused across calls).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

import httpx

from ._version import __version__
from .auth import ApiKeyAuth, BasicAuth
from .constants import BinaryType
from .dates import to_iso8601
from .exceptions import ParseError, TransportError, response_error_for
from .models import BinaryMessage, MediaMessage, Message, ReferencePoint, TrackingDevice
from .validation import validate_imei, validate_imeis, validate_message, validate_timestamp

__all__ = ["InboundClient"]

#: Default IPC Inbound v2 host. Override with your tenant's inbound URL.
DEFAULT_BASE_URL = "https://ipcinbound.inreachapp.com"

# Endpoint paths. Resource names are taken from the error-object URLs in the
# guide (which are authoritative), e.g. ".../api/Messaging/Message".
_PATH_MESSAGE = "/api/Messaging/Message"
_PATH_BINARY = "/api/Messaging/Binary"
_PATH_MEDIA = "/api/Messaging/Media"
_PATH_LOC_REQUEST = "/api/Location/LocationRequest"
_PATH_LOC_LAST = "/api/Location/LastKnownLocation"
_PATH_LOC_SEND = "/api/Location/SendLocationRequest"
_PATH_LOC_HISTORY = "/api/Location/History"
_PATH_TRACK = "/api/Tracking/Tracking"
_PATH_INTERVAL = "/api/Tracking/Interval"
_PATH_EMER_RESPONDENT = "/api/Emergency/Respondent"
_PATH_EMER_STATE = "/api/Emergency/State"
_PATH_EMER_ACK = "/api/Emergency/AcknowledgeDeclareEmergency"
_PATH_EMER_SEND = "/api/Emergency/SendMessage"

# Status codes for which a *GET* (idempotent) may safely be retried.
_RETRYABLE_GET_STATUS = frozenset({500, 502, 503, 504})


class InboundClient:
    """Synchronous client for the IPC Inbound v2 API.

    Args:
        auth: An :class:`~pyinreach.auth.ApiKeyAuth` (recommended) or
            :class:`~pyinreach.auth.BasicAuth` instance.
        base_url: Tenant inbound base URL; defaults to the public v2 host.
        timeout: Per-request timeout in seconds, or an :class:`httpx.Timeout`.
        max_retries: Maximum *additional* attempts after the first.
        backoff_factor: Base seconds for exponential back-off (no jitter, so
            back-off is deterministic).
        backoff_max: Upper bound for a single back-off sleep.
        retry_after_max: Cap applied to a server ``Retry-After`` hint.
        verify: TLS verification. Leave ``True`` in production.
        transport: Optional :class:`httpx.BaseTransport` (used in tests).
        sleep: Injectable sleep function (used in tests); defaults to
            :func:`time.sleep`.
    """

    def __init__(
        self,
        *,
        auth: ApiKeyAuth | BasicAuth | httpx.Auth,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float | httpx.Timeout = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        backoff_max: float = 8.0,
        retry_after_max: float = 60.0,
        verify: bool = True,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._backoff_max = backoff_max
        self._retry_after_max = retry_after_max
        self._sleep = sleep
        self._client = httpx.Client(
            auth=auth,
            timeout=timeout,
            verify=verify,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": f"pyinreach/{__version__}",
            },
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection pool."""

        self._client.close()

    def __enter__(self) -> InboundClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"InboundClient(base_url={self._base_url!r})"

    # -- messaging ---------------------------------------------------------

    def send_message(
        self,
        recipients: Iterable[str],
        sender: str,
        text: str,
        *,
        timestamp: datetime | None = None,
        reference_point: ReferencePoint | None = None,
        now: datetime | None = None,
    ) -> int:
        """Send one text message; returns the number of messages delivered."""

        message = Message(
            recipients=tuple(recipients),
            sender=sender,
            text=text,
            timestamp=timestamp,
            reference_point=reference_point,
        )
        return self.send_messages([message], now=now)

    def send_messages(self, messages: Sequence[Message], *, now: datetime | None = None) -> int:
        """Send a batch of pre-built :class:`Message` objects; returns count."""

        if not messages:
            raise ValueError("messages must not be empty")
        body = {"Messages": [m.to_dict(now=now) for m in messages]}
        response = self._request("POST", _PATH_MESSAGE, json=body)
        return self._count(response)

    def send_binary(
        self,
        recipients: Iterable[str],
        payload: bytes | str,
        type: BinaryType = BinaryType.GENERIC,
    ) -> int:
        """Send one binary message; returns the number delivered."""

        message = BinaryMessage(recipients=tuple(recipients), payload=payload, type=type)
        return self.send_binaries([message])

    def send_binaries(self, messages: Sequence[BinaryMessage]) -> int:
        """Send a batch of pre-built :class:`BinaryMessage` objects."""

        if not messages:
            raise ValueError("messages must not be empty")
        body = {"Messages": [m.to_dict() for m in messages]}
        response = self._request("POST", _PATH_BINARY, json=body)
        return self._count(response)

    def send_media(
        self,
        recipients: Iterable[str],
        sender: str,
        text: str,
        media: str,
        *,
        timestamp: datetime | None = None,
        now: datetime | None = None,
    ) -> int:
        """Send one media (image/audio) message; returns the number delivered."""

        message = MediaMessage(
            recipients=tuple(recipients),
            sender=sender,
            text=text,
            media=media,
            timestamp=timestamp,
        )
        response = self._request("POST", _PATH_MEDIA, json=message.to_dict(now=now))
        return self._count(response)

    # -- location ----------------------------------------------------------

    def request_location(self, imeis: Iterable[str]) -> Any:
        """Request a fresh location (sends a locate command; incurs cost)."""

        return self._json(self._request("GET", _PATH_LOC_REQUEST, params=self._imei_param(imeis)))

    def last_known_location(self, imeis: Iterable[str]) -> Any:
        """Query the last known location (no command sent; no cost)."""

        return self._json(self._request("GET", _PATH_LOC_LAST, params=self._imei_param(imeis)))

    def send_location_request(self, imeis: Iterable[str]) -> Any:
        """Send a location request via POST for one or more devices."""

        body = {"IMEI": list(validate_imeis(imeis))}
        return self._json(self._request("POST", _PATH_LOC_SEND, json=body))

    def location_history(
        self,
        imeis: Iterable[str],
        start: date | datetime | str,
        end: date | datetime | str,
    ) -> Any:
        """Query stored location history for a date range (no cost)."""

        params = self._imei_param(imeis)
        params["Start"] = _as_date_string(start)
        params["End"] = _as_date_string(end)
        return self._json(self._request("GET", _PATH_LOC_HISTORY, params=params))

    # -- tracking ----------------------------------------------------------

    def set_tracking(self, devices: Sequence[TrackingDevice]) -> None:
        """Enable/disable tracking (and optionally set interval) per device."""

        if not devices:
            raise ValueError("devices must not be empty")
        body = {"Devices": [d.to_tracking_dict() for d in devices]}
        self._request("POST", _PATH_TRACK, json=body)

    def set_interval(self, devices: Sequence[TrackingDevice]) -> None:
        """Set the tracking interval for one or more devices."""

        if not devices:
            raise ValueError("devices must not be empty")
        body = {"Devices": [d.to_interval_dict() for d in devices]}
        self._request("POST", _PATH_INTERVAL, json=body)

    def enable_tracking(self, imei: str, *, interval: int | None = None) -> None:
        """Convenience: turn tracking on for a single device."""

        self.set_tracking([TrackingDevice(imei=imei, tracking=True, interval=interval)])

    def disable_tracking(self, imei: str) -> None:
        """Convenience: turn tracking off for a single device."""

        self.set_tracking([TrackingDevice(imei=imei, tracking=False)])

    def set_device_interval(self, imei: str, interval: int) -> None:
        """Convenience: set the tracking interval for a single device."""

        self.set_interval([TrackingDevice(imei=imei, interval=interval)])

    # -- emergency ---------------------------------------------------------

    def get_respondent(self) -> bool:
        """Return ``True`` if SOS is handled by the Garmin Response Team."""

        data = self._json(self._request("GET", _PATH_EMER_RESPONDENT))
        return bool(_get(data, "respondent"))

    def get_emergency_state(self, imeis: Iterable[str]) -> Any:
        """Return the emergency state of one or more devices."""

        return self._json(self._request("GET", _PATH_EMER_STATE, params=self._imei_param(imeis)))

    def acknowledge_emergency(self, imei: str) -> None:
        """Acknowledge an SOS for a device (requires the GEOSEnabled flag)."""

        self._request("POST", _PATH_EMER_ACK, params={"IMEI": validate_imei(imei)})

    def send_emergency_message(
        self,
        imei: str,
        text: str,
        *,
        timestamp: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Send a message to a device that is in an emergency state."""

        moment = timestamp if timestamp is not None else (now or _utcnow())
        body = {
            "IMEI": validate_imei(imei),
            "UtcTimeStamp": to_iso8601(validate_timestamp(moment, now=now)),
            "Message": validate_message(text),
        }
        self._request("POST", _PATH_EMER_SEND, json=body)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _imei_param(imeis: Iterable[str]) -> dict[str, str]:
        return {"IMEI": ",".join(validate_imeis(imeis))}

    def _backoff(self, attempt: int) -> float:
        return min(self._backoff_factor * (1 << (attempt - 1)), self._backoff_max)

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header is not None:
            try:
                return min(max(float(int(header)), 0.0), self._retry_after_max)
            except ValueError:
                pass
        return self._backoff(attempt)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        url = self._base_url + path
        is_get = method == "GET"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(method, url, params=params, json=json)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The connection was never established, so the request was
                # definitely not processed: safe to retry for any method.
                if attempt <= self._max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                raise TransportError(f"could not connect to {url}: {exc}") from exc
            except httpx.TransportError as exc:
                # Ambiguous failure (e.g. read timeout): the server may already
                # have acted on the request. Only retry idempotent GETs.
                if is_get and attempt <= self._max_retries:
                    self._sleep(self._backoff(attempt))
                    continue
                raise TransportError(f"transport error for {url}: {exc}") from exc

            if response.status_code == 429 and attempt <= self._max_retries:
                self._sleep(self._retry_after(response, attempt))
                continue
            retryable_get = is_get and response.status_code in _RETRYABLE_GET_STATUS
            if retryable_get and attempt <= self._max_retries:
                self._sleep(self._backoff(attempt))
                continue

            if response.is_success:
                return response
            raise self._error_from_response(response)

    def _error_from_response(self, response: httpx.Response) -> Exception:
        code = description = url = message = None
        imeis: list[str] = []
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, Mapping):
            code = body.get("Code")
            description = body.get("Description")
            url = body.get("URL")
            message = body.get("Message")
            raw_imeis = body.get("IMEI") or body.get("Recipients")
            if isinstance(raw_imeis, list):
                imeis = [str(i) for i in raw_imeis]
            elif raw_imeis not in (None, ""):
                imeis = [str(raw_imeis)]
        retry_after = None
        if response.status_code == 429:
            retry_after = self._retry_after(response, 1)
        return response_error_for(
            response.status_code,
            message=message or f"HTTP {response.status_code} {response.reason_phrase}",
            code=code if isinstance(code, int) else None,
            description=description if isinstance(description, str) else None,
            url=url if isinstance(url, str) else None,
            imeis=imeis,
            retry_after=retry_after,
        )

    def _json(self, response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ParseError(f"expected a JSON response body: {exc}") from exc

    def _count(self, response: httpx.Response) -> int:
        data = self._json(response)
        value = _get(data, "count")
        if not isinstance(value, int):
            raise ParseError(f"expected an integer 'count' in response, got {data!r}")
        return value


def _get(data: Any, key: str) -> Any:
    if isinstance(data, Mapping):
        return data.get(key)
    raise ParseError(f"expected a JSON object, got {type(data).__name__}")


def _as_date_string(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError(f"expected a date, datetime or 'YYYY-MM-DD' string, got {value!r}")


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
