import logging
import math
import time

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.models import SensorData
from app.cloud_client import (
    send_to_cloud,
    check_cloud_health,
    CloudRejected,
    CloudUnavailable
)
from app.cloud_client import ML_KEM_MODE
from app.metrics import (
    DEVICE_MESSAGES_TOTAL,
    CLOUD_FORWARD_FAILURES_TOTAL,
    GATEWAY_DELIVERY_OUTCOME_TOTAL,
    GATEWAY_REQUEST_DURATION_SECONDS,
    GATEWAY_SECURITY_MODE
)


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Edge Gateway"
)


metrics_app = make_asgi_app()

app.mount(
    "/metrics",
    metrics_app
)


# Without this the enum defaults to "off" and would misreport the running
# configuration -- a metric that lies is worse than no metric.
SECURITY_MODE = ML_KEM_MODE if ML_KEM_MODE in (
    "off", "enabled", "required"
) else "off"

GATEWAY_SECURITY_MODE.state(SECURITY_MODE)


def _record(started_at: float, outcome: str) -> None:
    GATEWAY_DELIVERY_OUTCOME_TOTAL.labels(outcome=outcome).inc()

    GATEWAY_REQUEST_DURATION_SECONDS.labels(
        outcome=outcome,
        security_mode=SECURITY_MODE
    ).observe(time.perf_counter() - started_at)


def _json_safe(value):
    """Replace non-finite floats with their string form, recursively.

    A validation error echoes the rejected input back to the caller. When a
    sensor's read fails and it sends NaN or Infinity, that input cannot be
    written as standard JSON, so without this the error response itself
    raises and the caller gets a 500 instead of a 422. Keep in sync with
    cloud/app/main.py.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)

    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    return value


@app.exception_handler(RequestValidationError)
async def _reject_invalid_reading(request, exc):
    errors = exc.errors()

    # Documented in app/metrics.py but previously never incremented: without
    # it a sensor sending only bad readings is invisible in monitoring.
    GATEWAY_DELIVERY_OUTCOME_TOTAL.labels(
        outcome="rejected_validation"
    ).inc()

    body = exc.body if isinstance(exc.body, dict) else {}

    fields = sorted({
        str(error["loc"][-1])
        for error in errors
        if error.get("loc")
    })

    # %r keeps a device-supplied ID from injecting line breaks into the log.
    logger.warning(
        "Rejected reading from device %r: invalid %s",
        body.get("device_id"),
        ", ".join(fields) or "request"
    )

    # Mirrors FastAPI's own default handler so the response body is unchanged
    # for every finite input.
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe(jsonable_encoder(errors))}
    )


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/ready")
def ready():
    if check_cloud_health():
        return {
            "status": "ready",
            "cloud": "reachable"
        }

    raise HTTPException(
        status_code=503,
        detail="Cloud service unreachable"
    )


@app.post("/device-data")
def receive_device_data(data: SensorData):

    started_at = time.perf_counter()

    DEVICE_MESSAGES_TOTAL.inc()

    logger.info(
        "Received data from device %s",
        data.device_id
    )

    try:
        result = send_to_cloud(
            data.model_dump()
        )

        _record(started_at, "forwarded")

        return {
            "status": "forwarded",
            "cloud_response": result
        }

    except CloudRejected as error:

        CLOUD_FORWARD_FAILURES_TOTAL.inc()

        _record(started_at, "rejected_validation")

        logger.warning(
            "Cloud rejected reading: %s",
            error.detail
        )

        raise HTTPException(
            status_code=422,
            detail=f"Cloud rejected reading: {error.detail}"
        ) from error

    except CloudUnavailable as error:

        CLOUD_FORWARD_FAILURES_TOTAL.inc()

        _record(started_at, "failed_after_retries")

        logger.exception(
            "Failed to forward data to cloud"
        )

        raise HTTPException(
            status_code=502,
            detail="Cloud service unavailable"
        ) from error

    except Exception as error:

        CLOUD_FORWARD_FAILURES_TOTAL.inc()

        _record(started_at, "failed_after_retries")

        logger.exception(
            "Unexpected error forwarding data to cloud"
        )

        raise HTTPException(
            status_code=502,
            detail="Cloud service unavailable"
        ) from error