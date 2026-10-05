import pytest

from app.sensor_state import (
    SensorStateCapacityError,
    SensorStateTracker,
    _sensor_state_from_environment,
)


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def tracker(clock):
    return SensorStateTracker(clock=clock)


def test_third_identical_normal_reading_starts_one_stuck_episode(tracker):
    assert tracker.record_reading("sensor-1", 21.5, is_normal=True) is False
    assert tracker.record_reading("sensor-1", 21.5, is_normal=True) is False
    assert tracker.record_reading("sensor-1", 21.5, is_normal=True) is True
    assert tracker.record_reading("sensor-1", 21.5, is_normal=True) is False
    assert tracker.suspected_stuck_count() == 1


def test_changed_value_clears_stuck_and_allows_later_episode(tracker):
    for _ in range(3):
        tracker.record_reading("sensor-1", 21.5, is_normal=True)

    assert tracker.record_reading("sensor-1", 21.6, is_normal=True) is False
    assert tracker.suspected_stuck_count() == 0
    assert tracker.record_reading("sensor-1", 21.6, is_normal=True) is False
    assert tracker.record_reading("sensor-1", 21.6, is_normal=True) is True


def test_disconnect_clears_stuck_and_normal_reading_recovers(tracker):
    for _ in range(3):
        tracker.record_reading("sensor-1", 21.5, is_normal=True)

    tracker.record_disconnect("sensor-1")

    assert tracker.suspected_stuck_count() == 0
    assert tracker.disconnected_count() == 1

    tracker.record_reading("sensor-1", 21.6, is_normal=True)

    assert tracker.disconnected_count() == 0


def test_sentinel_interrupts_identical_normal_sequence(tracker):
    tracker.record_reading("sensor-1", 21.5, is_normal=True)
    tracker.record_reading("sensor-1", 21.5, is_normal=True)
    tracker.record_reading("sensor-1", 85.0, is_normal=False)

    assert tracker.record_reading("sensor-1", 21.5, is_normal=True) is False
    assert tracker.suspected_stuck_count() == 0


def test_silence_is_evaluated_from_current_monotonic_time(tracker, clock):
    tracker.record_reading("sensor-1", 21.5, is_normal=True)

    clock.now = 29.9
    assert tracker.silent_count() == 0

    clock.now = 30.0
    assert tracker.silent_count() == 1


def test_disconnect_and_network_silence_remain_distinct(tracker, clock):
    tracker.record_disconnect("sensor-1")

    assert tracker.disconnected_count() == 1
    assert tracker.silent_count() == 0

    clock.now = 30.0

    assert tracker.disconnected_count() == 1
    assert tracker.silent_count() == 1


def test_devices_are_tracked_independently(tracker):
    for _ in range(3):
        tracker.record_reading("sensor-1", 21.5, is_normal=True)
    tracker.record_reading("sensor-2", 21.5, is_normal=True)

    assert tracker.suspected_stuck_count() == 1

    tracker.record_reading("sensor-1", 21.6, is_normal=True)

    assert tracker.suspected_stuck_count() == 0


def test_registry_rejects_new_device_at_capacity_but_accepts_known_device(clock):
    tracker = SensorStateTracker(max_tracked_devices=1, clock=clock)
    tracker.record_reading("sensor-1", 21.5, is_normal=True)

    tracker.record_disconnect("sensor-1")

    with pytest.raises(SensorStateCapacityError):
        tracker.record_reading("sensor-2", 22.0, is_normal=True)


def test_tracker_configuration_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("SENSOR_STUCK_THRESHOLD", "4")
    monkeypatch.setenv("SENSOR_SILENCE_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("SENSOR_STATE_MAX_DEVICES", "7")

    configured = _sensor_state_from_environment()

    assert configured.stuck_threshold == 4
    assert configured.silence_timeout_seconds == 12.5
    assert configured.max_tracked_devices == 7


def test_tracker_configuration_defaults(monkeypatch):
    for name in (
        "SENSOR_STUCK_THRESHOLD",
        "SENSOR_SILENCE_TIMEOUT_SECONDS",
        "SENSOR_STATE_MAX_DEVICES",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = _sensor_state_from_environment()

    assert configured.stuck_threshold == 3
    assert configured.silence_timeout_seconds == 30.0
    assert configured.max_tracked_devices == 1000


@pytest.mark.parametrize("threshold", ["0", "1", "-2"])
def test_environment_rejects_too_small_stuck_threshold(monkeypatch, threshold):
    monkeypatch.setenv("SENSOR_STUCK_THRESHOLD", threshold)

    with pytest.raises(ValueError, match="stuck_threshold"):
        _sensor_state_from_environment()


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "-inf"])
def test_environment_rejects_nonpositive_or_nonfinite_timeout(monkeypatch, timeout):
    monkeypatch.setenv("SENSOR_SILENCE_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValueError, match="finite and positive"):
        _sensor_state_from_environment()
