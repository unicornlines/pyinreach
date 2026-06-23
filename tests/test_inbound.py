"""Tests for the InboundClient, including its retry and error-mapping policy."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from pyinreach import (
    AuthenticationError,
    BinaryType,
    Coordinate,
    RateLimitError,
    ReferencePoint,
    ServerError,
    TrackingDevice,
    TransportError,
    UnprocessableError,
)
from tests.conftest import json_response

TS = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# --------------------------------------------------------------------------
# Messaging
# --------------------------------------------------------------------------


def test_send_message_success(make_client) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["api_key"] = request.headers.get("X-API-Key")
        captured["body"] = _body(request)
        return json_response({"count": 1})

    client = make_client(handler)
    count = client.send_message(["100000000000001"], "t@example.com", "Hello", timestamp=TS)

    assert count == 1
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/Messaging/Message"
    assert captured["api_key"] == "test-key"
    message = captured["body"]["Messages"][0]
    assert message["Recipients"] == ["100000000000001"]
    assert message["Sender"] == "t@example.com"
    assert message["Message"] == "Hello"
    assert message["Timestamp"].startswith("/Date(")


def test_send_message_with_reference_point(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        rp = _body(request)["Messages"][0]["ReferencePoint"]
        assert rp["Coordinate"] == {"Latitude": 2.0, "Longitude": 2.0}
        assert rp["LocationType"] == "1"
        return json_response({"count": 1})

    rp = ReferencePoint(coordinate=Coordinate(2, 2))
    assert make_client(handler).send_message(
        ["100000000000001"], "t@e.com", "hi", reference_point=rp
    ) == 1


def test_send_binary_success(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Messaging/Binary"
        assert _body(request)["Messages"][0]["Type"] == 0
        return json_response({"count": 1})

    assert make_client(handler).send_binary(
        ["100000000000001"], b"data", BinaryType.ENCRYPTED
    ) == 1


def test_send_media_success(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        assert request.url.path == "/api/Messaging/Media"
        assert body["Recipients"] == "100000000000001"  # comma-joined string form
        assert body["Media"].startswith("data:image/png;base64,")
        return json_response({"count": 1})

    from pyinreach import build_data_url

    media = build_data_url(b"\x89PNG", "image/png")
    assert make_client(handler).send_media(["100000000000001"], "m@g.com", "pic", media) == 1


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------


def test_request_location(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/Location/LocationRequest"
        assert request.url.params.get("IMEI") == "100000000000001,100000000000002"
        return json_response({"ok": True})

    result = make_client(handler).request_location(["100000000000001", "100000000000002"])
    assert result == {"ok": True}


def test_last_known_location(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Location/LastKnownLocation"
        return json_response([{"latitude": 1.0}])

    assert make_client(handler).last_known_location(["100000000000001"]) == [{"latitude": 1.0}]


def test_send_location_request(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert _body(request) == {"IMEI": ["100000000000001"]}
        return json_response({"count": 1})

    make_client(handler).send_location_request(["100000000000001"])


def test_location_history_formats_dates(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("Start") == "2024-01-01"
        assert request.url.params.get("End") == "2024-03-01"
        return json_response([])

    make_client(handler).location_history(
        ["100000000000001"], date(2024, 1, 1), date(2024, 3, 1)
    )


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------


def test_set_tracking(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Tracking/Tracking"
        device = _body(request)["Devices"][0]
        assert device == {"Imei": "100000000000001", "Tracking": True, "Interval": 60}
        return httpx.Response(200)

    make_client(handler).set_tracking(
        [TrackingDevice(imei="100000000000001", tracking=True, interval=60)]
    )


def test_convenience_tracking_helpers(make_client) -> None:  # type: ignore[no-untyped-def]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "body": _body(request)})
        return httpx.Response(200)

    client = make_client(handler)
    client.enable_tracking("100000000000001", interval=120)
    client.disable_tracking("100000000000001")
    client.set_device_interval("100000000000001", 300)

    assert seen[0]["body"]["Devices"][0]["Tracking"] is True
    assert seen[1]["body"]["Devices"][0]["Tracking"] is False
    assert seen[2]["path"] == "/api/Tracking/Interval"
    assert seen[2]["body"]["Devices"][0]["Interval"] == 300


# --------------------------------------------------------------------------
# Emergency
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(1, True), (0, False)])
def test_get_respondent(make_client, value: int, expected: bool) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Emergency/Respondent"
        return json_response({"respondent": value})

    assert make_client(handler).get_respondent() is expected


def test_acknowledge_emergency(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Emergency/AcknowledgeDeclareEmergency"
        assert request.url.params.get("IMEI") == "100000000000001"
        return httpx.Response(200)

    make_client(handler).acknowledge_emergency("100000000000001")


def test_send_emergency_message(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        assert request.url.path == "/api/Emergency/SendMessage"
        assert body["IMEI"] == "100000000000001"
        assert body["Message"] == "hold on"
        assert body["UtcTimeStamp"].endswith("Z")
        return httpx.Response(200)

    make_client(handler).send_emergency_message("100000000000001", "hold on", timestamp=TS)


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


def test_422_maps_to_unprocessable(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            {
                "Code": 4,
                "Message": "Unknown or invalid device IMEI",
                "Description": "The IMEI 300234010000000 is invalid.",
                "URL": "https://test.example/api/Messaging/Message",
                "IMEI": ["300234010000000"],
            },
            status=422,
        )

    with pytest.raises(UnprocessableError) as exc:
        make_client(handler).send_message(["300234010000001"], "t@e.com", "hi")
    assert exc.value.code == 4
    assert exc.value.imeis == ("300234010000000",)
    assert exc.value.http_status == 422


def test_401_maps_to_authentication(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"Code": 3, "Message": "Invalid api key"}, status=401)

    with pytest.raises(AuthenticationError):
        make_client(handler).get_respondent()


def test_500_maps_to_server_error(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"Code": 1, "Message": "An unexpected error occurred"}, status=500)

    with pytest.raises(ServerError):
        make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")


# --------------------------------------------------------------------------
# Retry policy
# --------------------------------------------------------------------------


def test_429_is_retried_honouring_retry_after(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return json_response({"Code": 2}, status=429, headers={"Retry-After": "2"})
        return json_response({"count": 1})

    count = make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")
    assert count == 1
    assert calls["n"] == 2
    assert sleeps == [2.0]


def test_429_exhausts_retries(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"Code": 2}, status=429)

    with pytest.raises(RateLimitError):
        make_client(handler, max_retries=2).send_message(["100000000000001"], "t@e.com", "hi")
    assert len(sleeps) == 2  # initial attempt + 2 retries


def _retry_after_once(retry_after: str):  # type: ignore[no-untyped-def]
    """A handler that returns a 429 with the given Retry-After, then succeeds."""

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return json_response({"Code": 2}, status=429, headers={"Retry-After": retry_after})
        return json_response({"count": 1})

    return handler


def test_retry_after_accepts_fractional_seconds(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    count = make_client(_retry_after_once("1.5")).send_message(
        ["100000000000001"], "t@e.com", "hi"
    )
    assert count == 1
    assert sleeps == [1.5]


def test_retry_after_accepts_http_date(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    # A far-future HTTP-date hint is honoured but clamped to retry_after_max (60s).
    count = make_client(_retry_after_once("Wed, 21 Oct 2099 07:28:00 GMT")).send_message(
        ["100000000000001"], "t@e.com", "hi"
    )
    assert count == 1
    assert sleeps == [60.0]


def test_retry_after_garbage_falls_back_to_backoff(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    # An unparseable hint must not stall the caller: fall back to bounded backoff.
    count = make_client(_retry_after_once("soon")).send_message(
        ["100000000000001"], "t@e.com", "hi"
    )
    assert count == 1
    assert sleeps == [0.5]  # backoff_factor (0.5) * 2**(attempt-1)


def test_post_5xx_is_not_retried(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return json_response({"Code": 1}, status=500)

    with pytest.raises(ServerError):
        make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")
    assert calls["n"] == 1  # POST must not be replayed on an ambiguous 5xx
    assert sleeps == []


def test_get_5xx_is_retried(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return json_response([{"latitude": 1.0}])

    result = make_client(handler).last_known_location(["100000000000001"])
    assert result == [{"latitude": 1.0}]
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_connect_error_is_retried_for_post(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return json_response({"count": 1})

    count = make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")
    assert count == 1 and calls["n"] == 2 and len(sleeps) == 1


def test_read_timeout_is_not_retried_for_post(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(TransportError):
        make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")
    assert sleeps == []  # ambiguous failure on a POST is surfaced, not replayed


def test_read_timeout_is_retried_for_get(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("too slow")
        return json_response([])

    make_client(handler).last_known_location(["100000000000001"])
    assert calls["n"] == 2 and len(sleeps) == 1


# request_location is a GET, but it triggers a *paid* device command, so unlike
# the read-only GETs above it must never be replayed on an ambiguous failure.


def test_request_location_not_replayed_on_read_timeout(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("ambiguous: server may already have sent the locate")

    with pytest.raises(TransportError):
        make_client(handler).request_location(["100000000000001"])
    assert calls["n"] == 1  # the paid command was not re-sent
    assert sleeps == []


def test_request_location_not_replayed_on_5xx(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with pytest.raises(ServerError):
        make_client(handler).request_location(["100000000000001"])
    assert calls["n"] == 1
    assert sleeps == []


def test_request_location_retried_on_connect_error(make_client, sleeps: list[float]) -> None:  # type: ignore[no-untyped-def]
    # A connection error proves the locate command never reached the server, so
    # re-sending it cannot double-charge: that retry is still allowed.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused")
        return json_response({"ok": True})

    make_client(handler).request_location(["100000000000001"])
    assert calls["n"] == 2 and len(sleeps) == 1


def test_location_history_accepts_string_dates(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("Start") == "2024-01-01"
        return json_response([])

    make_client(handler).location_history(["100000000000001"], "2024-01-01", "2024-03-01")


def test_get_emergency_state(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/Emergency/State"
        return json_response({"100000000000001": "Normal"})

    assert make_client(handler).get_emergency_state(["100000000000001"]) == {
        "100000000000001": "Normal"
    }


def test_bad_count_raises_parse_error(make_client) -> None:  # type: ignore[no-untyped-def]
    from pyinreach import ParseError

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"unexpected": True})

    with pytest.raises(ParseError):
        make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")


def test_non_json_error_body_still_maps(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    with pytest.raises(ServerError) as exc:
        make_client(handler).send_message(["100000000000001"], "t@e.com", "hi")
    assert exc.value.http_status == 500


def test_context_manager_closes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"count": 1})

    from pyinreach import ApiKeyAuth, InboundClient

    with InboundClient(
        auth=ApiKeyAuth("k"),
        base_url="https://test.example",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.send_message(["100000000000001"], "t@e.com", "hi") == 1


def test_plaintext_base_url_is_rejected() -> None:
    """A real (un-mocked) http:// client would leak the API key in plaintext."""
    from pyinreach import ApiKeyAuth, ConfigurationError, InboundClient

    with pytest.raises(ConfigurationError):
        InboundClient(auth=ApiKeyAuth("k"), base_url="http://ipcinbound.example")
    # verify=False is the explicit opt-out for local, non-production testing.
    InboundClient(auth=ApiKeyAuth("k"), base_url="http://localhost:8080", verify=False).close()
