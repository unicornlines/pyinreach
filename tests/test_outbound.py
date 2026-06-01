"""Tests for outbound event parsing, driven by the official example payloads."""

from __future__ import annotations

import base64

import pytest

from pyinreach import GpsFix, MessageCode, ParseError, TransportMode, parse_events
from pyinreach.outbound import DEFAULT_MAX_PAYLOAD_BYTES

# The IPC Outbound "Example Event" (event schema v2), verbatim.
EXAMPLE_EVENT = """
{
  "Version": "2.0",
  "Events": [
    {
      "imei": "100000000000001",
      "messageCode": 3,
      "freeText": "On my way.",
      "timeStamp": 1323784607376,
      "addresses": [
        { "address": "2075752244" },
        { "address": "product.support@garmin.com" }
      ],
      "point": {
        "latitude": 43.8078653812408,
        "longitude": -70.1636695861816,
        "altitude": 45,
        "gpsFix": 2,
        "course": 45,
        "speed": 50
      },
      "status": { "autonomous": 0, "lowBattery": 1, "intervalChange": 0, "resetDetected": 0 }
    }
  ]
}
"""

# "Example Free Text Content" -- note the null pingback fields and empty addresses.
FREE_TEXT_WITH_NULLS = (
    '{"Version": "2.0", "Events": [{"imei":"100000000000001", "messageCode":3, '
    '"freeText":"Hello World", "timeStamp": 1323784607376, "pingbackReceived":null, '
    '"pingbackResponded":null, "addresses":[], "point":{ "latitude":43.8078653812408, '
    '"longitude":-70.1636695861816, "altitude":45, "gpsFix":2, "course":45, "speed":50 }, '
    '"status":{ "autonomous":0, "lowBattery":0 , "intervalChange":0, "resetDetected":0}}]}'
)

# "Example Binary Content" (v2).
BINARY_V2 = (
    '{"Version": "2.0","Events": [{"payload": "aGVsbG8=","imei": "300234010571020",'
    '"messageCode": 64,"status": {"lowBattery": 0}}]}'
)

# "Example Binary Content V4" -- binary messages carry a timeStamp in v4.
BINARY_V4 = (
    '{"Version": "4.0","Events": [{"transportMode": "Satellite","payload": "aGVsbG8=",'
    '"imei": "300052030105900","messageCode": 66,"timeStamp": 1740406683953,'
    '"status": {"lowBattery": 0}}]}'
)

MEDIA_B64 = base64.b64encode(b"ogg-audio-bytes").decode()
MEDIA_V4 = (
    '{"Version": "4.0","Events": [{"imei": "100000000000001","mediaBytes": "' + MEDIA_B64 + '",'
    '"mediaId": "01082758-4cfb-451d-a273-2e4bf462c37d","mediaType": "audio/ogg",'
    '"transcription": "This is an audio message","messageCode": 3,"freeText": "On my way.",'
    '"timeStamp": 1323784607376,"addresses": [{"address": "2075752244"}],'
    '"status": {"autonomous": 0, "lowBattery": 1}}]}'
)


def test_parse_example_event_v2() -> None:
    batch = parse_events(EXAMPLE_EVENT)
    assert batch.version == "2.0"
    assert len(batch) == 1
    event = batch[0]
    assert event.imei == "100000000000001"
    assert event.message_code == 3
    assert event.message_code_enum is MessageCode.FREE_TEXT
    assert event.message_code_name == "FREE_TEXT"
    assert event.free_text == "On my way."
    assert event.addresses == ("2075752244", "product.support@garmin.com")
    assert event.point is not None and event.point.gps_fix_enum is GpsFix.FIX_3D
    assert event.status is not None and event.status.battery_low is True
    assert event.timestamp is not None and event.timestamp.year == 2011


def test_parse_handles_null_and_empty_fields() -> None:
    event = parse_events(FREE_TEXT_WITH_NULLS)[0]
    assert event.pingback_received_ms is None
    assert event.addresses == ()
    assert event.status is not None and event.status.battery_low is False


def test_parse_binary_v2_decodes_payload() -> None:
    event = parse_events(BINARY_V2)[0]
    assert event.message_code == MessageCode.ENCRYPTED_BINARY
    assert event.decoded_payload() == b"hello"
    assert event.timestamp is None  # v2 binary has no timestamp


def test_parse_binary_v4_has_transport_and_timestamp() -> None:
    event = parse_events(BINARY_V4)[0]
    assert event.transport_mode_enum is TransportMode.SATELLITE
    assert event.message_code == MessageCode.GENERIC_BINARY
    assert event.timestamp_ms == 1740406683953


def test_parse_media_v4() -> None:
    event = parse_events(MEDIA_V4)[0]
    assert event.media_type == "audio/ogg"
    assert event.transcription == "This is an audio message"
    assert event.decoded_media() == b"ogg-audio-bytes"


def test_unknown_message_code_is_preserved() -> None:
    event = parse_events('{"Version":"9.9","Events":[{"imei":"1","messageCode":9999}]}')[0]
    assert event.message_code == 9999
    assert event.message_code_enum is None
    assert event.message_code_name == "UNKNOWN"


def test_predefined_message_range() -> None:
    event = parse_events('{"Version":"2.0","Events":[{"imei":"1","messageCode":30}]}')[0]
    assert event.is_predefined_message is True
    assert event.message_code_name == "PREDEFINED_MESSAGE"


def test_multi_device_imei_split() -> None:
    event = parse_events('{"Version":"2.0","Events":[{"imei":"111,222,333","messageCode":3}]}')[0]
    assert event.imeis == ("111", "222", "333")


def test_accepts_already_decoded_mapping() -> None:
    batch = parse_events({"Version": "2.0", "Events": [{"imei": "1", "messageCode": 0}]})
    assert batch[0].message_code == 0


def test_raw_is_read_only_and_lossless() -> None:
    payload = '{"Version":"2.0","Events":[{"imei":"1","messageCode":3,"futureField":42}]}'
    event = parse_events(payload)[0]
    assert event.raw["futureField"] == 42
    with pytest.raises(TypeError):
        event.raw["x"] = 1  # type: ignore[index]


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",  # top-level array, not object
        '{"Version":"2.0"}',  # missing Events
        '{"Version":"2.0","Events":{}}',  # Events not an array
        '{"Events":[]}',  # missing Version
        '{"Version":"2.0","Events":[{"imei":"1"}]}',  # event missing messageCode
        '{"Version":"2.0","Events":["nope"]}',  # event not an object
    ],
)
def test_malformed_payloads_raise(payload: str) -> None:
    with pytest.raises(ParseError):
        parse_events(payload)


def test_oversized_payload_rejected() -> None:
    with pytest.raises(ParseError):
        parse_events('{"Version":"2.0","Events":[]}', max_bytes=5)


def test_default_max_bytes_is_generous() -> None:
    assert DEFAULT_MAX_PAYLOAD_BYTES >= 1_000_000


def test_bad_base64_media_raises() -> None:
    payload = '{"Version":"4.0","Events":[{"imei":"1","messageCode":3,"mediaBytes":"!!"}]}'
    event = parse_events(payload)[0]
    with pytest.raises(ParseError):
        event.decoded_media()


# --- Hostile / malformed payloads must fail cleanly, never crash the receiver ---


def test_deeply_nested_payload_raises_parse_error() -> None:
    # A deeply nested array exhausts the JSON decoder's stack; it must surface
    # as ParseError, not an uncaught RecursionError, so a webhook handler that
    # only guards ParseError is not crashed.
    with pytest.raises(ParseError):
        parse_events('{"Version":"2.0","Events":' + "[" * 60000)


def test_out_of_range_timestamp_becomes_none() -> None:
    # A timestamp outside datetime's representable range must yield None when
    # read, not raise OverflowError in the consumer's request handler.
    payload = (
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":65,'
        '"timeStamp":99999999999999999999,'
        '"pingbackReceived":-99999999999999999999,'
        '"pingbackResponded":99999999999999999999}]}'
    )
    event = parse_events(payload)[0]
    assert event.timestamp_ms == 99999999999999999999  # preserved losslessly
    assert event.timestamp is None
    assert event.pingback_received is None
    assert event.pingback_responded is None


def test_oversized_numeric_string_is_bounded() -> None:
    big = "9" * 100000
    # In a required field it is rejected, and the error must not embed the blob.
    with pytest.raises(ParseError) as exc:
        parse_events('{"Version":"2.0","Events":[{"imei":"1","messageCode":"' + big + '"}]}')
    assert len(str(exc.value)) < 200
    # In an optional field it coerces to None rather than being converted.
    event = parse_events(
        '{"Version":"2.0","Events":[{"imei":"1","messageCode":3,"timeStamp":"' + big + '"}]}'
    )[0]
    assert event.timestamp_ms is None
