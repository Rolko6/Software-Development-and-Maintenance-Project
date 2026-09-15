"""Gateway API tests: validation, forwarding, retry/backoff, readiness.

Cloud is never actually contacted here -- `requests.post`/`requests.get`
(imported inside gateway/app/cloud_client.py) are monkeypatched at the
function boundary, matching the "mocked at the HTTP boundary" option for
in-process testing. tests/reliability/test_end_to_end.py additionally routes
through the real cloud app.
"""

from unittest.mock import Mock

import pytest
import requests

from conftest import counter_value

VALID_PAYLOAD = {"device_id": "sensor-001", "temperature": 22.5}


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = {} if json_data is None else json_data
        self.text = text or str(self._json_data)

    def json(self):
        return self._json_data


# --- Liveness / readiness --------------------------------------------

def test_health(gateway_client):
    response = gateway_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_ready_when_cloud_reachable(monkeypatch, gateway_client):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200))
    response = gateway_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_when_cloud_unreachable(monkeypatch, gateway_client):
    def raise_connection_error(*args, **kwargs):
        raise requests.exceptions.ConnectionError("simulated outage")

    monkeypatch.setattr(requests, "get", raise_connection_error)
    response = gateway_client.get("/ready")
    assert response.status_code == 503


def test_openapi_schema_available(gateway_client):
    # Regression guard for the sys.modules aliasing in conftest.py: OpenAPI
    # generation (and any pydantic model rebuild) must not depend on the
    # bare "app" module name still being present in sys.modules.
    response = gateway_client.get("/openapi.json")
    assert response.status_code == 200


# --- Validation --------------------------------------------------------

def test_empty_device_id_rejected(gateway_client):
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "", "temperature": 22.5}
    )
    assert response.status_code == 422


def test_device_id_too_long_rejected(gateway_client):
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "x" * 101, "temperature": 22.5}
    )
    assert response.status_code == 422


def test_device_id_max_length_accepted(monkeypatch, gateway_client):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: FakeResponse(200, {"status": "stored"})
    )
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "x" * 100, "temperature": 22.5}
    )
    assert response.status_code == 200


def test_missing_device_id_field(gateway_client):
    response = gateway_client.post("/device-data", json={"temperature": 22.5})
    assert response.status_code == 422


def test_missing_temperature_field(gateway_client):
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "sensor-001"}
    )
    assert response.status_code == 422


def test_non_numeric_temperature_rejected(gateway_client):
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "sensor-001", "temperature": "hot"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("temperature", [22, 22.5, "22.5"])
def test_temperature_accepts_int_float_and_numeric_string(
    monkeypatch, gateway_client, temperature
):
    # Legacy wire-contract check: pydantic v2's existing lax coercion for
    # numeric types must keep working after adding the ge/le range bounds.
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: FakeResponse(200, {"status": "stored"})
    )
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "sensor-001", "temperature": temperature}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("temperature", [-273.15, -40.1, 60.1, 500])
def test_temperature_out_of_range_rejected(gateway_client, temperature):
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "sensor-001", "temperature": temperature}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("temperature", [-40, -40.0, 60, 60.0])
def test_temperature_boundary_values_accepted(monkeypatch, gateway_client, temperature):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: FakeResponse(200, {"status": "stored"})
    )
    response = gateway_client.post(
        "/device-data",
        json={"device_id": "sensor-001", "temperature": temperature}
    )
    assert response.status_code == 200


def test_invalid_payload_does_not_increment_device_messages_counter(gateway_client):
    import gateway_app.metrics as gateway_metrics

    before = counter_value(gateway_metrics.DEVICE_MESSAGES_TOTAL)
    gateway_client.post("/device-data", json={"device_id": "", "temperature": 22.5})
    after = counter_value(gateway_metrics.DEVICE_MESSAGES_TOTAL)

    assert after == before


# --- Valid forwarding ----------------------------------------------------

def test_valid_reading_forwarded(monkeypatch, gateway_client):
    import gateway_app.metrics as gateway_metrics

    mock_post = Mock(return_value=FakeResponse(200, {"status": "stored"}))
    monkeypatch.setattr(requests, "post", mock_post)

    before = counter_value(gateway_metrics.DEVICE_MESSAGES_TOTAL)
    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)
    after = counter_value(gateway_metrics.DEVICE_MESSAGES_TOTAL)

    assert response.status_code == 200
    assert response.json() == {
        "status": "forwarded",
        "cloud_response": {"status": "stored"}
    }
    assert after == before + 1
    assert mock_post.call_count == 1


# --- Cloud failure and retry behaviour ------------------------------------

def test_cloud_failure_returns_502_and_increments_failure_counter(
    monkeypatch, gateway_client
):
    import gateway_app.metrics as gateway_metrics

    mock_post = Mock(side_effect=requests.exceptions.ConnectionError("down"))
    monkeypatch.setattr(requests, "post", mock_post)

    before = counter_value(gateway_metrics.CLOUD_FORWARD_FAILURES_TOTAL)
    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)
    after = counter_value(gateway_metrics.CLOUD_FORWARD_FAILURES_TOTAL)

    # Documented behaviour (README manual failure check): exact status and
    # body are preserved across the retry-adding change.
    assert response.status_code == 502
    assert response.json() == {"detail": "Cloud service unavailable"}
    # One failed request increments the failure counter once, regardless of
    # how many attempts were made internally.
    assert after == before + 1


def test_retry_recovers_after_transient_connection_errors(monkeypatch, gateway_client):
    mock_post = Mock(side_effect=[
        requests.exceptions.ConnectionError("down"),
        requests.exceptions.ConnectionError("down"),
        FakeResponse(200, {"status": "stored"}),
    ])
    monkeypatch.setattr(requests, "post", mock_post)

    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert mock_post.call_count == 3


def test_retry_on_cloud_5xx_then_success(monkeypatch, gateway_client):
    mock_post = Mock(side_effect=[
        FakeResponse(503, text="temporarily overloaded"),
        FakeResponse(200, {"status": "stored"}),
    ])
    monkeypatch.setattr(requests, "post", mock_post)

    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert mock_post.call_count == 2


def test_retry_exhausted_after_max_attempts(monkeypatch, gateway_client):
    mock_post = Mock(side_effect=requests.exceptions.ConnectionError("down"))
    monkeypatch.setattr(requests, "post", mock_post)

    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 502
    # CLOUD_FORWARD_MAX_ATTEMPTS default/test value is 3.
    assert mock_post.call_count == 3


def test_no_retry_on_4xx_cloud_rejection(monkeypatch, gateway_client):
    # Simulates the cloud rejecting a reading the gateway itself would have
    # accepted (e.g. validation drift) -- must not be retried, and must be
    # reported distinctly from an availability failure.
    mock_post = Mock(return_value=FakeResponse(400, text="rejected by cloud"))
    monkeypatch.setattr(requests, "post", mock_post)

    response = gateway_client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 422
    assert mock_post.call_count == 1


def test_retry_stops_when_time_budget_exhausted(monkeypatch, gateway_main):
    """The retry loop must not keep scheduling attempts past its total
    wall-clock budget, so it cannot outlive the caller's own timeout.

    Calls send_to_cloud() directly rather than through the HTTP stack:
    TestClient runs the ASGI app on a background anyio event loop that
    itself depends on a working time.monotonic(), so patching it process-
    wide while going through TestClient is unreliable.
    """
    import gateway_app.cloud_client as cloud_client

    mock_post = Mock(side_effect=requests.exceptions.ConnectionError("down"))
    monkeypatch.setattr(requests, "post", mock_post)

    # Fake clock: small, real-looking elapsed time through the deadline
    # computation, the first attempt's remaining-budget check, and the
    # post-attempt backoff check -- then reports the budget exhausted at
    # the remaining-budget check for what would be the second attempt.
    calls = {"n": 0}
    real_budget = cloud_client.CLOUD_FORWARD_TOTAL_BUDGET_SECONDS
    timeline = [0.0, 0.1, 0.2]

    def fake_monotonic():
        idx = calls["n"]
        calls["n"] += 1
        if idx < len(timeline):
            return timeline[idx]
        return real_budget + 1

    monkeypatch.setattr(cloud_client.time, "monotonic", fake_monotonic)

    with pytest.raises(cloud_client.CloudUnavailable):
        cloud_client.send_to_cloud(VALID_PAYLOAD)

    # Only the first attempt ran; the second was never started because the
    # budget was already spent by the time its turn came.
    assert mock_post.call_count == 1
