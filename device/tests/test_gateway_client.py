"""Tests for GatewayClient in app/gateway_client.py."""

from datetime import datetime, timezone

import requests

from app.gateway_client import DeliveryResult, GatewayClient
from app.models import SensorReading


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSession:
    """Minimal stand-in for requests.Session, recording calls and returning
    a scripted response or raising a scripted exception."""

    def __init__(self, response=None, raise_exception=None):
        self._response = response
        self._raise_exception = raise_exception
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append({
            "url": url,
            "json": json,
            "data": data,
            "headers": headers,
            "timeout": timeout
        })

        if self._raise_exception is not None:
            raise self._raise_exception

        return self._response


def _reading():
    return SensorReading(
        device_id="sensor-1",
        temperature=21.234,
        recorded_at=datetime.now(timezone.utc)
    )


def test_send_posts_the_two_key_payload_with_url_and_timeout():
    session = FakeSession(response=FakeResponse(200))
    client = GatewayClient(url="http://gateway/device-data", timeout=3.5, session=session)

    client.send(_reading())

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "http://gateway/device-data"
    assert call["timeout"] == 3.5
    assert call["json"] == {"device_id": "sensor-1", "temperature": 21.23}


def test_send_returns_delivered_true_on_2xx_status():
    session = FakeSession(response=FakeResponse(200))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading())

    assert result == DeliveryResult(delivered=True, status_code=200, error=None)


def test_send_returns_delivered_true_on_204():
    session = FakeSession(response=FakeResponse(204))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading())

    assert result.delivered is True
    assert result.status_code == 204


def test_send_returns_delivered_false_without_raising_on_http_error_status():
    """This is the fix for the documented limitation: a non-2xx response
    must be reported as a failed delivery, not printed/logged as success."""
    session = FakeSession(response=FakeResponse(500))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading())

    assert result.delivered is False
    assert result.status_code == 500
    assert result.error is None


def test_send_returns_delivered_false_on_404():
    session = FakeSession(response=FakeResponse(404))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading())

    assert result.delivered is False
    assert result.status_code == 404


def test_send_catches_request_exception_and_does_not_propagate():
    session = FakeSession(raise_exception=requests.RequestException("connection refused"))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading())  # must not raise

    assert result.delivered is False
    assert result.status_code is None
    assert result.error == "connection refused"


def _reading_with(temperature):
    return SensorReading(
        device_id="broken-sensor",
        temperature=temperature,
        recorded_at=datetime.now(timezone.utc)
    )


def test_finite_reading_is_still_sent_as_json():
    """Normal readings keep the exact legacy request: json=, no raw body."""
    session = FakeSession(response=FakeResponse(200))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    client.send(_reading_with(-127.0))

    call = session.calls[0]
    assert call["json"] == {"device_id": "broken-sensor", "temperature": -127.0}
    assert call["data"] is None


def test_nan_reading_is_sent_as_raw_json_the_way_sensor_firmware_would():
    """requests refuses to encode NaN (InvalidJSONError), which the device
    used to report as a network failure. Firmware that prints the float
    sends the NaN token anyway, so the simulator does the same."""
    session = FakeSession(response=FakeResponse(422))
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    client.send(_reading_with(float("nan")))

    call = session.calls[0]
    assert call["json"] is None
    assert call["data"] == '{"device_id": "broken-sensor", "temperature": NaN}'
    assert call["headers"] == {"Content-Type": "application/json"}


class RejectingGatewayAdapter(requests.adapters.BaseAdapter):
    """Stands in for the network under a real requests.Session: records the
    encoded body and answers 422 like the gateway does for a NaN reading."""

    def __init__(self):
        super().__init__()
        self.bodies = []

    def send(self, request, **kwargs):
        self.bodies.append(request.body)

        response = requests.Response()
        response.status_code = 422
        response.request = request
        return response

    def close(self):
        pass


def test_nan_reading_reaches_the_gateway_through_a_real_requests_session():
    """With a real requests.Session the NaN reading is actually encoded and
    sent, and the gateway's 422 comes back as a rejection (logged as WARNING
    by the runner) rather than as a connection error."""
    adapter = RejectingGatewayAdapter()
    session = requests.Session()
    session.mount("http://", adapter)
    client = GatewayClient(url="http://gateway/device-data", timeout=5, session=session)

    result = client.send(_reading_with(float("nan")))

    assert result == DeliveryResult(delivered=False, status_code=422, error=None)
    assert adapter.bodies == ['{"device_id": "broken-sensor", "temperature": NaN}']


def test_client_defaults_to_a_requests_session_when_none_given():
    client = GatewayClient(url="http://gateway/device-data", timeout=5)

    assert isinstance(client._session, requests.Session)
