# Generates simulated temperature readings and packages them as SensorReading
# instances.

import math
import random
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from app.config import DeviceConfig
from app.models import SensorReading


class TemperatureModel(Protocol):
    def next_value(self) -> float:
        ...


class UniformTemperatureModel:
    """Draws each reading independently from a uniform distribution, matching
    the original device.py behaviour: random.uniform(min, max)."""

    def __init__(self, minimum: float, maximum: float, rng: random.Random):
        self._minimum = minimum
        self._maximum = maximum
        self._rng = rng

    def next_value(self) -> float:
        return self._rng.uniform(self._minimum, self._maximum)


class RandomWalkTemperatureModel:
    """Starts mid-range and takes small steps, clamped to [minimum, maximum]."""

    STEP_SIZE = 0.5

    def __init__(self, minimum: float, maximum: float, rng: random.Random):
        self._minimum = minimum
        self._maximum = maximum
        self._rng = rng
        self._value = (minimum + maximum) / 2

    def next_value(self) -> float:
        step = self._rng.uniform(-self.STEP_SIZE, self.STEP_SIZE)
        candidate = self._value + step

        self._value = min(max(candidate, self._minimum), self._maximum)

        return self._value


# Values a DS18B20 reports when something is wrong rather than a temperature:
# DallasTemperature's DEVICE_DISCONNECTED_C for a missing or unwired sensor,
# and the sensor's own power-on reset register value, read back when the
# conversion never ran (e.g. after a brown-out).
DISCONNECTED_C = -127.0
POWER_ON_RESET_C = 85.0


class DS18B20TemperatureModel:
    """A DS18B20 on an Arduino: the true temperature drifts slowly (a random
    walk), the sensor reads it with a fixed calibration error of up to
    +-0.5C, and reports it in 12-bit steps of 0.0625C."""

    RESOLUTION = 0.0625
    MAX_CALIBRATION_OFFSET = 0.5

    def __init__(self, minimum: float, maximum: float, rng: random.Random):
        # Drawn once: a given physical sensor is consistently off by the same
        # amount, it does not jitter by up to 0.5C between readings.
        self._calibration_offset = rng.uniform(
            -self.MAX_CALIBRATION_OFFSET,
            self.MAX_CALIBRATION_OFFSET
        )
        self._true_temperature = RandomWalkTemperatureModel(minimum, maximum, rng)

    def next_value(self) -> float:
        measured = self._true_temperature.next_value() + self._calibration_offset

        return round(measured / self.RESOLUTION) * self.RESOLUTION


class FaultInjectingModel:
    """Wraps any temperature model and, per reading, replaces its value with a
    typical hardware fault at the configured rates: a disconnected sensor
    (-127), a power-on reset value (85), a failed read (NaN), or a stuck
    sensor repeating one value for several readings.

    One random draw per reading picks at most one fault; the rates are
    consecutive slices of [0, 1), and anything past them is a normal reading.
    """

    STUCK_MIN_READINGS = 5
    STUCK_MAX_READINGS = 20

    def __init__(
        self,
        inner: TemperatureModel,
        rng: random.Random,
        disconnect_rate: float = 0.0,
        power_on_reset_rate: float = 0.0,
        nan_rate: float = 0.0,
        stuck_rate: float = 0.0
    ):
        self._inner = inner
        self._rng = rng
        self._disconnect_rate = disconnect_rate
        self._power_on_reset_rate = power_on_reset_rate
        self._nan_rate = nan_rate
        self._stuck_rate = stuck_rate
        self._stuck_value = 0.0
        self._stuck_remaining = 0

    def next_value(self) -> float:
        # The real temperature keeps changing whatever the sensor reports, so
        # the inner model advances on every reading, faulty or not.
        value = self._inner.next_value()

        if self._stuck_remaining > 0:
            self._stuck_remaining -= 1
            return self._stuck_value

        roll = self._rng.random()

        threshold = self._disconnect_rate
        if roll < threshold:
            return DISCONNECTED_C

        threshold += self._power_on_reset_rate
        if roll < threshold:
            return POWER_ON_RESET_C

        threshold += self._nan_rate
        if roll < threshold:
            return math.nan

        threshold += self._stuck_rate
        if roll < threshold:
            # This reading is the first of the stuck run.
            self._stuck_value = value
            self._stuck_remaining = self._rng.randint(
                self.STUCK_MIN_READINGS,
                self.STUCK_MAX_READINGS
            ) - 1

        return value


def build_temperature_model(config: DeviceConfig) -> TemperatureModel:
    rng = random.Random(config.random_seed)

    if config.temperature_model == "ds18b20":
        model = DS18B20TemperatureModel(
            config.temperature_min,
            config.temperature_max,
            rng
        )
    elif config.temperature_model == "random-walk":
        model = RandomWalkTemperatureModel(
            config.temperature_min,
            config.temperature_max,
            rng
        )
    else:
        model = UniformTemperatureModel(
            config.temperature_min,
            config.temperature_max,
            rng
        )

    fault_rates = {
        "disconnect_rate": config.fault_disconnect_rate,
        "power_on_reset_rate": config.fault_power_on_reset_rate,
        "nan_rate": config.fault_nan_rate,
        "stuck_rate": config.fault_stuck_rate
    }

    # Only wrap when asked to, so the default device is exactly the model it
    # always was.
    if any(rate > 0 for rate in fault_rates.values()):
        return FaultInjectingModel(model, rng, **fault_rates)

    return model


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TemperatureSensor:
    def __init__(
        self,
        device_id: str,
        model: TemperatureModel,
        clock: Optional[Callable[[], datetime]] = None
    ):
        self._device_id = device_id
        self._model = model
        self._clock = clock if clock is not None else _utc_now

    def read(self) -> SensorReading:
        return SensorReading(
            device_id=self._device_id,
            temperature=round(self._model.next_value(), 2),
            recorded_at=self._clock()
        )
