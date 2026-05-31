"""Tests for the deterministic validators."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from pyinreach import ErrorCode, ValidationError
from pyinreach import validation as V


def test_imei_accepts_15_digits() -> None:
    assert V.validate_imei("300234010571020") == "300234010571020"


@pytest.mark.parametrize("bad", ["12345", "30023401057102X", "3002340105710200", 300234010571020])
def test_imei_rejects_non_15_digits(bad: object) -> None:
    with pytest.raises(ValidationError) as exc:
        V.validate_imei(bad)  # type: ignore[arg-type]
    assert exc.value.code == ErrorCode.UNKNOWN_DEVICE


def test_imeis_requires_non_empty_iterable() -> None:
    with pytest.raises(ValidationError):
        V.validate_imeis([])
    with pytest.raises(ValidationError):
        V.validate_imeis("300234010571020")  # a bare string is rejected


@pytest.mark.parametrize(
    "func,good,bad,code",
    [
        (V.validate_altitude, 18000, 18001, ErrorCode.INVALID_ALTITUDE),
        (V.validate_altitude, -1000, -1001, ErrorCode.INVALID_ALTITUDE),
        (V.validate_speed, 1854, 1855, ErrorCode.INVALID_SPEED),
        (V.validate_speed, 0, -1, ErrorCode.INVALID_SPEED),
        (V.validate_course, 360, 361, ErrorCode.INVALID_COURSE),
        (V.validate_course, -360, -361, ErrorCode.INVALID_COURSE),
        (V.validate_latitude, 90, 90.0001, ErrorCode.INVALID_POSITION),
        (V.validate_longitude, -180, -180.0001, ErrorCode.INVALID_POSITION),
    ],
)
def test_numeric_bounds(func, good, bad, code) -> None:  # type: ignore[no-untyped-def]
    assert func(good) == good
    with pytest.raises(ValidationError) as exc:
        func(bad)
    assert exc.value.code == code


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "5", None])
def test_numbers_reject_non_finite_and_bool(bad: object) -> None:
    with pytest.raises(ValidationError):
        V.validate_altitude(bad)


def test_interval_bounds_and_type() -> None:
    assert V.validate_interval(30) == 30
    assert V.validate_interval(65535) == 65535
    for bad in (29, 65536, True, 30.0):
        with pytest.raises(ValidationError) as exc:
            V.validate_interval(bad)  # type: ignore[arg-type]
        assert exc.value.code == ErrorCode.INVALID_INTERVAL


def test_location_and_binary_types() -> None:
    assert int(V.validate_location_type(1)) == 1
    with pytest.raises(ValidationError):
        V.validate_location_type(2)
    assert int(V.validate_binary_type(2)) == 2
    with pytest.raises(ValidationError):
        V.validate_binary_type(3)


def test_message_length_and_label_budget() -> None:
    assert V.validate_message("hi") == "hi"
    with pytest.raises(ValidationError):
        V.validate_message("")
    with pytest.raises(ValidationError):
        V.validate_message("x" * 161)
    # label shares the 160-character budget
    with pytest.raises(ValidationError) as exc:
        V.validate_message("x" * 156, label_len=5)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_label_budget() -> None:
    assert V.validate_label("abc", message_len=10) == "abc"
    with pytest.raises(ValidationError):
        V.validate_label("x" * 151, message_len=10)


def test_timestamp_bounds() -> None:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert V.validate_timestamp(datetime(2011, 1, 1, tzinfo=timezone.utc), now=now)
    with pytest.raises(ValidationError) as too_old:
        V.validate_timestamp(datetime(2010, 12, 31, tzinfo=timezone.utc), now=now)
    assert too_old.value.code == ErrorCode.INVALID_TIMESTAMP
    with pytest.raises(ValidationError):
        V.validate_timestamp(now + timedelta(seconds=1), now=now)


@pytest.mark.parametrize("sender", ["test.ipc@gmail.com", "2075752244", "+1 (207) 575-2244"])
def test_sender_accepts_email_and_phone(sender: str) -> None:
    assert V.validate_sender(sender) == sender


@pytest.mark.parametrize("bad", ["not an address", "@nope", "", "abcd"])
def test_sender_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValidationError) as exc:
        V.validate_sender(bad)
    assert exc.value.code == ErrorCode.INVALID_SENDER


def test_payload_base64_and_size() -> None:
    good = base64.b64encode(b"hello").decode()
    assert V.validate_payload(good) == b"hello"
    with pytest.raises(ValidationError) as bad_b64:
        V.validate_payload("not base64!!")
    assert bad_b64.value.code == ErrorCode.INVALID_PAYLOAD
    too_big = base64.b64encode(b"x" * 269).decode()
    with pytest.raises(ValidationError):
        V.validate_payload(too_big)
