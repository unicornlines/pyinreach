# pyinreach

A typed, dependency-light Python client for the **Garmin inReach IPC**
(inReach Portal Connect) API. It implements both halves of the interface:

- **Inbound** (your app → device): send text / binary / media messages, request
  locations, control tracking, and handle emergencies.
- **Outbound** (device → your web service): parse the JSON events Garmin pushes
  to your webhook, and authenticate those requests.

> **Unofficial.** This is a community project and is not affiliated with,
> sponsored by, or endorsed by Garmin Ltd. "Garmin" and "inReach" are
> trademarks of their respective owners.

## Why this library

- **Secure by default** — TLS verification on, credentials never logged,
  constant-time webhook token checks, strict input validation, and bounded
  payload parsing. See [`THREAT_MODEL.md`](THREAT_MODEL.md).
- **Reliable** — a deliberate retry policy that retries safe failures
  (HTTP 429, connection errors) but **never silently re-sends** a
  money-spending command on an ambiguous failure.
- **Deterministic** — no hidden randomness, all timestamps normalised to UTC,
  pure validators, and an injectable clock so back-off is testable.
- **Efficient** — one pooled, keep-alive connection reused across calls; frozen
  dataclasses with `__slots__`.
- **Fully typed** — ships `py.typed`; `mypy --strict` clean.

## Installation

```bash
pip install pyinreach
```

Requires Python 3.10+. The only runtime dependency is
[`httpx`](https://www.python-httpx.org/).

## Authentication

The inbound API uses an API key (header `X-API-Key`). Generate one from the
Garmin Explore site (Admin Controls → Portal Connect → *Generate API Key*).
Legacy `.svc` deployments use HTTP Basic auth instead.

```python
from pyinreach import ApiKeyAuth, BasicAuth

auth = ApiKeyAuth("your-api-key")          # IPC Inbound v2 (recommended)
auth = BasicAuth("username", "password")   # legacy .svc services
```

## Sending to a device (Inbound)

```python
from pyinreach import InboundClient, ApiKeyAuth, Coordinate, ReferencePoint, BinaryType

with InboundClient(auth=ApiKeyAuth("your-api-key")) as client:
    # A plain text message (160-char limit, validated locally first).
    client.send_message(
        recipients=["300234010571020"],
        sender="dispatch@example.com",
        text="Weather looks good for the jump.",
    )

    # A text message carrying a reference point.
    client.send_message(
        recipients=["300234010571020"],
        sender="dispatch@example.com",
        text="Meet at the cabin",
        reference_point=ReferencePoint(coordinate=Coordinate(47.42, 10.98), label="cabin"),
    )

    # Binary (<= 268 bytes once decoded).
    client.send_binary(["300234010571020"], b"\x01\x02\x03", BinaryType.GENERIC)

    # Tracking control.
    client.enable_tracking("300234010571020", interval=300)   # seconds
    client.disable_tracking("300234010571020")

    # Location.
    last = client.last_known_location(["300234010571020"])    # no cost
    client.request_location(["300234010571020"])              # sends a command

    # Emergency.
    if client.get_respondent():
        client.acknowledge_emergency("300234010571020")
        client.send_emergency_message("300234010571020", "Help is on the way.")
```

Each command that reaches a device **costs money**, so every model validates its
inputs on construction — an invalid `Message`, `Coordinate`, etc. raises
`ValidationError` before any network call happens.

### Error handling

```python
from pyinreach import (
    InboundClient, ApiKeyAuth,
    AuthenticationError, RateLimitError, UnprocessableError, ServerError,
    TransportError, ValidationError,
)

try:
    client.send_message(["300234010571020"], "d@example.com", "hi")
except ValidationError as e:
    ...  # caught locally, nothing was sent (e.code is the API error code)
except RateLimitError as e:
    ...  # HTTP 429; e.retry_after holds the server hint (already honoured on retry)
except UnprocessableError as e:
    ...  # HTTP 422; e.code, e.description, e.imeis describe the rejection
except AuthenticationError:
    ...  # HTTP 401 / 403
except ServerError:
    ...  # HTTP 500 / 501
except TransportError:
    ...  # network / TLS / timeout
```

## Receiving from a device (Outbound)

Garmin POSTs JSON to a web service you host. `parse_events` decodes it into
typed objects (event schema v2/v3/v4). Unknown message codes are preserved as
integers, and the original payload is kept losslessly in `.raw`.

```python
from pyinreach import parse_events, MessageCode

batch = parse_events(request_body)          # str, bytes, or an already-parsed dict
for event in batch:
    print(event.imei, event.message_code_name, event.free_text)
    if event.message_code == MessageCode.FREE_TEXT and event.point:
        print(event.point.latitude, event.point.longitude)
    if event.timestamp:                     # UTC datetime
        print(event.timestamp.isoformat())
    if event.media_bytes:                   # v4 media event
        audio = event.decoded_media()
```

### Authenticating the webhook

```python
from pyinreach import verify_static_token, parse_bearer_token

token = parse_bearer_token(headers.get("Authorization"))
if not verify_static_token(token, expected="your-shared-secret"):
    raise PermissionError("rejected")       # constant-time comparison
```

## Using it in Django

The library is framework-agnostic. A minimal pattern for the use case of
"friends log in, see my location, and exchange texts":

```python
# views.py
import json
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from pyinreach import (
    InboundClient, ApiKeyAuth, parse_events,
    parse_bearer_token, verify_static_token, ParseError,
)

# Build the client once and reuse it (it pools connections).
client = InboundClient(auth=ApiKeyAuth(settings.INREACH_API_KEY))


@csrf_exempt
def inreach_webhook(request):
    """Receives device → server pushes (IPC Outbound)."""
    token = parse_bearer_token(request.headers.get("Authorization"))
    if not verify_static_token(token, expected=settings.INREACH_WEBHOOK_TOKEN):
        return HttpResponseForbidden()
    try:
        batch = parse_events(request.body)
    except ParseError:
        return HttpResponse(status=400)     # anything but 200 makes Garmin retry

    for event in batch:
        # Persist location/messages; trigger subsystems (e.g. a METAR lookup)
        # when event.free_text matches a command you recognise.
        store_event(event)
    return HttpResponse(status=200)          # 200 = "received", stops retries


def send_text(request):
    """Server → device (IPC Inbound), e.g. replying with a requested METAR."""
    client.send_message(
        recipients=[settings.INREACH_IMEI],
        sender=request.user.email,
        text=request.POST["text"],
    )
    return JsonResponse({"ok": True})
```

Notes for that design:

- Respond to the webhook with **HTTP 200** only once you have durably stored the
  event; any other status causes Garmin to retry (see the retry/suspend schedule
  in the Outbound guide).
- Keep webhook handling fast; do heavy work (METAR fetch, etc.) asynchronously.
- The 160-character message limit is enforced for you — split long replies.
- Store the API key and webhook token in settings/secrets, never in code.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # test suite (network-free, uses httpx MockTransport)
ruff check .      # lint
mypy              # type-check (strict)
```

## License

[MIT](LICENSE).
