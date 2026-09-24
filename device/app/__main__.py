# Entry point: builds the configuration, wires the sensor/client/runner
# together, and runs the device's send loop.

import logging
import sys

from app.config import DeviceConfig
from app.gateway_client import GatewayClient
from app.runner import SensorRunner
from app.sensor import TemperatureSensor, build_temperature_model


def main() -> None:
    # Configure logging before parsing config so a ValueError below is
    # reported through the normal log stream rather than a bare traceback.
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        config = DeviceConfig.from_env()
    except ValueError as error:
        logger.error("Invalid device configuration: %s", error)
        sys.exit(1)

    logging.getLogger().setLevel(config.log_level.upper())

    model = build_temperature_model(config)

    sensor = TemperatureSensor(
        device_id=config.device_id,
        model=model
    )

    client = GatewayClient(
        url=config.gateway_url,
        timeout=config.request_timeout_seconds
    )

    runner = SensorRunner(
        sensor=sensor,
        client=client,
        interval_seconds=config.send_interval_seconds
    )

    runner.install_signal_handlers()
    runner.run_forever()


if __name__ == "__main__":
    main()
