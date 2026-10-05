import os
import random
import time
from urllib.parse import urlsplit, urlunsplit

import requests


GATEWAY_URL = os.getenv(
    "GATEWAY_URL",
    "http://localhost:8000/device-data"
)


def _derive_status_url(gateway_url):
    parsed = urlsplit(gateway_url)
    reading_path = parsed.path.rstrip("/")
    parent_path = reading_path.rsplit("/", 1)[0]
    status_path = f"{parent_path}/device-status"
    return urlunsplit((parsed.scheme, parsed.netloc, status_path, "", ""))


DEVICE_STATUS_URL = os.getenv(
    "DEVICE_STATUS_URL",
    _derive_status_url(GATEWAY_URL)
)


DEVICE_ID = os.getenv(
    "DEVICE_ID",
    "legacy-sensor-001"
)


# Fault-injection rates, simulating a real DS18B20's known failure modes.
# Each read_sensor() call rolls once against these (mutually exclusive, in order):
# disconnected > error sentinel > stuck-episode start > normal reading.
ERROR_RATE = float(os.getenv("ERROR_RATE", "0.01"))
DISCONNECT_RATE = float(os.getenv("DISCONNECT_RATE", "0.02"))
STUCK_START_RATE = float(os.getenv("STUCK_START_RATE", "0.03"))

# DS18B20 error sentinels: 85.0 = power-on-reset (read before conversion),
# -127.0 = CRC/communication failure.
ERROR_SENTINELS = [85.0, -127.0]

_current_temperature = round(random.uniform(15, 30), 2)
_stuck_reads_remaining = 0


def read_sensor():
    """Simulate one DS18B20 read. Returns a temperature, an error sentinel,
    or None if the sensor didn't respond at all (communication failure)."""
    global _current_temperature, _stuck_reads_remaining

    if _stuck_reads_remaining > 0:
        _stuck_reads_remaining -= 1
        return _current_temperature

    roll = random.random()

    if roll < DISCONNECT_RATE:
        return None

    if roll < DISCONNECT_RATE + ERROR_RATE:
        return random.choice(ERROR_SENTINELS)

    if roll < DISCONNECT_RATE + ERROR_RATE + STUCK_START_RATE:
        _stuck_reads_remaining = random.randint(3, 8) - 1
        return _current_temperature

    _current_temperature = round(
        min(30.0, max(15.0, _current_temperature + random.uniform(-0.3, 0.3))),
        2
    )
    return _current_temperature


def generate_sensor_data():
    """Return a reading payload, or None for send_data() to report status."""
    temperature = read_sensor()

    if temperature is None:
        return None

    return {
        "device_id": DEVICE_ID,
        "temperature": temperature
    }


def send_data():
    data = generate_sensor_data()

    if data is None:
        status = {
            "device_id": DEVICE_ID,
            "status": "disconnected"
        }

        try:
            response = requests.post(
                DEVICE_STATUS_URL,
                json=status,
                timeout=5
            )
            print(
                f"Sensor read failed (disconnected) | "
                f"Status response: {response.status_code}"
            )
        except requests.RequestException as error:
            print(f"Failed to send device status: {error}")
        return

    try:
        response = requests.post(
            GATEWAY_URL,
            json=data,
            timeout=5
        )

        print(
            f"Sent data: {data} | "
            f"Response: {response.status_code}"
        )

    except requests.RequestException as error:
        print(f"Failed to send data: {error}")


if __name__ == "__main__":
    while True:
        send_data()
        time.sleep(5)
