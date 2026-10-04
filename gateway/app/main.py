import logging

from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

from app.models import SensorData
from app.cloud_client import send_to_cloud
from app.metrics import (
    DEVICE_MESSAGES_TOTAL,
    CLOUD_FORWARD_FAILURES_TOTAL,
    SENSOR_FAULT_READINGS_TOTAL
)


logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# Known DS18B20 error sentinels (see documentation/phases/v1.3.0.md).
SENSOR_FAULT_SENTINELS = {
    85.0: "power_on_reset",
    -127.0: "crc_failure",
}


app = FastAPI(
    title="Edge Gateway"
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


@app.post("/device-data")
def receive_device_data(data: SensorData):

    DEVICE_MESSAGES_TOTAL.inc()

    fault_type = SENSOR_FAULT_SENTINELS.get(data.temperature)
    if fault_type is not None:
        SENSOR_FAULT_READINGS_TOTAL.labels(type=fault_type).inc()

    logger.info(
        "Received data from device %s",
        data.device_id
    )

    try:
        result = send_to_cloud(
            data.model_dump()
        )

        return {
            "status": "forwarded",
            "cloud_response": result
        }

    except Exception as error:

        CLOUD_FORWARD_FAILURES_TOTAL.inc()

        logger.exception(
            "Failed to forward data to cloud"
        )

        raise HTTPException(
            status_code=502,
            detail="Cloud service unavailable"
        ) from error