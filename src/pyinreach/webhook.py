"""Helpers for authenticating inbound *outbound-API* webhook requests.

Garmin authenticates itself to your web service either with an OAuth token or a
static token placed in an HTTP header. Verifying an OAuth/JWT token is
application-specific (it depends on your authorization server) and is therefore
out of scope here. The common, robust case -- a shared static token -- is
supported with a constant-time comparison so verification cannot be attacked by
timing.

These helpers are pure and dependency-free, which keeps the request-receiving
side of an application (e.g. a Django view) free of any HTTP-client baggage.
"""

from __future__ import annotations

import hmac

__all__ = ["parse_bearer_token", "verify_static_token"]


def verify_static_token(provided: str | None, expected: str) -> bool:
    """Return ``True`` iff *provided* equals *expected*, in constant time.

    A ``None`` or empty *provided* value always fails. The comparison uses
    :func:`hmac.compare_digest`, so it does not leak token length or content
    through timing side channels.
    """

    if not expected:
        raise ValueError("expected token must be a non-empty string")
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def parse_bearer_token(authorization_header: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header.

    Returns ``None`` if the header is absent or not a well-formed bearer
    credential. The scheme match is case-insensitive per RFC 7235.
    """

    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
