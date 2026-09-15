import logging
import os

from fastapi import Depends, FastAPI

from app.models import SensorData
from app.storage import (
    save_sensor_data,
    get_all_data
)


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Cloud Service"
)


# Read the mode from the environment rather than importing app.crypto to ask,
# because importing that package eagerly builds the ML-KEM key manager and
# session store (see docs/security/ml-kem-integration.md, "Residual risks").
# A missing cryptography wheel or an unwritable CLOUD_ML_KEM_KEY_PATH would
# then crash this service at startup even with the feature switched off, which
# would make "off" useless as a rollback state. Importing only when the
# feature is on keeps the legacy plaintext path reachable no matter what.
ML_KEM_MODE = os.getenv("CLOUD_ML_KEM_MODE", "off").strip().lower()


if ML_KEM_MODE == "off":
    def enforce_legacy_mode() -> None:
        """No-op gate: with ML-KEM off, plaintext POST /data is the only path."""
        return None

else:
    from app.crypto import enforce_legacy_mode, router as secure_router

    app.include_router(secure_router)

    logger.info("ML-KEM secure channel mounted, mode=%s", ML_KEM_MODE)


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/ready")
def ready():
    # The cloud has no external dependency of its own (unlike the gateway,
    # which depends on the cloud), so readiness here is process-level: once
    # the process is up and serving requests, it is ready.
    return {
        "status": "ready"
    }


@app.post("/data")
def receive_data(
    data: SensorData,
    _legacy_gate: None = Depends(enforce_legacy_mode)
):

    logger.info(
        "Received data from device %s",
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