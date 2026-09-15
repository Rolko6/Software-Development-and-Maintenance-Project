"""In-process end-to-end tests: a device-shaped payload through the gateway
to the real cloud app.

The gateway forwards over `requests`; here `requests.post` is monkeypatched
to call the cloud's own FastAPI app through `TestClient` (an httpx ASGI
transport under the hood) instead of a real socket, so the cloud's real
validation and storage are exercised without touching Docker or the network.
"""

import requests


DEVICE_PAYLOAD = {"device_id": "e2e-sensor-001", "temperature": 21.4}


def test_reading_lands_in_cloud_storage(monkeypatch, gateway_client, cloud_test_client):
    def fake_post(url, json=None, timeout=None):
        return cloud_test_client.post("/data", json=json)

    monkeypatch.setattr(requests, "post", fake_post)

    response = gateway_client.post("/device-data", json=DEVICE_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["status"] == "forwarded"

    stored = cloud_test_client.get("/data").json()
    assert DEVICE_PAYLOAD in stored


def test_cloud_outage_returns_502_and_reading_is_lost(monkeypatch, gateway_client, cloud_test_client):
    def fake_post(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("simulated outage")

    monkeypatch.setattr(requests, "post", fake_post)

    response = gateway_client.post("/device-data", json=DEVICE_PAYLOAD)

    # Matches the README's documented manual failure check exactly.
    assert response.status_code == 502
    assert response.json() == {"detail": "Cloud service unavailable"}

    # Residual risk this retry does not cover: the reading is not queued or
    # replayed once the retry budget is exhausted.
    assert cloud_test_client.get("/data").json() == []


def test_cloud_recovers_after_transient_outage(monkeypatch, gateway_client, cloud_test_client):
    """A cloud outage that clears within the retry budget still delivers the
    reading, unlike a full outage."""
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ConnectionError("simulated blip")
        return cloud_test_client.post("/data", json=json)

    monkeypatch.setattr(requests, "post", fake_post)

    response = gateway_client.post("/device-data", json=DEVICE_PAYLOAD)

    assert response.status_code == 200
    assert DEVICE_PAYLOAD in cloud_test_client.get("/data").json()
