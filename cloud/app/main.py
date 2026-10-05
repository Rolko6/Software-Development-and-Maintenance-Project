import base64
import json
import logging
import math
import sqlite3
import time

from fastapi import Depends, FastAPI, HTTPException
from pydantic import ValidationError
from prometheus_client import make_asgi_app

from app.config import ALLOW_LEGACY_INGESTION
from app.crypto import decapsulate, decrypt_payload
from app.keys import PRIVATE_KEY
from app.metrics import (
    LEGACY_DATA_REJECTED_TOTAL,
    LEGACY_DATA_RECEIVED_TOTAL,
    SECURE_DATA_RECEIVED_TOTAL,
    SECURE_DATA_REJECTED_TOTAL,
)
from app.models import SecureEnvelope, SensorData
from app.storage import (
    save_sensor_data,
    get_all_data,
    validate_database_path,
)


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# How long a /data/secure request's embedded timestamp stays acceptable.
# Older requests are rejected as possible replays. See documentation/phases/v2.0.0.md.
REPLAY_WINDOW_SECONDS = 30


def _finite_number(value):
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


validate_database_path()


app = FastAPI(
    title="Cloud Service"
)


metrics_app = make_asgi_app()

app.mount(
    "/metrics",
    metrics_app
)


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


def enforce_legacy_ingestion_policy():
    if not ALLOW_LEGACY_INGESTION:
        logger.warning("Rejected request to disabled legacy UNENCRYPTED endpoint")
        LEGACY_DATA_REJECTED_TOTAL.inc()
        raise HTTPException(status_code=403, detail="Legacy ingestion is disabled")


@app.post("/data", dependencies=[Depends(enforce_legacy_ingestion_policy)])
def receive_data(data: SensorData):
    logger.warning(
        "Received data on legacy UNENCRYPTED endpoint from device %s "
        "— consider migrating to /data/secure",
        data.device_id
    )

    try:
        save_sensor_data(data.model_dump())
    except sqlite3.Error as error:
        logger.exception("Failed to store data received on legacy endpoint")
        raise HTTPException(status_code=503, detail="Storage unavailable") from error

    LEGACY_DATA_RECEIVED_TOTAL.inc()

    return {
        "status": "stored"
    }


@app.post("/data/secure")
def receive_secure_data(envelope: SecureEnvelope):
    try:
        kem_ciphertext = base64.b64decode(envelope.kem_ciphertext, validate=True)
        nonce = base64.b64decode(envelope.nonce, validate=True)
        ciphertext = base64.b64decode(envelope.ciphertext, validate=True)

        shared_secret = decapsulate(PRIVATE_KEY, kem_ciphertext)
        plaintext = decrypt_payload(shared_secret, nonce, ciphertext)
    except Exception as error:
        logger.warning("Rejected /data/secure request: decryption failed (%s)", error)
        SECURE_DATA_REJECTED_TOTAL.labels(reason="decryption_failed").inc()
        raise HTTPException(status_code=400, detail="Decryption failed") from error

    try:
        payload = json.loads(plaintext)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        logger.warning("Rejected /data/secure request: malformed JSON payload")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="malformed_payload").inc()
        raise HTTPException(status_code=400, detail="Invalid encrypted payload") from error

    if not isinstance(payload, dict):
        logger.warning("Rejected /data/secure request: payload is not an object")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="malformed_payload").inc()
        raise HTTPException(status_code=400, detail="Invalid encrypted payload")

    timestamp = payload.get("timestamp")
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not _finite_number(timestamp)
    ):
        logger.warning("Rejected /data/secure request: invalid timestamp")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="malformed_payload").inc()
        raise HTTPException(status_code=400, detail="Invalid or missing timestamp")

    if abs(time.time() - timestamp) > REPLAY_WINDOW_SECONDS:
        logger.warning("Rejected /data/secure request: timestamp outside acceptance window")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="stale_timestamp").inc()
        raise HTTPException(status_code=401, detail="Request expired or missing timestamp")

    try:
        data = SensorData.model_validate(payload)
    except ValidationError as error:
        logger.warning("Rejected /data/secure request: invalid sensor data")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="validation_failed").inc()
        raise HTTPException(status_code=422, detail="Invalid sensor data") from error

    if not math.isfinite(data.temperature):
        logger.warning("Rejected /data/secure request: non-finite temperature")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="validation_failed").inc()
        raise HTTPException(status_code=422, detail="Invalid sensor data")

    logger.info(
        "Received data on secure endpoint from device %s",
        data.device_id
    )

    try:
        save_sensor_data(data.model_dump())
    except sqlite3.Error as error:
        logger.exception("Failed to store data received on secure endpoint")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="storage_failed").inc()
        raise HTTPException(status_code=503, detail="Storage unavailable") from error

    SECURE_DATA_RECEIVED_TOTAL.inc()

    return {
        "status": "stored"
    }


@app.get("/data")
def get_data():
    try:
        return get_all_data()
    except sqlite3.Error as error:
        logger.exception("Failed to read stored data")
        raise HTTPException(status_code=503, detail="Storage unavailable") from error
