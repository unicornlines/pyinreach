"""Tests for the authentication strategies."""

from __future__ import annotations

import base64

import httpx
import pytest

from pyinreach import ApiKeyAuth, BasicAuth


def _apply(auth: httpx.Auth, request: httpx.Request) -> httpx.Request:
    flow = auth.auth_flow(request)
    return next(flow)


def test_api_key_sets_header() -> None:
    request = httpx.Request("GET", "https://example.test/")
    out = _apply(ApiKeyAuth("secret-key"), request)
    assert out.headers["X-API-Key"] == "secret-key"


def test_api_key_repr_is_redacted() -> None:
    assert "secret-key" not in repr(ApiKeyAuth("secret-key"))


def test_api_key_rejects_empty() -> None:
    with pytest.raises(ValueError):
        ApiKeyAuth("")


def test_basic_auth_sets_header() -> None:
    request = httpx.Request("GET", "https://example.test/")
    out = _apply(BasicAuth("user", "pass"), request)
    expected = "Basic " + base64.b64encode(b"user:pass").decode()
    assert out.headers["Authorization"] == expected


def test_basic_auth_repr_redacts_password() -> None:
    text = repr(BasicAuth("alice", "hunter2"))
    assert "alice" in text
    assert "hunter2" not in text
