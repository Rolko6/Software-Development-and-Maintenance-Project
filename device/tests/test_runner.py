"""Tests for SensorRunner in app/runner.py."""

from datetime import datetime, timezone

import pytest

from app.gateway_client import DeliveryResult
from app.models import SensorReading
from app.runner import SensorRunner


class FakeSensor:
    def __init__(self, readings=None, exception=None):
        self._readings = list(readings) if readings is not None else None
        self._exception = exception
        self.read_count = 0

    def read(self):
        self.read_count += 1

        if self._exception is not None:
            raise self._exception

        if self._readings is not None:
            return self._readings[(self.read_count - 1) % len(self._readings)]

        return SensorReading(
            device_id="sensor-1",
            temperature=20.0,
            recorded_at=datetime.now(timezone.utc)
        )


class FakeClient:
    def __init__(self, results=None, on_send=None):
        self._results = results
        self._on_send = on_send
        self.sent = []

    def send(self, reading):
        self.sent.append(reading)

        if self._on_send is not None:
            self._on_send(len(self.sent))

        if self._results is not None:
            return self._results[(len(self.sent) - 1) % len(self._results)]

        return DeliveryResult(delivered=True, status_code=200, error=None)


class FakeClock:
    """Fake monotonic() / sleep() pair: monotonic() advances by the amount
    of every recorded sleep, so elapsed time is deterministic."""

    def __init__(self, start=0.0):
        self.now = start
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_run_once_returns_delivered_result_and_logs_info(caplog):
    sensor = FakeSensor()
    client = FakeClient(results=[DeliveryResult(delivered=True, status_code=200, error=None)])
    runner = SensorRunner(sensor, client, interval_seconds=5.0)

    with caplog.at_level("INFO"):
        result = runner.run_once()

    assert result == DeliveryResult(delivered=True, status_code=200, error=None)
    assert len(client.sent) == 1
    assert any("Delivered" in message for message in caplog.messages)


def test_run_once_does_not_raise_when_delivery_fails_with_error(caplog):
    sensor = FakeSensor()
    client = FakeClient(results=[DeliveryResult(delivered=False, status_code=None, error="boom")])
    runner = SensorRunner(sensor, client, interval_seconds=5.0)

    with caplog.at_level("ERROR"):
        result = runner.run_once()  # must not raise

    assert result.delivered is False
    assert any("boom" in message for message in caplog.messages)


def test_run_once_does_not_raise_when_gateway_rejects_with_status_code(caplog):
    sensor = FakeSensor()
    client = FakeClient(results=[DeliveryResult(delivered=False, status_code=500, error=None)])
    runner = SensorRunner(sensor, client, interval_seconds=5.0)

    with caplog.at_level("WARNING"):
        result = runner.run_once()  # must not raise

    assert result.delivered is False
    assert any("500" in message for message in caplog.messages)


def test_run_forever_stops_via_stop_flag_and_sends_expected_number_of_times():
    sensor = FakeSensor()
    fake_clock = FakeClock()
    runner = SensorRunner(
        sensor,
        client=None,  # replaced below once the runner instance is known
        interval_seconds=1.0,
        sleep=fake_clock.sleep,
        monotonic=fake_clock.monotonic
    )

    def stop_after_third_send(send_count):
        if send_count >= 3:
            runner.stop()

    client = FakeClient(on_send=stop_after_third_send)
    runner._client = client

    runner.run_forever()

    assert len(client.sent) == 3


def test_run_forever_survives_a_failing_cycle_and_keeps_going(caplog):
    class ExplodingSensor:
        def __init__(self):
            self.calls = 0

        def read(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("sensor malfunction")
            return SensorReading(
                device_id="sensor-1",
                temperature=20.0,
                recorded_at=datetime.now(timezone.utc)
            )

    sensor = ExplodingSensor()
    fake_clock = FakeClock()
    runner = SensorRunner(
        sensor,
        client=None,
        interval_seconds=1.0,
        sleep=fake_clock.sleep,
        monotonic=fake_clock.monotonic
    )

    def stop_after_second_send(send_count):
        if send_count >= 1:
            runner.stop()

    client = FakeClient(on_send=stop_after_second_send)
    runner._client = client

    with caplog.at_level("ERROR"):
        runner.run_forever()  # must not raise despite the first cycle failing

    assert sensor.calls == 2
    assert len(client.sent) == 1
    assert "sensor malfunction" in caplog.text


def test_run_forever_paces_cycles_by_sleeping_remaining_interval():
    sensor = FakeSensor()
    fake_clock = FakeClock()
    runner = SensorRunner(
        sensor,
        client=None,
        interval_seconds=2.0,
        sleep=fake_clock.sleep,
        monotonic=fake_clock.monotonic
    )

    def stop_after_third_send(send_count):
        if send_count >= 3:
            runner.stop()

    client = FakeClient(on_send=stop_after_third_send)
    runner._client = client

    runner.run_forever()

    # Two full 2.0s cycles are paced out via sleep slices; the third cycle
    # requests stop during send, before any further sleeping happens.
    assert sum(fake_clock.sleeps) == pytest.approx(4.0)
