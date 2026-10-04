import base64
import json
import logging
import time

from fastapi import FastAPI, HTTPException

from app.crypto import decapsulate, decrypt_payload
from app.keys import PRIVATE_KEY
from app.models import SecureEnvelope, SensorData
from app.storage import (
    save_sensor_data,
    get_all_data
)


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# How long a /data/secure request's embedded timestamp stays acceptable.
# Older requests are rejected as possible replays. See documentation/phases/v2.0.0.md.
REPLAY_WINDOW_SECONDS = 30


app = FastAPI(
    title="Cloud Service"
)


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.post("/data")
def receive_data(data: SensorData):
    # Legacy, unencrypted endpoint — kept for backward compatibility, but every
    # use is flagged so it's never a silent downgrade. New clients should use
    # /data/secure.
    logger.warning(
        "Received data on legacy UNENCRYPTED endpoint from device %s "
        "— consider migrating to /data/secure",
        data.device_id
    )

    save_sensor_data(
        data.model_dump()
    )

    return {
        "status": "stored"
    }


@app.post("/data/secure")
def receive_secure_data(envelope: SecureEnvelope):
    try:
        kem_ciphertext = base64.b64decode(envelope.kem_ciphertext)
        nonce = base64.b64decode(envelope.nonce)
        ciphertext = base64.b64decode(envelope.ciphertext)

        shared_secret = decapsulate(PRIVATE_KEY, kem_ciphertext)
        plaintext = decrypt_payload(shared_secret, nonce, ciphertext)
        payload = json.loads(plaintext)
    except Exception as error:
        logger.warning("Rejected /data/secure request: decryption failed (%s)", error)
        raise HTTPException(status_code=400, detail="Decryption failed") from error

    timestamp = payload.get("timestamp")
    if timestamp is None or abs(time.time() - timestamp) > REPLAY_WINDOW_SECONDS:
        logger.warning("Rejected /data/secure request: timestamp outside acceptance window")
        raise HTTPException(status_code=401, detail="Request expired or missing timestamp")

    data = SensorData(device_id=payload["device_id"], temperature=payload["temperature"])

    logger.info(
        "Received data on secure endpoint from device %s",
        data.device_id
    )

    save_sensor_data(
        data.model_dump()
    )

    return {
        "status": "stored"
    }


@app.get("/data")
def get_data():
    return get_all_data()
