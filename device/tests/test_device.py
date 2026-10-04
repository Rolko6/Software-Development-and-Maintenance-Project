from unittest.mock import MagicMock, patch

import pytest
import requests

import device


@pytest.fixture(autouse=True)
def reset_fault_rates(monkeypatch):
    # Default every test to "always a normal reading" so unrelated tests aren't
    # flaky; a test that cares about a specific fault mode overrides one rate to 1.0.
    monkeypatch.setattr(device, "DISCONNECT_RATE", 0.0)
    monkeypatch.setattr(device, "ERROR_RATE", 0.0)
    monkeypatch.setattr(device, "STUCK_START_RATE", 0.0)
    monkeypatch.setattr(device, "_stuck_reads_remaining", 0)
    monkeypatch.setattr(device, "_current_temperature", 22.0)


def test_generate_sensor_data_shape_and_range():
    for _ in range(50):
        data = device.generate_sensor_data()

        assert set(data.keys()) == {"device_id", "temperature"}
        assert data["device_id"] == device.DEVICE_ID
        assert 15 <= data["temperature"] <= 30
        # round(x, 2) means at most 2 digits after the decimal point.
        assert round(data["temperature"], 2) == data["temperature"]


def test_read_sensor_returns_none_when_disconnected(monkeypatch):
    # Simulates a communication/bus failure: no reading at all this cycle.
    monkeypatch.setattr(device, "DISCONNECT_RATE", 1.0)

    assert device.read_sensor() is None
    assert device.generate_sensor_data() is None


def test_read_sensor_returns_error_sentinel(monkeypatch):
    # Sensor responded, but with a DS18B20 error value (85.0 or -127.0).
    monkeypatch.setattr(device, "ERROR_RATE", 1.0)

    reading = device.read_sensor()

    assert reading in device.ERROR_SENTINELS


def test_read_sensor_stuck_episode_repeats_same_value(monkeypatch):
    # Simulates a frozen sensor: same value returned for several consecutive reads.
    monkeypatch.setattr(device, "STUCK_START_RATE", 1.0)
    monkeypatch.setattr(device, "_current_temperature", 21.5)

    first = device.read_sensor()
    second = device.read_sensor()

    assert first == 21.5
    assert second == 21.5
    assert device._stuck_reads_remaining >= 0


@patch("device.requests.post")
def test_send_data_success_does_not_raise(mock_post):
    mock_post.return_value = MagicMock(status_code=200)

    device.send_data()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["device_id"] == device.DEVICE_ID
    assert kwargs["timeout"] == 5


@patch("device.requests.post")
def test_send_data_handles_request_exception(mock_post):
    # Gateway unreachable/timeout should be caught, not crash the device loop.
    mock_post.side_effect = requests.RequestException("connection refused")

    device.send_data()  # must not raise

    mock_post.assert_called_once()


@patch("device.requests.post")
def test_send_data_skips_when_sensor_disconnected(mock_post, monkeypatch):
    monkeypatch.setattr(device, "DISCONNECT_RATE", 1.0)

    device.send_data()

    mock_post.assert_not_called()
