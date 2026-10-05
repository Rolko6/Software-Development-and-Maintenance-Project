from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.metrics import (
    CLOUD_FORWARD_ATTEMPTS_TOTAL,
    CLOUD_FORWARD_FAILURES_TOTAL,
    SENSOR_FAULT_READINGS_TOTAL,
    SENSOR_READ_FAILURES_TOTAL,
    SENSOR_STUCK_EPISODES_TOTAL,
)
from app.sensor_state import SENSOR_STATE

client = TestClient(app)


def test_metrics_endpoint_is_mounted():
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert b"sensor_fault_readings_total" in response.content


def test_known_sentinel_label_series_are_initialized():
    SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset").reset()
    SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure").reset()

    response = client.get("/metrics/")

    assert b'sensor_fault_readings_total{type="power_on_reset"} 0.0' in response.content
    assert b'sensor_fault_readings_total{type="crc_failure"} 0.0' in response.content


@patch("app.main.send_to_cloud")
def test_power_on_reset_sentinel_increments_fault_counter(mock_send_to_cloud):
    mock_send_to_cloud.return_value = {"status": "stored"}
    before = SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset")._value.get()

    client.post("/device-data", json={"device_id": "sensor-1", "temperature": 85.0})

    assert SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset")._value.get() == before + 1


@patch("app.main.send_to_cloud")
def test_crc_failure_sentinel_increments_fault_counter(mock_send_to_cloud):
    mock_send_to_cloud.return_value = {"status": "stored"}
    before = SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure")._value.get()

    client.post("/device-data", json={"device_id": "sensor-1", "temperature": -127.0})

    assert SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure")._value.get() == before + 1


@patch("app.main.send_to_cloud")
def test_normal_temperature_does_not_increment_fault_counter(mock_send_to_cloud):
    mock_send_to_cloud.return_value = {"status": "stored"}
    before_reset = SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset")._value.get()
    before_crc = SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure")._value.get()

    client.post("/device-data", json={"device_id": "sensor-1", "temperature": 21.5})

    assert SENSOR_FAULT_READINGS_TOTAL.labels(type="power_on_reset")._value.get() == before_reset
    assert SENSOR_FAULT_READINGS_TOTAL.labels(type="crc_failure")._value.get() == before_crc


@patch("app.main.send_to_cloud")
def test_stuck_episode_counter_increments_once_per_episode(mock_send_to_cloud):
    mock_send_to_cloud.return_value = {"status": "stored"}
    before = SENSOR_STUCK_EPISODES_TOTAL._value.get()
    payload = {"device_id": "sensor-1", "temperature": 21.5}

    for _ in range(4):
        response = client.post("/device-data", json=payload)
        assert response.status_code == 200

    assert SENSOR_STUCK_EPISODES_TOTAL._value.get() == before + 1

    client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 21.6},
    )
    for _ in range(2):
        client.post(
            "/device-data",
            json={"device_id": "sensor-1", "temperature": 21.6},
        )

    assert SENSOR_STUCK_EPISODES_TOTAL._value.get() == before + 2


def test_repeated_disconnect_reports_increment_failure_counter():
    before = SENSOR_READ_FAILURES_TOTAL._value.get()
    payload = {"device_id": "sensor-1", "status": "disconnected"}

    assert client.post("/device-status", json=payload).status_code == 200
    assert client.post("/device-status", json=payload).status_code == 200

    assert SENSOR_READ_FAILURES_TOTAL._value.get() == before + 2


@patch("app.main.send_to_cloud")
def test_current_disconnected_and_stuck_gauges_recover(mock_send_to_cloud):
    mock_send_to_cloud.return_value = {"status": "stored"}
    disconnected = {"device_id": "sensor-1", "status": "disconnected"}
    client.post("/device-status", json=disconnected)

    metrics = client.get("/metrics/").content
    assert b"sensor_disconnected_devices 1.0" in metrics
    assert b"sensor_suspected_stuck_devices 0.0" in metrics

    reading = {"device_id": "sensor-1", "temperature": 21.5}
    for _ in range(3):
        client.post("/device-data", json=reading)

    metrics = client.get("/metrics/").content
    assert b"sensor_disconnected_devices 0.0" in metrics
    assert b"sensor_suspected_stuck_devices 1.0" in metrics

    client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 21.6},
    )

    metrics = client.get("/metrics/").content
    assert b"sensor_suspected_stuck_devices 0.0" in metrics


@patch("app.main.send_to_cloud")
def test_silent_gauge_uses_time_at_each_scrape(mock_send_to_cloud, monkeypatch):
    mock_send_to_cloud.return_value = {"status": "stored"}
    now = [100.0]
    monkeypatch.setattr(SENSOR_STATE, "_clock", lambda: now[0])
    client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 21.5},
    )

    assert b"sensor_silent_devices 0.0" in client.get("/metrics/").content

    now[0] = 130.0

    assert b"sensor_silent_devices 1.0" in client.get("/metrics/").content


@patch("app.main.send_to_cloud")
def test_failed_cloud_forward_counts_attempt_and_failure(mock_send_to_cloud):
    mock_send_to_cloud.side_effect = RuntimeError("cloud unavailable")
    attempts_before = CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get()
    failures_before = CLOUD_FORWARD_FAILURES_TOTAL._value.get()

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 21.5},
    )

    assert response.status_code == 502
    assert CLOUD_FORWARD_ATTEMPTS_TOTAL._value.get() == attempts_before + 1
    assert CLOUD_FORWARD_FAILURES_TOTAL._value.get() == failures_before + 1
