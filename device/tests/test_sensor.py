"""Tests for app/sensor.py: temperature models, the factory, and
TemperatureSensor."""

import math
import random
from datetime import datetime, timezone

from app.config import DeviceConfig
from app.sensor import (
    DISCONNECTED_C,
    POWER_ON_RESET_C,
    DS18B20TemperatureModel,
    FaultInjectingModel,
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


class CountingModel:
    """Returns 1.0, 2.0, 3.0, ... so a repeated value can only come from the
    fault layer, never from the model itself."""

    def __init__(self):
        self.calls = 0

    def next_value(self) -> float:
        self.calls += 1
        return float(self.calls)


def test_ds18b20_values_are_multiples_of_its_0_0625_resolution():
    model = DS18B20TemperatureModel(15.0, 30.0, random.Random(3))

    for _ in range(500):
        value = model.next_value()
        assert (value / DS18B20TemperatureModel.RESOLUTION).is_integer()


def test_ds18b20_stays_within_range_plus_its_calibration_error():
    """The true temperature stays in [min, max]; the reported value may be
    off by the fixed calibration offset (at most +-0.5C) plus rounding."""
    model = DS18B20TemperatureModel(20.0, 21.0, random.Random(5))
    margin = (
        DS18B20TemperatureModel.MAX_CALIBRATION_OFFSET
        + DS18B20TemperatureModel.RESOLUTION / 2
    )

    for _ in range(500):
        value = model.next_value()
        assert 20.0 - margin <= value <= 21.0 + margin


def test_ds18b20_changes_gradually_rather_than_jumping_across_the_range():
    model = DS18B20TemperatureModel(15.0, 30.0, random.Random(8))
    max_change = (
        RandomWalkTemperatureModel.STEP_SIZE
        + DS18B20TemperatureModel.RESOLUTION
    )

    previous = model.next_value()
    for _ in range(500):
        value = model.next_value()
        assert abs(value - previous) <= max_change
        previous = value


def test_fault_layer_with_zero_rates_passes_readings_through_unchanged():
    model = FaultInjectingModel(CountingModel(), random.Random(1))

    assert [model.next_value() for _ in range(5)] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_disconnect_rate_of_one_always_reports_minus_127():
    model = FaultInjectingModel(CountingModel(), random.Random(1), disconnect_rate=1.0)

    assert [model.next_value() for _ in range(20)] == [DISCONNECTED_C] * 20


def test_power_on_reset_rate_of_one_always_reports_85():
    model = FaultInjectingModel(CountingModel(), random.Random(1), power_on_reset_rate=1.0)

    assert [model.next_value() for _ in range(20)] == [POWER_ON_RESET_C] * 20


def test_nan_rate_of_one_always_reports_nan():
    model = FaultInjectingModel(CountingModel(), random.Random(1), nan_rate=1.0)

    assert all(math.isnan(model.next_value()) for _ in range(20))


def test_stuck_fault_repeats_one_value_for_several_readings():
    model = FaultInjectingModel(CountingModel(), random.Random(1), stuck_rate=1.0)

    readings = [model.next_value() for _ in range(FaultInjectingModel.STUCK_MIN_READINGS)]

    assert readings == [1.0] * FaultInjectingModel.STUCK_MIN_READINGS


def test_true_temperature_keeps_changing_while_the_sensor_is_stuck():
    """When the stuck run ends, the next value is the current true
    temperature, not the one right after the frozen value."""
    inner = CountingModel()
    model = FaultInjectingModel(inner, random.Random(1), stuck_rate=1.0)

    readings = [model.next_value() for _ in range(FaultInjectingModel.STUCK_MAX_READINGS + 1)]
    run_length = next(i for i, value in enumerate(readings) if value != readings[0])

    assert FaultInjectingModel.STUCK_MIN_READINGS <= run_length <= FaultInjectingModel.STUCK_MAX_READINGS
    assert readings[run_length] == float(run_length + 1)


def test_fault_rate_is_roughly_honoured_over_many_readings():
    model = FaultInjectingModel(CountingModel(), random.Random(11), disconnect_rate=0.1)

    faults = sum(model.next_value() == DISCONNECTED_C for _ in range(10000))

    assert 800 <= faults <= 1200


def test_build_temperature_model_selects_ds18b20():
    model = build_temperature_model(_config(TEMPERATURE_MODEL="ds18b20"))

    assert isinstance(model, DS18B20TemperatureModel)


def test_build_temperature_model_wraps_the_model_only_when_a_fault_rate_is_set():
    model = build_temperature_model(
        _config(TEMPERATURE_MODEL="ds18b20", FAULT_DISCONNECT_RATE="0.05")
    )

    assert isinstance(model, FaultInjectingModel)


def test_build_temperature_model_with_faults_is_deterministic_with_seed():
    config = _config(
        TEMPERATURE_MODEL="ds18b20",
        RANDOM_SEED="7",
        FAULT_DISCONNECT_RATE="0.2",
        FAULT_STUCK_RATE="0.2",
    )

    model_a = build_temperature_model(config)
    model_b = build_temperature_model(config)

    assert [model_a.next_value() for _ in range(50)] == [model_b.next_value() for _ in range(50)]


def test_sensor_read_passes_a_nan_fault_through_without_crashing():
    model = FaultInjectingModel(CountingModel(), random.Random(1), nan_rate=1.0)
    sensor = TemperatureSensor(device_id="broken-sensor", model=model)

    assert math.isnan(sensor.read().temperature)


def test_sensor_read_uses_default_clock_when_none_given():
    model = UniformTemperatureModel(15.0, 30.0, random.Random(1))
    sensor = TemperatureSensor(device_id="sensor-1", model=model)

    before = datetime.now(timezone.utc)
    reading = sensor.read()
    after = datetime.now(timezone.utc)

    assert before <= reading.recorded_at <= after
