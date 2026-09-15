"""Cloud API tests: health/readiness, storage, validation, retention."""

import importlib

import pytest


VALID_PAYLOAD = {"device_id": "sensor-001", "temperature": 22.5}


def test_health(cloud_test_client):
    response = cloud_test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_ready(cloud_test_client):
    response = cloud_test_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_openapi_schema_available(cloud_test_client):
    response = cloud_test_client.get("/openapi.json")
    assert response.status_code == 200


def test_post_data_stores_reading(cloud_test_client):
    response = cloud_test_client.post("/data", json=VALID_PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {"status": "stored"}


def test_get_data_returns_stored_reading(cloud_test_client):
    cloud_test_client.post("/data", json=VALID_PAYLOAD)
    response = cloud_test_client.get("/data")
    assert response.status_code == 200
    assert response.json() == [VALID_PAYLOAD]


def test_empty_device_id_rejected(cloud_test_client):
    response = cloud_test_client.post(
        "/data", json={"device_id": "", "temperature": 22.5}
    )
    assert response.status_code == 422


def test_device_id_too_long_rejected(cloud_test_client):
    response = cloud_test_client.post(
        "/data", json={"device_id": "x" * 101, "temperature": 22.5}
    )
    assert response.status_code == 422


def test_non_numeric_temperature_rejected(cloud_test_client):
    response = cloud_test_client.post(
        "/data", json={"device_id": "sensor-001", "temperature": "hot"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("temperature", [-273.15, -40.1, 60.1, 500])
def test_temperature_out_of_range_rejected(cloud_test_client, temperature):
    response = cloud_test_client.post(
        "/data", json={"device_id": "sensor-001", "temperature": temperature}
    )
    assert response.status_code == 422


def test_missing_fields_rejected(cloud_test_client):
    response = cloud_test_client.post("/data", json={"device_id": "sensor-001"})
    assert response.status_code == 422


# --- Storage isolation between tests --------------------------------------
# The autouse _reset_cloud_storage fixture in conftest.py must clear storage
# before/after every test. These two tests, run in file order, demonstrate
# it: the first stores a reading, the second finds storage empty again.

def test_a_reading_is_stored(cloud_test_client):
    cloud_test_client.post("/data", json=VALID_PAYLOAD)
    assert len(cloud_test_client.get("/data").json()) == 1


def test_b_storage_was_reset_since_previous_test(cloud_test_client):
    assert cloud_test_client.get("/data").json() == []


# --- Bounded retention -----------------------------------------------------

def test_storage_bounded_retention(cloud_main):
    storage = importlib.import_module("cloud_app.storage")
    limit = storage.MAX_STORED_READINGS  # set to 5 for tests; see conftest.py

    for i in range(limit + 3):
        storage.save_sensor_data({"device_id": f"sensor-{i}", "temperature": 20.0})

    stored = storage.get_all_data()

    assert len(stored) == limit
    # Oldest entries evicted first-in-first-out; most recent retained.
    assert stored[0]["device_id"] == "sensor-3"
    assert stored[-1]["device_id"] == f"sensor-{limit + 2}"


def test_get_data_still_returns_a_plain_list(cloud_test_client):
    # Compatibility: GET /data must still behave like a plain JSON array,
    # not exposing the deque internally used for bounded retention.
    cloud_test_client.post("/data", json=VALID_PAYLOAD)
    response = cloud_test_client.get("/data")
    assert isinstance(response.json(), list)
