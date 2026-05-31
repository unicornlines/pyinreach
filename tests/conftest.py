"""Shared fixtures: a network-free InboundClient backed by httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pyinreach import ApiKeyAuth, InboundClient

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def sleeps() -> list[float]:
    """Records every back-off sleep the client would have performed."""

    return []


@pytest.fixture
def make_client(sleeps: list[float]) -> Callable[..., InboundClient]:
    """Factory building an InboundClient whose transport is a mock handler."""

    created: list[InboundClient] = []

    def _make(handler: Handler, **kwargs: Any) -> InboundClient:
        kwargs.setdefault("base_url", "https://test.example")
        client = InboundClient(
            auth=ApiKeyAuth("test-key"),
            transport=httpx.MockTransport(handler),
            sleep=lambda s: sleeps.append(s),
            **kwargs,
        )
        created.append(client)
        return client

    yield _make
    for client in created:
        client.close()


def json_response(
    payload: Any, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)
