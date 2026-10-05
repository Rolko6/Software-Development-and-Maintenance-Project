"""In-memory sensor state used to derive gateway reliability metrics."""

from dataclasses import dataclass
import math
import os
import threading
import time
from collections.abc import Callable


@dataclass
class _DeviceState:
    last_contact: float
    disconnected: bool = False
    last_normal_temperature: float | None = None
    identical_normal_readings: int = 0
    suspected_stuck: bool = False


class SensorStateCapacityError(RuntimeError):
    """Raised when a new device would exceed the bounded state registry."""


class SensorStateTracker:
    """Track current sensor state without exposing device IDs as metric labels."""

    def __init__(
        self,
        *,
        stuck_threshold: int = 3,
        silence_timeout_seconds: float = 30.0,
        max_tracked_devices: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if stuck_threshold < 2:
            raise ValueError("stuck_threshold must be at least 2")
        if (
            not math.isfinite(silence_timeout_seconds)
            or silence_timeout_seconds <= 0
        ):
            raise ValueError("silence_timeout_seconds must be finite and positive")
        if max_tracked_devices <= 0:
            raise ValueError("max_tracked_devices must be positive")

        self.stuck_threshold = stuck_threshold
        self.silence_timeout_seconds = silence_timeout_seconds
        self.max_tracked_devices = max_tracked_devices
        self._clock = clock
        self._devices: dict[str, _DeviceState] = {}
        self._lock = threading.Lock()

    def record_reading(
        self,
        device_id: str,
        temperature: float,
        *,
        is_normal: bool,
    ) -> bool:
        """Record contact and return True only when a new stuck episode starts."""
        now = self._clock()

        with self._lock:
            state = self._devices.get(device_id)
            if state is None:
                self._check_capacity()
                state = _DeviceState(last_contact=now)
                self._devices[device_id] = state

            state.last_contact = now
            state.disconnected = False

            if not is_normal:
                self._clear_stuck_state(state)
                return False

            if state.last_normal_temperature == temperature:
                state.identical_normal_readings += 1
            else:
                state.last_normal_temperature = temperature
                state.identical_normal_readings = 1
                state.suspected_stuck = False

            if (
                state.identical_normal_readings >= self.stuck_threshold
                and not state.suspected_stuck
            ):
                state.suspected_stuck = True
                return True

            return False

    def record_disconnect(self, device_id: str) -> None:
        """Record an explicit failed sensor read as recent device contact."""
        now = self._clock()

        with self._lock:
            state = self._devices.get(device_id)
            if state is None:
                self._check_capacity()
                state = _DeviceState(last_contact=now)
                self._devices[device_id] = state

            state.last_contact = now
            state.disconnected = True
            self._clear_stuck_state(state)

    def disconnected_count(self) -> int:
        with self._lock:
            return sum(state.disconnected for state in self._devices.values())

    def suspected_stuck_count(self) -> int:
        with self._lock:
            return sum(state.suspected_stuck for state in self._devices.values())

    def tracked_device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    def silent_count(self) -> int:
        now = self._clock()
        with self._lock:
            return sum(
                now - state.last_contact >= self.silence_timeout_seconds
                for state in self._devices.values()
            )

    def clear(self) -> None:
        """Clear process-local state, primarily for deterministic tests."""
        with self._lock:
            self._devices.clear()

    @staticmethod
    def _clear_stuck_state(state: _DeviceState) -> None:
        state.last_normal_temperature = None
        state.identical_normal_readings = 0
        state.suspected_stuck = False

    def _check_capacity(self) -> None:
        if len(self._devices) >= self.max_tracked_devices:
            raise SensorStateCapacityError(
                f"sensor state capacity of {self.max_tracked_devices} devices reached"
            )


def _sensor_state_from_environment() -> SensorStateTracker:
    return SensorStateTracker(
        stuck_threshold=int(os.getenv("SENSOR_STUCK_THRESHOLD", "3")),
        silence_timeout_seconds=float(
            os.getenv("SENSOR_SILENCE_TIMEOUT_SECONDS", "30")
        ),
        max_tracked_devices=int(os.getenv("SENSOR_STATE_MAX_DEVICES", "1000")),
    )


SENSOR_STATE = _sensor_state_from_environment()
