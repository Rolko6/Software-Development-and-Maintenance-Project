import logging
import time

from fastapi import FastAPI, HTTPException
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