"""Tests for the POST /device-data endpoint."""

from unittest.mock import patch

import pytest


VALID_PAYLOAD = {"device_id": "sensor-1", "temperature": 21.5}


def test_valid_payload_is_forwarded_and_returns_cloud_response(client):
    """A valid payload with a patched successful send_to_cloud returns 200 and the forwarded body."""
    with patch("app.main.send_to_cloud", return_value={"status": "stored"}) as mock_send:
        response = client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json() == {
        "status": "forwarded",
        "cloud_response": {"status": "stored"}
    }
    mock_send.assert_called_once_with({"device_id": "sensor-1", "temperature": 21.5})


def test_empty_device_id_is_rejected_before_forwarding(client):
    """device_id="" fails validation with 422 and send_to_cloud is never called."""
    with patch("app.main.send_to_cloud") as mock_send:
        response = client.post(
            "/device-data",
            json={"device_id": "", "temperature": 21.5}
        )

    assert response.status_code == 422
    mock_send.assert_not_called()


def test_device_id_over_100_chars_is_rejected(client):
    """A 101-character device_id fails validation with 422."""
    with patch("app.main.send_to_cloud") as mock_send:
        response = client.post(
            "/device-data",
            json={"device_id": "a" * 101, "temperature": 21.5}
        )

    assert response.status_code == 422
    mock_send.assert_not_called()


@pytest.mark.parametrize("length", [1, 100])
def test_device_id_boundary_lengths_are_accepted(client, length):
    """device_id lengths of exactly 1 and exactly 100 characters pass validation."""
    with patch("app.main.send_to_cloud", return_value={"status": "stored"}) as mock_send:
        response = client.post(
            "/device-data",
            json={"device_id": "a" * length, "temperature": 21.5}
        )

    assert response.status_code == 200
    mock_send.assert_called_once()


def test_missing_temperature_is_rejected(client):
    """A payload missing the temperature field fails validation with 422."""
    with patch("app.main.send_to_cloud") as mock_send:
        response = client.post("/device-data", json={"device_id": "sensor-1"})

    assert response.status_code == 422
    mock_send.assert_not_called()


def test_non_numeric_temperature_is_rejected(client):
    """A non-numeric temperature string fails validation with 422."""
    with patch("app.main.send_to_cloud") as mock_send:
        response = client.post(
            "/device-data",
            json={"device_id": "sensor-1", "temperature": "not-a-number"}
        )

    assert response.status_code == 422
    mock_send.assert_not_called()


def test_send_to_cloud_exception_returns_502(client):
    """If send_to_cloud raises, the route returns 502 with the fixed detail message."""
    with patch("app.main.send_to_cloud", side_effect=RuntimeError("network down")):
        response = client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 502
    assert response.json() == {"detail": "Cloud service unavailable"}
