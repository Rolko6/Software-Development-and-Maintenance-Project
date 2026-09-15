"""Tests for SensorReading in app/models.py."""

from datetime import datetime, timezone

from app.models import SensorReading


def test_to_payload_has_exactly_device_id_and_temperature_keys():
    """to_payload() must carry only the two fields the legacy gateway
    contract accepts -- recorded_at never leaves the device process."""
    reading = SensorReading(
        device_id="sensor-1",
        temperature=21.5,
        recorded_at=datetime.now(timezone.utc)
    )

    payload = reading.to_payload()

    assert set(payload.keys()) == {"device_id", "temperature"}


def test_to_payload_device_id_matches_field():
    reading = SensorReading(
        device_id="sensor-7",
        temperature=18.0,
        recorded_at=datetime.now(timezone.utc)
    )

    assert reading.to_payload()["device_id"] == "sensor-7"


def test_to_payload_rounds_temperature_to_two_decimals():
    reading = SensorReading(
        device_id="sensor-1",
        temperature=21.23456,
        recorded_at=datetime.now(timezone.utc)
    )

    assert reading.to_payload()["temperature"] == 21.23


def test_to_payload_temperature_is_float():
    reading = SensorReading(
        device_id="sensor-1",
        temperature=20,
        recorded_at=datetime.now(timezone.utc)
    )

    assert isinstance(reading.to_payload()["temperature"], float)


def test_reading_is_frozen():
    reading = SensorReading(
        device_id="sensor-1",
        temperature=20.0,
        recorded_at=datetime.now(timezone.utc)
    )

    try:
        reading.temperature = 99.0
        assert False, "expected assignment to a frozen dataclass to raise"
    except Exception:
        pass
