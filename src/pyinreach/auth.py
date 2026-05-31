"""Authentication strategies for the inbound API.

The IPC Inbound service supports two schemes:

* **API key** (v2) -- an ``X-API-Key`` header. This is the current scheme.
* **HTTP Basic** (legacy ``.svc`` services) -- a username/password pair.

Both are :class:`httpx.Auth` implementations, so they plug straight into the
client's transport. Credentials are never included in ``repr`` output, to keep
them out of logs and tracebacks.
"""

from __future__ import annotations

import base64
from collections.abc import Generator

import httpx

__all__ = ["ApiKeyAuth", "BasicAuth"]


class ApiKeyAuth(httpx.Auth):
    """Attach an ``X-API-Key`` header to every request (IPC Inbound v2)."""

    def __init__(self, api_key: str):
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["X-API-Key"] = self._api_key
        yield request

    def __repr__(self) -> str:
        return "ApiKeyAuth(api_key='***')"


class BasicAuth(httpx.Auth):
    """Attach an HTTP Basic ``Authorization`` header (legacy ``.svc`` API)."""

    def __init__(self, username: str, password: str):
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("username and password must be strings")
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._header = f"Basic {token}"
        self._username = username

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = self._header
        yield request

    def __repr__(self) -> str:
        return f"BasicAuth(username={self._username!r}, password='***')"
