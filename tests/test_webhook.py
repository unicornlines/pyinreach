"""Tests for the webhook authentication helpers."""

from __future__ import annotations

import pytest

from pyinreach import parse_bearer_token, verify_static_token


def test_verify_static_token_matches() -> None:
    assert verify_static_token("s3cret", "s3cret") is True


def test_verify_static_token_rejects_wrong_and_missing() -> None:
    assert verify_static_token("wrong", "s3cret") is False
    assert verify_static_token(None, "s3cret") is False
    assert verify_static_token("", "s3cret") is False


def test_verify_static_token_requires_expected() -> None:
    with pytest.raises(ValueError):
        verify_static_token("anything", "")


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),  # case-insensitive scheme
        ("BEARER   spaced  ", "spaced"),
        ("Basic abc123", None),
        ("abc123", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_bearer_token(header: str | None, expected: str | None) -> None:
    assert parse_bearer_token(header) == expected
