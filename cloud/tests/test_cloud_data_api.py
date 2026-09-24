import pytest

from app.storage import get_all_data


def test_post_data_with_valid_payload_returns_200_and_stored_status(client):
    """POST /data with a valid payload returns 200 and {"status": "stored"}."""
    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": 21.0},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "stored"}


def test_post_data_with_valid_payload_is_saved_to_storage(client):
    """After a valid POST /data, the reading is present in app.storage.get_all_data()."""
    payload = {"device_id": "sensor-1", "temperature": 21.0}
    client.post("/data", json=payload)
    assert payload in get_all_data()


def test_get_data_returns_empty_list_on_clean_store(client):
    """GET /data returns [] when no readings have been stored yet."""
    response = client.get("/data")
    assert response.status_code == 200
    assert response.json() == []


def test_get_data_returns_readings_in_insertion_order(client):
    """GET /data returns readings in the order they were posted."""
    payloads = [
        {"device_id": "sensor-a", "temperature": 10.0},
        {"device_id": "sensor-b", "temperature": 20.0},
        {"device_id": "sensor-c", "temperature": 30.0},
    ]
    for payload in payloads:
        client.post("/data", json=payload)

    response = client.get("/data")
    assert response.json() == payloads


def test_round_trip_two_readings_preserve_order_and_values(client):
    """Posting two readings and then GETting /data returns both, in order, with matching fields."""
    first = {"device_id": "sensor-x", "temperature": 15.5}
    second = {"device_id": "sensor-y", "temperature": 29.75}

    client.post("/data", json=first)
    client.post("/data", json=second)

    response = client.get("/data")
    data = response.json()

    assert data == [first, second]


@pytest.mark.parametrize(
    "payload",
    [
        {"temperature": 22.5},
        {"device_id": "sensor-1"},
    ],
    ids=["missing_device_id", "missing_temperature"],
)
def test_post_data_missing_required_field_returns_422(client, payload):
    """POST /data with device_id or temperature omitted returns 422 (pydantic validation error)."""
    response = client.post("/data", json=payload)
    assert response.status_code == 422


def test_post_data_temperature_as_numeric_string_is_coerced_to_float(client):
    """POST /data with temperature="22.5" (a string) is accepted and coerced to float 22.5."""
    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": "22.5"},
    )
    assert response.status_code == 200
    stored = get_all_data()
    assert stored[-1]["temperature"] == 22.5
    assert isinstance(stored[-1]["temperature"], float)


def test_post_data_with_empty_device_id_is_rejected(client):
    """POST /data with device_id="" returns 422: gateway and cloud validation
    rules are now aligned (device_id requires min_length=1)."""
    response = client.post(
        "/data",
        json={"device_id": "", "temperature": 22.5},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "temperature",
    [-40.0, 60.0],
    ids=["min_bound", "max_bound"],
)
def test_post_data_temperature_at_bounds_is_accepted(client, temperature):
    """POST /data with temperature at the inclusive bounds -40.0 or 60.0 is accepted."""
    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": temperature},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "temperature",
    [-40.1, 60.1],
    ids=["below_min", "above_max"],
)
def test_post_data_temperature_outside_bounds_returns_422(client, temperature):
    """POST /data with temperature just outside -40.0..60.0 returns 422."""
    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": temperature},
    )
    assert response.status_code == 422
