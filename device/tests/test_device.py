from unittest.mock import MagicMock, patch

import requests

import device


def test_generate_sensor_data_shape_and_range():
    for _ in range(50):
        data = device.generate_sensor_data()

        assert set(data.keys()) == {"device_id", "temperature"}
        assert data["device_id"] == device.DEVICE_ID
        assert 15 <= data["temperature"] <= 30
        # round(x, 2) means at most 2 digits after the decimal point.
        assert round(data["temperature"], 2) == data["temperature"]


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
