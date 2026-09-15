"""Tests for the SensorData model in app/models.py."""

import pytest
from pydantic import ValidationError

from app.models import SensorData


def test_valid_payload_parses_into_sensor_data():
    """A well-formed device_id and temperature parse without error."""
    data = SensorData(device_id="sensor-1", temperature=21.5)

    assert data.device_id == "sensor-1"
    assert data.temperature == 21.5


def test_empty_device_id_raises_validation_error():
    """An empty device_id violates min_length=1 and raises ValidationError."""
    with pytest.raises(ValidationError):
        SensorData(device_id="", temperature=21.5)


def test_device_id_over_100_chars_raises_validation_error():
    """A 101-character device_id exceeds max_length=100 and raises ValidationError."""
    with pytest.raises(ValidationError):
        SensorData(device_id="a" * 101, temperature=21.5)


@pytest.mark.parametrize("length", [1, 100])
def test_device_id_boundary_lengths_are_accepted(length):
    """device_id lengths of exactly 1 and exactly 100 characters are both valid."""
    data = SensorData(device_id="a" * length, temperature=21.5)

    assert len(data.device_id) == length


def test_numeric_string_temperature_coerces_to_float():
    """A numeric string temperature such as "22.5" coerces to the float 22.5."""
    data = SensorData(device_id="sensor-1", temperature="22.5")

    assert data.temperature == 22.5
    assert isinstance(data.temperature, float)
