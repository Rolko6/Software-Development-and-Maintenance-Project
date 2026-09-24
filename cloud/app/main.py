import logging
import os
import time

from fastapi import Depends, FastAPI

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models import SensorData
from app.storage import (
    save_sensor_data,
    get_all_data
)
from app.metrics import (
    CLOUD_READINGS_REJECTED_TOTAL,
    CLOUD_REQUEST_DURATION_SECONDS,
    CLOUD_SECURITY_MODE,
    metrics_app
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

app.mount("/metrics", metrics_app)

# Without this the enum defaults to "off" and would misreport the running
# configuration -- a metric that lies is worse than no metric.
SECURITY_MODE = ML_KEM_MODE if ML_KEM_MODE in (
    "off", "enabled", "required"
) else "off"

CLOUD_SECURITY_MODE.state(SECURITY_MODE)


def _rejection_reason(errors) -> str:
    """Map a validation failure onto the fixed reason labels in app.metrics.

    Only the documented values are ever emitted, so the label set stays
    bounded: invalid_device_id, invalid_temperature, other.
    """
    fields = {
        str(location)
        for error in errors
        for location in error.get("loc", ())
    }

    if "device_id" in fields:
        return "invalid_device_id"

    if "temperature" in fields:
        return "invalid_temperature"

    return "other"


# Only the reading-ingest paths are timed. Timing /metrics or /health would
# bury the signal under probe traffic.
_TIMED_PATHS = ("/data", "/secure/data")


@app.middleware("http")
async def _observe_request_duration(request, call_next):
    if request.method != "POST" or request.url.path not in _TIMED_PATHS:
        return await call_next(request)

    started_at = time.perf_counter()
    response = await call_next(request)

    CLOUD_REQUEST_DURATION_SECONDS.labels(
        outcome="stored" if response.status_code < 400 else "rejected",
        security_mode=SECURITY_MODE
    ).observe(time.perf_counter() - started_at)

    return response


@app.exception_handler(RequestValidationError)
async def _count_validation_rejections(request, exc):
    errors = exc.errors()

    CLOUD_READINGS_REJECTED_TOTAL.labels(
        reason=_rejection_reason(errors)
    ).inc()

    # Mirrors FastAPI's own default handler so the response body is unchanged.
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": errors})
    )


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