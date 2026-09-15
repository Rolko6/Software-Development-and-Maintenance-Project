# Schedules periodic sensor reads and gateway deliveries, and shuts down
# gracefully on SIGTERM/SIGINT so `docker compose stop` does not have to wait
# for the kill timeout.

import logging
import signal
import time
from typing import Callable

from app.gateway_client import DeliveryResult, GatewayClient
from app.sensor import TemperatureSensor


logger = logging.getLogger(__name__)


# Sleep in slices no longer than this so a stop signal is noticed quickly
# even while a cycle is "waiting out" the rest of its interval.
MAX_SLEEP_SLICE_SECONDS = 0.5


class SensorRunner:
    def __init__(
        self,
        sensor: TemperatureSensor,
        client: GatewayClient,
        interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic
    ):
        self._sensor = sensor
        self._client = client
        self._interval_seconds = interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def install_signal_handlers(self) -> None:
        def _handle_signal(signum, frame):
            logger.info("Received signal %s, shutting down", signum)
            self.stop()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    def run_once(self) -> DeliveryResult:
        reading = self._sensor.read()
        result = self._client.send(reading)

        if result.delivered:
            logger.info(
                "Delivered reading device_id=%s temperature=%.2f status_code=%s",
                reading.device_id,
                reading.temperature,
                result.status_code
            )
        elif result.error is not None:
            logger.error(
                "Failed to deliver reading device_id=%s temperature=%.2f error=%s",
                reading.device_id,
                reading.temperature,
                result.error
            )
        else:
            logger.warning(
                "Gateway rejected reading device_id=%s temperature=%.2f status_code=%s",
                reading.device_id,
                reading.temperature,
                result.status_code
            )

        return result

    def run_forever(self) -> None:
        self._stop_requested = False

        while not self._stop_requested:
            cycle_start = self._monotonic()

            try:
                self.run_once()
            except Exception:
                logger.exception("Unexpected error during sensor cycle")

            self._sleep_until_next_cycle(cycle_start)

    def _sleep_until_next_cycle(self, cycle_start: float) -> None:
        deadline = cycle_start + self._interval_seconds

        while not self._stop_requested:
            remaining = deadline - self._monotonic()

            if remaining <= 0:
                return

            self._sleep(min(remaining, MAX_SLEEP_SLICE_SECONDS))
