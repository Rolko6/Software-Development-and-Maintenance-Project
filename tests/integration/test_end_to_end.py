"""End-to-end smoke tests against the running Docker Compose stack.

Every test here is marked `integration` and talks to the gateway (host port
8000) and cloud (host port 8001) services over real HTTP, as started by
`docker compose up`. They assume the `device` container is also running and
posting readings for `legacy-sensor-001` every five seconds, so assertions
against `GET /data` treat the response as a shared, growing list rather than
a fixture the test fully controls.
"""

import re
import time
import uuid

import pytest
import requests

pytestmark = pytest.mark.integration

METRIC_LINE_RE_TEMPLATE = r"^{name} (\S+)$"


def _unique_device_id() -> str:
    return f"ci-test-{uuid.uuid4().hex}"


def _parse_metric_value(metrics_text: str, metric_name: str) -> float:
    """Pull a Prometheus counter's current value out of the text exposition
    format with a small regex, rather than adding a parsing dependency.
    """

    pattern = METRIC_LINE_RE_TEMPLATE.format(name=re.escape(metric_name))
    match = re.search(pattern, metrics_text, re.MULTILINE)

    assert match is not None, (
        f"metric {metric_name!r} not found in metrics body:\n{metrics_text}"
    )

    return float(match.group(1))


def _count_readings_with_device_id(readings, device_id: str) -> int:
    return sum(1 for reading in readings if reading.get("device_id") == device_id)


def test_gateway_health_returns_ok(gateway_base_url):
    response = requests.get(f"{gateway_base_url}/health", timeout=5)

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_cloud_health_returns_ok(cloud_base_url):
    response = requests.get(f"{cloud_base_url}/health", timeout=5)

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_post_device_data_is_forwarded_to_cloud(gateway_base_url):
    device_id = _unique_device_id()
    payload = {"device_id": device_id, "temperature": 24.5}

    response = requests.post(
        f"{gateway_base_url}/device-data",
        json=payload,
        timeout=5,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "forwarded",
        "cloud_response": {"status": "stored"},
    }


def test_forwarded_reading_appears_in_cloud_data(gateway_base_url, cloud_base_url):
    device_id = _unique_device_id()
    temperature = 19.75
    payload = {"device_id": device_id, "temperature": temperature}

    post_response = requests.post(
        f"{gateway_base_url}/device-data",
        json=payload,
        timeout=5,
    )
    assert post_response.status_code == 200

    # The gateway forwards synchronously, so the reading should already be
    # visible; retry briefly to absorb any incidental scheduling jitter.
    readings = []
    for _ in range(10):
        data_response = requests.get(f"{cloud_base_url}/data", timeout=5)
        assert data_response.status_code == 200
        readings = data_response.json()

        if any(
            reading.get("device_id") == device_id
            and reading.get("temperature") == temperature
            for reading in readings
        ):
            break

        time.sleep(0.5)

    # The device simulator posts concurrently, so assert containment, never
    # equality, against the full list of readings.
    assert any(
        reading.get("device_id") == device_id
        and reading.get("temperature") == temperature
        for reading in readings
    ), f"expected reading for {device_id} not found in {readings!r}"


def test_post_device_data_with_empty_device_id_is_rejected(
    gateway_base_url, cloud_base_url
):
    before_response = requests.get(f"{cloud_base_url}/data", timeout=5)
    assert before_response.status_code == 200
    empty_id_count_before = _count_readings_with_device_id(before_response.json(), "")

    response = requests.post(
        f"{gateway_base_url}/device-data",
        json={"device_id": "", "temperature": 22.5},
        timeout=5,
    )

    assert response.status_code == 422

    after_response = requests.get(f"{cloud_base_url}/data", timeout=5)
    assert after_response.status_code == 200
    empty_id_count_after = _count_readings_with_device_id(after_response.json(), "")

    # The gateway must reject the reading before forwarding it, so the
    # rejected request itself adds nothing with an empty device id.
    assert empty_id_count_after == empty_id_count_before


def test_metrics_endpoint_exposes_counters_and_increments_on_valid_post(
    gateway_base_url,
):
    metrics_before_response = requests.get(f"{gateway_base_url}/metrics/", timeout=5)
    assert metrics_before_response.status_code == 200

    metrics_before_text = metrics_before_response.text
    assert "device_messages_total" in metrics_before_text
    assert "cloud_forward_failures_total" in metrics_before_text

    messages_before = _parse_metric_value(
        metrics_before_text, "device_messages_total"
    )

    post_response = requests.post(
        f"{gateway_base_url}/device-data",
        json={"device_id": _unique_device_id(), "temperature": 21.0},
        timeout=5,
    )
    assert post_response.status_code == 200

    metrics_after_response = requests.get(f"{gateway_base_url}/metrics/", timeout=5)
    assert metrics_after_response.status_code == 200

    messages_after = _parse_metric_value(
        metrics_after_response.text, "device_messages_total"
    )

    assert messages_after > messages_before


def test_simulated_device_reaches_cloud_end_to_end(cloud_base_url):
    # The device container posts a reading for "legacy-sensor-001" every
    # five seconds (see device/app/ and the README's architecture
    # section), so polling for up to ~30s gives it multiple opportunities
    # to appear without tying the test to a specific interval.
    deadline = time.monotonic() + 30
    readings = []

    while time.monotonic() < deadline:
        response = requests.get(f"{cloud_base_url}/data", timeout=5)
        assert response.status_code == 200
        readings = response.json()

        if any(
            reading.get("device_id") == "legacy-sensor-001" for reading in readings
        ):
            break

        time.sleep(1)

    assert any(
        reading.get("device_id") == "legacy-sensor-001" for reading in readings
    ), "no reading from legacy-sensor-001 arrived within 30s"
