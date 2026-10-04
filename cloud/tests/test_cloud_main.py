from fastapi.testclient import TestClient

from app.main import app
from app.storage import stored_data

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_post_data_stores_and_get_data_returns_it():
    # stored_data is shared module state, so reset it to keep this test isolated.
    stored_data.clear()

    payload = {"device_id": "sensor-1", "temperature": 22.5}
    post_response = client.post("/data", json=payload)

    assert post_response.status_code == 200
    assert post_response.json() == {"status": "stored"}

    get_response = client.get("/data")
    assert get_response.json() == [payload]


def test_data_model_has_no_device_id_length_limit():
    # Documents a known gap (see documentation/phases/v1.0.0.md, Section 4):
    # cloud's SensorData model is looser than gateway's — an empty device_id is accepted here.
    stored_data.clear()

    response = client.post("/data", json={"device_id": "", "temperature": 22.5})

    assert response.status_code == 200
