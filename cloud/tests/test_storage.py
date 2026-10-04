from app import storage


def test_save_and_get_all_data():
    # storage.stored_data is a module-level list, so reset it to keep this test isolated.
    storage.stored_data.clear()

    storage.save_sensor_data({"device_id": "sensor-1", "temperature": 22.5})
    storage.save_sensor_data({"device_id": "sensor-2", "temperature": 18.0})

    assert storage.get_all_data() == [
        {"device_id": "sensor-1", "temperature": 22.5},
        {"device_id": "sensor-2", "temperature": 18.0},
    ]


def test_get_all_data_empty_by_default():
    storage.stored_data.clear()

    assert storage.get_all_data() == []
