"""Tests for the date/time conversion helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pyinreach import (
    from_epoch_ms,
    parse_dotnet_date,
    parse_iso8601,
    to_dotnet_date,
    to_epoch_ms,
    to_iso8601,
)
from pyinreach.dates import ensure_utc

# A timestamp straight from the IPC Outbound "Example Event".
EXAMPLE_MS = 1323784607376


def test_epoch_round_trip() -> None:
    assert to_epoch_ms(from_epoch_ms(EXAMPLE_MS)) == EXAMPLE_MS


def test_from_epoch_ms_is_exact_and_utc() -> None:
    dt = from_epoch_ms(EXAMPLE_MS)
    assert dt.tzinfo == timezone.utc
    assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=EXAMPLE_MS)


def test_dotnet_date_serialisation() -> None:
    assert to_dotnet_date(from_epoch_ms(1296557000000)) == "/Date(1296557000000)/"


@pytest.mark.parametrize(
    "value",
    ["/Date(1296557000000)/", "\\/Date(1296557000000)\\/", "/Date(1296557000000+0000)/"],
)
def test_parse_dotnet_date_variants(value: str) -> None:
    assert to_epoch_ms(parse_dotnet_date(value)) == 1296557000000


def test_parse_dotnet_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_dotnet_date("2024-01-01")


def test_iso8601_serialisation_has_millis_and_z() -> None:
    dt = datetime(2024, 4, 7, 21, 28, 24, 968000, tzinfo=timezone.utc)
    assert to_iso8601(dt) == "2024-04-07T21:28:24.968Z"


def test_iso8601_round_trip() -> None:
    text = "2024-04-07T21:28:24.968Z"
    assert to_iso8601(parse_iso8601(text)) == text


def test_parse_iso8601_with_offset_normalises_to_utc() -> None:
    parsed = parse_iso8601("2024-04-07T23:28:24.968+02:00")
    assert parsed == datetime(2024, 4, 7, 21, 28, 24, 968000, tzinfo=timezone.utc)


def test_ensure_utc_treats_naive_as_utc() -> None:
    naive = datetime(2024, 1, 1, 12, 0, 0)
    assert ensure_utc(naive) == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
