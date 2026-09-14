# Initially, this sends data normally.
# Later, this will become the place where ML-KEM is integrated.

import os

import requests


CLOUD_URL = os.getenv(
    "CLOUD_URL",
    "http://localhost:8001/data"
)


def send_to_cloud(sensor_data: dict):
    response = requests.post(
        CLOUD_URL,
        json=sensor_data,
        timeout=5
    )

    response.raise_for_status()

    return response.json()