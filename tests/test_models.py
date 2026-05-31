"""Tests for the immutable request models and their JSON serialisation."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from pyinreach import (
    BinaryMessage,
    BinaryType,
    Coordinate,
    LocationType,
    MediaMessage,
    Message,
    ReferencePoint,
    TrackingDevice,
    ValidationError,
    build_data_url,
)

TS = datetime(2011, 2, 1, 0, 3, 20, tzinfo=timezone.utc)  # 1296561800000 ms


def test_coordinate_serialisation() -> None:
    assert Coordinate(2, 2).to_dict() == {"Latitude": 2.0, "Longitude": 2.0}


def test_reference_point_serialises_numbers_as_strings() -> None:
    rp = ReferencePoint(
        coordinate=Coordinate(2, 2),
        location_type=LocationType.GPS,
        altitude=20,
        speed=20,
        course=180,
        label="",
    )
    assert rp.to_dict() == {
        "LocationType": "1",
        "Altitude": "20",
        "Speed": "20",
        "Course": "180",
        "Coordinate": {"Latitude": 2.0, "Longitude": 2.0},
        "Label": "",
    }


def test_message_serialisation_uses_dotnet_date() -> None:
    msg = Message(recipients=["100000000000001"], sender="t@example.com", text="Hi", timestamp=TS)
    body = msg.to_dict()
    assert body["Recipients"] == ["100000000000001"]
    assert body["Sender"] == "t@example.com"
    assert body["Message"] == "Hi"
    assert body["Timestamp"].startswith("/Date(") and body["Timestamp"].endswith(")/")
    assert "ReferencePoint" not in body


def test_message_with_reference_point() -> None:
    rp = ReferencePoint(coordinate=Coordinate(1, 1), label="cabin")
    msg = Message(recipients=["100000000000001"], sender="t@e.com", text="x", reference_point=rp)
    assert msg.to_dict()["ReferencePoint"]["Label"] == "cabin"


def test_message_label_counts_against_limit() -> None:
    rp = ReferencePoint(coordinate=Coordinate(1, 1), label="x" * 10)
    with pytest.raises(ValidationError):
        Message(
            recipients=["100000000000001"],
            sender="t@e.com",
            text="y" * 151,
            reference_point=rp,
        )


def test_message_is_frozen() -> None:
    msg = Message(recipients=["100000000000001"], sender="t@e.com", text="x")
    with pytest.raises(AttributeError):
        msg.text = "changed"  # type: ignore[misc]


def test_binary_message_from_bytes() -> None:
    msg = BinaryMessage(recipients=["100000000000001"], payload=b"hello", type=BinaryType.GENERIC)
    body = msg.to_dict()
    assert body["Type"] == 1
    assert base64.b64decode(body["Payload"]) == b"hello"


def test_binary_message_payload_too_large() -> None:
    with pytest.raises(ValidationError):
        BinaryMessage(recipients=["100000000000001"], payload=b"x" * 269)


def test_media_message_serialisation() -> None:
    msg = MediaMessage.from_bytes(
        recipients=["100000000000001", "100000000000002"],
        sender="m@garmin.com",
        text="Test Media Message",
        data=b"\x00\x01\x02",
        mime_type="image/avif",
        timestamp=TS,
    )
    body = msg.to_dict()
    assert body["Recipients"] == "100000000000001,100000000000002"  # comma-joined string
    assert body["Media"].startswith("data:image/avif;base64,")
    assert body["Timestamp"].endswith("Z")


def test_media_message_rejects_non_data_url() -> None:
    with pytest.raises(ValidationError):
        MediaMessage(recipients=["100000000000001"], sender="m@g.com", text="x", media="http://x")


def test_build_data_url() -> None:
    url = build_data_url(b"hi", "image/png")
    assert url == "data:image/png;base64," + base64.b64encode(b"hi").decode()


def test_tracking_device_serialisers() -> None:
    dev = TrackingDevice(imei="100000000000001", tracking=True, interval=30)
    assert dev.to_tracking_dict() == {"Imei": "100000000000001", "Tracking": True, "Interval": 30}
    assert TrackingDevice(imei="100000000000001", interval=600).to_interval_dict() == {
        "Imei": "100000000000001",
        "Interval": 600,
    }


def test_tracking_device_requires_relevant_fields() -> None:
    with pytest.raises(ValidationError):
        TrackingDevice(imei="100000000000001").to_tracking_dict()  # no tracking flag
    with pytest.raises(ValidationError):
        TrackingDevice(imei="100000000000001", tracking=True).to_interval_dict()  # no interval
