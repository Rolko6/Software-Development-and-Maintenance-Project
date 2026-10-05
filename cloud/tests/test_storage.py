import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import storage


def test_save_and_get_all_data():
    storage.save_sensor_data({"device_id": "sensor-1", "temperature": 22.5})
    storage.save_sensor_data({"device_id": "sensor-2", "temperature": 18.0})

    assert storage.get_all_data() == [
        {"device_id": "sensor-1", "temperature": 22.5},
        {"device_id": "sensor-2", "temperature": 18.0},
    ]


def test_get_all_data_empty_by_default():
    assert storage.get_all_data() == []


@pytest.mark.parametrize("database_path", ["", "   ", ":memory:", " :memory: "])
def test_database_path_rejects_transient_sqlite_storage(monkeypatch, database_path):
    monkeypatch.setenv("CLOUD_DB_PATH", database_path)

    with pytest.raises(RuntimeError, match="must name a durable database file"):
        storage._database_path()


def test_data_survives_a_fresh_process(tmp_path):
    database_path = tmp_path / "persistent-readings.sqlite3"
    cloud_directory = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["CLOUD_DB_PATH"] = str(database_path)

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.storage import save_sensor_data; "
                "save_sensor_data({'device_id': 'restart-check', 'temperature': 19.75})"
            ),
        ],
        cwd=cloud_directory,
        env=environment,
        check=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from app.storage import get_all_data; "
                "print(json.dumps(get_all_data()))"
            ),
        ],
        cwd=cloud_directory,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        '[{"device_id": "restart-check", "temperature": 19.75}]'
    )


def test_insert_uses_parameters_for_payload_values():
    payload = {
        "device_id": "sensor'); DROP TABLE readings; --",
        "temperature": 22.5,
    }

    storage.save_sensor_data(payload)

    assert storage.get_all_data() == [payload]


def test_concurrent_writes_use_independent_connections():
    readings = [
        {"device_id": f"sensor-{index}", "temperature": float(index)}
        for index in range(20)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(storage.save_sensor_data, readings))

    assert sorted(
        storage.get_all_data(), key=lambda reading: reading["device_id"]
    ) == sorted(readings, key=lambda reading: reading["device_id"])


def test_write_failure_is_raised_and_does_not_store_a_row(monkeypatch, tmp_path):
    database_path = tmp_path / "failed-write.sqlite3"
    monkeypatch.setenv("CLOUD_DB_PATH", str(database_path))
    assert storage.get_all_data() == []

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_readings
            BEFORE INSERT ON readings
            BEGIN
                SELECT RAISE(FAIL, 'simulated write failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="simulated write failure"):
        storage.save_sensor_data(
            {"device_id": "should-not-persist", "temperature": 20.0}
        )

    assert storage.get_all_data() == []


def test_database_open_failure_is_raised(monkeypatch, tmp_path):
    directory_path = tmp_path / "not-a-database"
    directory_path.mkdir()
    monkeypatch.setenv("CLOUD_DB_PATH", str(directory_path))

    with pytest.raises(sqlite3.OperationalError):
        storage.save_sensor_data({"device_id": "sensor-1", "temperature": 20.0})
