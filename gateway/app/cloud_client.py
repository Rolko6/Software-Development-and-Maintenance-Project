import base64
import json
import os
import time

import requests

from app.crypto import encapsulate, encrypt_payload
from app.keys import CLOUD_PUBLIC_KEY


CLOUD_URL = os.getenv(
    "CLOUD_URL",
    "http://localhost:8001/data/secure"
)


def send_to_cloud(sensor_data: dict):
    payload = dict(sensor_data)
    payload["timestamp"] = time.time()
    plaintext = json.dumps(payload).encode()

    shared_secret, kem_ciphertext = encapsulate(CLOUD_PUBLIC_KEY)
    nonce, ciphertext = encrypt_payload(shared_secret, plaintext)

    envelope = {
        "kem_ciphertext": base64.b64encode(kem_ciphertext).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }

    response = requests.post(
        CLOUD_URL,
        json=envelope,
        timeout=5
    )

    response.raise_for_status()

    return response.json()
