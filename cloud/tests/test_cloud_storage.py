from app.storage import MAX_STORED_READINGS, get_all_data, save_sensor_data, stored_data


def test_get_all_data_on_empty_store_returns_empty_list():
    """get_all_data() on an empty store returns an empty list."""
    assert get_all_data() == []


def test_save_sensor_data_appends_to_storage():
    """save_sensor_data() appends the given dict to storage."""
    reading = {"device_id": "sensor-1", "temperature": 18.0}
    save_sensor_data(reading)
    assert get_all_data() == [reading]


def test_save_sensor_data_keeps_duplicate_readings_without_deduplication():
    """Repeated saves of identical dicts are all kept -- no de-duplication is performed."""
    reading = {"device_id": "sensor-1", "temperature": 18.0}
    save_sensor_data(reading)
    save_sensor_data(reading)
    save_sensor_data(reading)
    assert get_all_data() == [reading, reading, reading]


def test_get_all_data_returns_a_copy_not_the_live_internal_container():
    """get_all_data() returns a new list built from stored_data, so mutating
    the returned list does not affect storage -- this pins the fix for the
    aliasing bug the old test used to pin."""
    save_sensor_data({"device_id": "sensor-1", "temperature": 99.0})
    result = get_all_data()
    assert result is not stored_data

    result.append({"device_id": "sensor-2", "temperature": 1.0})
    assert get_all_data() == [{"device_id": "sensor-1", "temperature": 99.0}]


def test_save_sensor_data_drops_oldest_readings_beyond_max_stored_readings():
    """Storage is bounded by MAX_STORED_READINGS (backed by a
    collections.deque(maxlen=...)): saving more readings than the limit keeps
    only the most recent ones and drops the oldest."""
    total = MAX_STORED_READINGS + 5
    for i in range(total):
        save_sensor_data({"device_id": f"sensor-{i}", "temperature": float(i)})

    result = get_all_data()
    assert len(result) == MAX_STORED_READINGS
    assert result[0] == {"device_id": "sensor-5", "temperature": 5.0}
    assert result[-1] == {
        "device_id": f"sensor-{total - 1}",
        "temperature": float(total - 1),
    }
