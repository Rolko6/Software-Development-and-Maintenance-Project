# Generates simulated temperature readings and packages them as SensorReading
# instances.

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


def build_temperature_model(config: DeviceConfig) -> TemperatureModel:
    rng = random.Random(config.random_seed)

    if config.temperature_model == "random-walk":
        return RandomWalkTemperatureModel(
            config.temperature_min,
            config.temperature_max,
            rng
        )

    return UniformTemperatureModel(
        config.temperature_min,
        config.temperature_max,
        rng
    )


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
