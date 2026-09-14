import os
import random
import time

import requests


GATEWAY_URL = os.getenv(
    "GATEWAY_URL",
    "http://localhost:8000/device-data"
)


DEVICE_ID = os.getenv(
    "DEVICE_ID",
    "legacy-sensor-001"
)


def generate_sensor_data():
    return {
        "device_id": DEVICE_ID,
        "temperature": round(random.uniform(15, 30), 2)
    }


def send_data():
    data = generate_sensor_data()

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