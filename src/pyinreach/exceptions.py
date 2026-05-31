"""Exception hierarchy for :mod:`pyinreach`.

The hierarchy mirrors the failure modes documented for the IPC API so callers
can catch precisely the category they care about::

    PyInreachError
    ├── ConfigurationError        -- the client was set up incorrectly
    ├── ValidationError           -- caught locally, before any request is sent
    ├── TransportError            -- network / TLS / timeout failure
    ├── ParseError                -- a malformed payload could not be decoded
    └── ResponseError             -- the API returned a JSON error object
        ├── AuthenticationError   -- HTTP 401 / 403  (error code 3)
        ├── RateLimitError        -- HTTP 429        (error code 2)
        ├── UnprocessableError    -- HTTP 422        (semantic rejection)
        └── ServerError           -- HTTP 500 / 501  (error code 1)
"""

from __future__ import annotations

from collections.abc import Sequence

from .constants import ErrorCode


class PyInreachError(Exception):
    """Base class for every error raised by this library."""


class ConfigurationError(PyInreachError):
    """The client or a request was configured in a way that cannot work."""


class ValidationError(PyInreachError, ValueError):
    """A value failed local validation before any network call was made.

    Local validation deliberately mirrors the server-side rules so that the
    cost (and side effects) of a doomed request are avoided. ``code`` is the
    matching :class:`~pyinreach.constants.ErrorCode` the server would have
    returned, and ``field`` names the offending input.
    """

    def __init__(self, message: str, *, code: ErrorCode, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


class TransportError(PyInreachError):
    """A network-level failure: connection refused, TLS error, timeout, ..."""


class ParseError(PyInreachError):
    """A payload could not be parsed into the expected structure."""


class ResponseError(PyInreachError):
    """The API responded with a JSON error object.

    Attributes map onto the documented error object fields. Any of them may be
    ``None`` when the server omits them (for example, encrypted-messaging
    accounts drop ``null`` values from responses).
    """

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        code: int | None = None,
        description: str | None = None,
        url: str | None = None,
        imeis: Sequence[str] | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.code = code
        self.description = description
        self.url = url
        self.imeis: tuple[str, ...] = tuple(imeis) if imeis else ()
        self.retry_after = retry_after

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        parts = [self.message]
        if self.code is not None:
            parts.append(f"code={self.code}")
        parts.append(f"http_status={self.http_status}")
        if self.imeis:
            parts.append(f"imeis={list(self.imeis)}")
        return " ".join(parts)


class AuthenticationError(ResponseError):
    """HTTP 401/403 -- credentials or API key missing or invalid."""


class RateLimitError(ResponseError):
    """HTTP 429 -- too many requests; ``retry_after`` holds the server hint."""


class UnprocessableError(ResponseError):
    """HTTP 422 -- the request was well-formed but semantically rejected."""


class ServerError(ResponseError):
    """HTTP 500/501 -- an internal failure inside the IPC service."""


def response_error_for(
    http_status: int,
    *,
    message: str,
    code: int | None = None,
    description: str | None = None,
    url: str | None = None,
    imeis: Sequence[str] | None = None,
    retry_after: float | None = None,
) -> ResponseError:
    """Construct the most specific :class:`ResponseError` for *http_status*."""

    cls: type[ResponseError]
    if http_status in (401, 403):
        cls = AuthenticationError
    elif http_status == 429:
        cls = RateLimitError
    elif http_status == 422:
        cls = UnprocessableError
    elif http_status >= 500:
        cls = ServerError
    else:
        cls = ResponseError
    return cls(
        message,
        http_status=http_status,
        code=code,
        description=description,
        url=url,
        imeis=imeis,
        retry_after=retry_after,
    )
