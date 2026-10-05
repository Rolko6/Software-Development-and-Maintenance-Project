from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.metrics import (
    CLOUD_FORWARD_ATTEMPTS_TOTAL,
    CLOUD_FORWARD_FAILURES_TOTAL,
    DEVICE_MESSAGES_TOTAL,
    SENSOR_FAULT_READINGS_TOTAL,
    SENSOR_STUCK_EPISODES_TOTAL,
)
from app.sensor_state import SENSOR_STATE

client = TestClient(app)


def test_health_returns_200():
    # Basic liveness check.
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@patch("app.main.send_to_cloud")
def test_device_data_valid_forwards_to_cloud(mock_send_to_cloud):
    # Cloud call is mocked so this test doesn't need a real cloud service running.
    mock_send_to_cloud.return_value = {"status": "stored"}

    payload = {"device_id": "sensor-1", "temperature": 22.5}
    response = client.post("/device-data", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "status": "forwarded",
        "cloud_response": {"status": "stored"},
    }
    mock_send_to_cloud.assert_called_once_with(payload)


def test_device_data_empty_device_id_rejected():
    # Pydantic validation (min_length=1) should reject this before cloud is ever called.
    response = client.post(
        "/device-data",
        json={"device_id": "", "temperature": 22.5},
    )

    assert response.status_code == 422


def test_device_data_missing_temperature_rejected():
    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1"},
    )

    assert response.status_code == 422


@patch("app.main.send_to_cloud")
def test_device_data_cloud_unreachable_returns_502(mock_send_to_cloud):
    # Simulates the cloud being down/unreachable.
    mock_send_to_cloud.side_effect = Exception("connection refused")

    attempts_before = CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get()
    failures_before = CLOUD_FORWARD_FAILURES_TOTAL._value.get()

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 22.5},
    )

    assert response.status_code == 502
    assert CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get() == attempts_before + 1
    assert CLOUD_FORWARD_FAILURES_TOTAL._value.get() == failures_before + 1


@pytest.mark.parametrize("temperature", ["NaN", "Infinity", "-Infinity"])
@patch("app.main.send_to_cloud")
def test_device_data_rejects_nonfinite_temperature_without_side_effects(
    mock_send_to_cloud,
    temperature,
):
    before = {
        "messages": DEVICE_MESSAGES_TOTAL._value.get(),
        "attempts": CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get(),
        "failures": CLOUD_FORWARD_FAILURES_TOTAL._value.get(),
        "stuck": SENSOR_STUCK_EPISODES_TOTAL._value.get(),
        "power_on_reset": SENSOR_FAULT_READINGS_TOTAL.labels(
            type="power_on_reset"
        )._value.get(),
        "crc_failure": SENSOR_FAULT_READINGS_TOTAL.labels(
            type="crc_failure"
        )._value.get(),
    }

    response = client.post(
        "/device-data",
        content=(
            '{"device_id":"nonfinite-sensor","temperature":'
            + temperature
            + "}"
        ),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert SENSOR_STATE.tracked_device_count() == 0
    assert DEVICE_MESSAGES_TOTAL._value.get() == before["messages"]
    assert CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get() == before["attempts"]
    assert CLOUD_FORWARD_FAILURES_TOTAL._value.get() == before["failures"]
    assert SENSOR_STUCK_EPISODES_TOTAL._value.get() == before["stuck"]
    assert (
        SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset")._value.get()
        == before["power_on_reset"]
    )
    assert (
        SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure")._value.get()
        == before["crc_failure"]
    )
    mock_send_to_cloud.assert_not_called()


@patch("app.main.send_to_cloud")
def test_device_status_is_recorded_without_cloud_forwarding(mock_send_to_cloud):
    response = client.post(
        "/device-status",
        json={"device_id": "sensor-1", "status": "disconnected"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "recorded"}
    mock_send_to_cloud.assert_not_called()


def test_device_status_rejects_unknown_status():
    response = client.post(
        "/device-status",
        json={"device_id": "sensor-1", "status": "stuck"},
    )

    assert response.status_code == 422


@patch("app.main.send_to_cloud")
def test_new_device_is_rejected_when_sensor_state_capacity_is_full(
    mock_send_to_cloud,
    monkeypatch,
):
    mock_send_to_cloud.return_value = {"status": "stored"}
    monkeypatch.setattr(SENSOR_STATE, "max_tracked_devices", 1)
    attempts_before = CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get()
    messages_before = DEVICE_MESSAGES_TOTAL._value.get()

    accepted = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 22.5},
    )
    rejected = client.post(
        "/device-data",
        json={"device_id": "sensor-2", "temperature": 22.5},
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 503
    assert rejected.json() == {"detail": "Sensor state capacity reached"}
    mock_send_to_cloud.assert_called_once()
    assert CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get() == attempts_before + 1
    assert DEVICE_MESSAGES_TOTAL._value.get() == messages_before + 2


# --- DS18B20-realistic boundary values (see documentation/phases/v1.0.0.md, Section 4/8) ---
# These document CURRENT behavior: the gateway has no range/sanity validation, so sensor
# error sentinels pass through unchanged. Expected to keep passing until v1.3.0 decides
# whether these should instead be rejected or flagged.

@patch("app.main.send_to_cloud")
def test_device_data_accepts_power_on_reset_sentinel(mock_send_to_cloud):
    # 85.0 = DS18B20's power-on-reset value (read happened before first conversion).
    mock_send_to_cloud.return_value = {"status": "stored"}

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 85.0},
    )

    assert response.status_code == 200


@patch("app.main.send_to_cloud")
def test_device_data_accepts_crc_failure_sentinel(mock_send_to_cloud):
    # -127.0 = common sentinel for a failed/corrupted DS18B20 read (CRC error, bad wiring).
    mock_send_to_cloud.return_value = {"status": "stored"}

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": -127.0},
    )

    assert response.status_code == 200


@patch("app.main.send_to_cloud")
def test_device_data_accepts_out_of_physical_range_temperature(mock_send_to_cloud):
    # DS18B20's physical range is -55..125 degrees C; anything outside that is a bad reading.
    mock_send_to_cloud.return_value = {"status": "stored"}

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 500.0},
    )

    assert response.status_code == 200
