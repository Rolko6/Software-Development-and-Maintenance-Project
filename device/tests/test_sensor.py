"""Tests for app/sensor.py: temperature models, the factory, and
TemperatureSensor."""

import random
from datetime import datetime, timezone

from app.config import DeviceConfig
from app.sensor import (
    RandomWalkTemperatureModel,
    TemperatureSensor,
    UniformTemperatureModel,
    build_temperature_model,
)


def _config(**overrides):
    env = {
        "TEMPERATURE_MIN": "15",
        "TEMPERATURE_MAX": "30",
        "TEMPERATURE_MODEL": "uniform",
    }
    env.update(overrides)
    return DeviceConfig.from_env(env)


def test_uniform_model_stays_within_bounds_over_many_samples():
    """Mirrors the original device.py check: 200 samples, all within
    [min, max]."""
    model = UniformTemperatureModel(15.0, 30.0, random.Random(1))

    for _ in range(200):
        value = model.next_value()
        assert 15.0 <= value <= 30.0


def test_random_walk_model_starts_mid_range():
    """The first value returned must be within one step of the midpoint,
    since the model starts at (min + max) / 2 and then takes one step."""
    model = RandomWalkTemperatureModel(20.0, 30.0, random.Random(1))

    midpoint = 25.0
    first_value = model.next_value()

    assert abs(first_value - midpoint) <= RandomWalkTemperatureModel.STEP_SIZE


def test_random_walk_model_stays_clamped_to_bounds_over_many_samples():
    """A narrow range with many seeded steps should trigger clamping at
    both ends and never escape [minimum, maximum]."""
    model = RandomWalkTemperatureModel(20.0, 20.5, random.Random(7))

    for _ in range(500):
        value = model.next_value()
        assert 20.0 <= value <= 20.5


def test_build_temperature_model_selects_uniform_by_default():
    config = _config()

    model = build_temperature_model(config)

    assert isinstance(model, UniformTemperatureModel)


def test_build_temperature_model_selects_random_walk():
    config = _config(TEMPERATURE_MODEL="random-walk")

    model = build_temperature_model(config)

    assert isinstance(model, RandomWalkTemperatureModel)


def test_build_temperature_model_is_deterministic_with_seed():
    config = _config(RANDOM_SEED="123")

    model_a = build_temperature_model(config)
    model_b = build_temperature_model(config)

    values_a = [model_a.next_value() for _ in range(5)]
    values_b = [model_b.next_value() for _ in range(5)]

    assert values_a == values_b


def test_sensor_read_returns_reading_with_device_id_and_rounded_temperature():
    model = UniformTemperatureModel(15.0, 30.0, random.Random(1))
    fixed_time = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

    sensor = TemperatureSensor(
        device_id="sensor-9",
        model=model,
        clock=lambda: fixed_time
    )

    reading = sensor.read()

    assert reading.device_id == "sensor-9"
    assert round(reading.temperature, 2) == reading.temperature
    assert 15.0 <= reading.temperature <= 30.0
    assert reading.recorded_at == fixed_time


def test_sensor_read_uses_default_clock_when_none_given():
    model = UniformTemperatureModel(15.0, 30.0, random.Random(1))
    sensor = TemperatureSensor(device_id="sensor-1", model=model)

    before = datetime.now(timezone.utc)
    reading = sensor.read()
    after = datetime.now(timezone.utc)

    assert before <= reading.recorded_at <= after
