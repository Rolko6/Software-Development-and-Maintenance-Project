from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

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

    response = client.post(
        "/device-data",
        json={"device_id": "sensor-1", "temperature": 22.5},
    )

    assert response.status_code == 502


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
