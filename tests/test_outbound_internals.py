"""Coverage for outbound value coercion and the derived-view properties."""

from __future__ import annotations

import base64

import pytest

from pyinreach import Event, GpsFix, Point, Status, parse_events


def _one(payload: str) -> Event:
    return parse_events(payload)[0]


def test_point_and_status_coercion_from_strings_and_floats() -> None:
    event = _one(
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":0,'
        '"point":{"latitude":"43.8","longitude":-70.1,"gpsFix":"2","speed":50.0},'
        '"status":{"autonomous":1.0,"lowBattery":"1"}}]}'
    )
    assert event.point is not None
    assert event.point.latitude == 43.8
    assert event.point.gps_fix == 2
    assert event.point.speed == 50.0
    assert event.status is not None
    assert event.status.autonomous == 1
    assert event.status.low_battery == 1


def test_coercion_returns_none_for_unparseable() -> None:
    event = _one(
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":0,'
        '"timeStamp":"not-a-number",'
        '"point":{"latitude":true,"gpsFix":"x","course":"NaN"}}]}'
    )
    assert event.timestamp_ms is None
    assert event.point is not None
    assert event.point.latitude is None  # bool is rejected
    assert event.point.gps_fix is None
    assert event.point.course is None


def test_point_and_status_absent_become_none() -> None:
    event = _one('{"Version":"2.0","Events":[{"imei":"1","messageCode":0}]}')
    assert event.point is None
    assert event.status is None


def test_addresses_accept_plain_strings() -> None:
    event = _one('{"Version":"2.0","Events":[{"imei":"1","messageCode":3,"addresses":["a","b"]}]}')
    assert event.addresses == ("a", "b")


def test_gps_fix_enum_variants() -> None:
    assert Point(gps_fix=None).gps_fix_enum is None
    assert Point(gps_fix=2).gps_fix_enum is GpsFix.FIX_3D
    assert Point(gps_fix=99).gps_fix_enum is None  # unknown numeric


def test_status_derived_booleans() -> None:
    assert Status(autonomous=1).is_autonomous is True
    assert Status(autonomous=0).is_autonomous is False
    assert Status(autonomous=None).is_autonomous is None
    assert Status(low_battery=1).battery_low is True
    assert Status(low_battery=0).battery_low is False
    assert Status(low_battery=2).battery_low is None  # "not reported"
    assert Status(reset_detected=1).factory_reset_detected is True
    assert Status(reset_detected=None).factory_reset_detected is None


def test_transport_mode_unknown_returns_none() -> None:
    payload = '{"Version":"3.0","Events":[{"imei":"1","messageCode":0,"transportMode":"Carrier"}]}'
    assert _one(payload).transport_mode_enum is None


def test_decoded_payload_present_and_absent() -> None:
    encoded = base64.b64encode(b"\x01\x02").decode()
    event = _one(
        f'{{"Version":"2.0","Events":[{{"imei":"1","messageCode":64,"payload":"{encoded}"}}]}}'
    )
    assert event.decoded_payload() == b"\x01\x02"
    no_payload = _one('{"Version":"2.0","Events":[{"imei":"1","messageCode":0}]}')
    assert no_payload.decoded_payload() is None


def test_pingback_timestamps() -> None:
    event = _one(
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":65,'
        '"pingbackReceived":1323784607376,"pingbackResponded":1323784607999}]}'
    )
    assert event.pingback_received is not None
    assert event.pingback_responded is not None
    assert event.pingback_responded > event.pingback_received


def test_event_batch_is_iterable_indexable_sized() -> None:
    batch = parse_events(
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":0},{"imei":"2","messageCode":3}]}'
    )
    assert len(batch) == 2
    assert [e.imei for e in batch] == ["1", "2"]
    assert batch[1].message_code == 3


def test_parse_accepts_bytes() -> None:
    batch = parse_events(b'{"Version":"2.0","Events":[{"imei":"1","messageCode":0}]}')
    assert batch.version == "2.0"


def test_parse_rejects_wrong_type() -> None:
    from pyinreach import ParseError

    with pytest.raises(ParseError):
        parse_events(12345)  # type: ignore[arg-type]
