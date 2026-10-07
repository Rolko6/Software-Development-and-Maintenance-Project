import base64
import json
import logging
import math
import sqlite3
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


# Same handler as the gateway's: FastAPI's 422 response repeats the rejected
# input, and a NaN or Infinity there would make the error response itself
# fail with 500, so such values are shown as text instead.
def _json_safe_validation_detail(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {
            key: _json_safe_validation_detail(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe_validation_detail(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, error):
    return JSONResponse(
        status_code=422,
        content={
            "detail": _json_safe_validation_detail(
                jsonable_encoder(error.errors())
            )
        },
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


def _reject(reason: str, status_code: int, detail: str) -> HTTPException:
    """Log and count one rejected /data/secure request; returns the error to raise."""
    logger.warning("Rejected /data/secure request: %s (%s)", detail, reason)
    SECURE_DATA_REJECTED_TOTAL.labels(reason=reason).inc()
    return HTTPException(status_code=status_code, detail=detail)


@app.post("/data/secure")
def receive_secure_data(envelope: SecureEnvelope):
    # 1. Decrypt: ML-KEM gives the shared secret, AES-GCM the plaintext.
    try:
        kem_ciphertext = base64.b64decode(envelope.kem_ciphertext, validate=True)
        nonce = base64.b64decode(envelope.nonce, validate=True)
        ciphertext = base64.b64decode(envelope.ciphertext, validate=True)

        shared_secret = decapsulate(PRIVATE_KEY, kem_ciphertext)
        plaintext = decrypt_payload(shared_secret, nonce, ciphertext)
    except Exception as error:
        raise _reject("decryption_failed", 400, "Decryption failed") from error

    # 2. The plaintext must be a JSON object with a usable timestamp.
    try:
        payload = json.loads(plaintext)
    except ValueError as error:  # includes JSONDecodeError and UnicodeDecodeError
        raise _reject("malformed_payload", 400, "Invalid encrypted payload") from error

    if not isinstance(payload, dict):
        raise _reject("malformed_payload", 400, "Invalid encrypted payload")

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) \
            or not _finite_number(timestamp):
        raise _reject("malformed_payload", 400, "Invalid or missing timestamp")

    # 3. Replay protection: only recent requests are accepted.
    if abs(time.time() - timestamp) > REPLAY_WINDOW_SECONDS:
        raise _reject("stale_timestamp", 401, "Request expired or missing timestamp")

    # 4. The reading itself (SensorData also rejects NaN and Infinity).
    try:
        data = SensorData.model_validate(payload)
    except ValidationError as error:
        raise _reject("validation_failed", 422, "Invalid sensor data") from error

    # 5. Store. A storage failure is the server's fault, so it is logged with
    # the full traceback.
    try:
        save_sensor_data(data.model_dump())
    except sqlite3.Error as error:
        logger.exception("Failed to store data received on secure endpoint")
        SECURE_DATA_REJECTED_TOTAL.labels(reason="storage_failed").inc()
        raise HTTPException(status_code=503, detail="Storage unavailable") from error

    logger.info("Received data on secure endpoint from device %s", data.device_id)
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
