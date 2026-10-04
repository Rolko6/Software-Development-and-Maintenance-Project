from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.metrics import SENSOR_FAULT_READINGS_TOTAL

client = TestClient(app)


def test_metrics_endpoint_is_mounted():
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert b"sensor_fault_readings_total" in response.content


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
