import logging
import math

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.models import DeviceStatus, SensorData
from app.cloud_client import send_to_cloud
from app.metrics import (
    DEVICE_MESSAGES_TOTAL,
    CLOUD_FORWARD_ATTEMPTS_TOTAL,
    CLOUD_FORWARD_FAILURES_TOTAL,
    SENSOR_FAULT_READINGS_TOTAL,
    SENSOR_READ_FAILURES_TOTAL,
    SENSOR_STUCK_EPISODES_TOTAL,
)
from app.sensor_state import SENSOR_STATE, SensorStateCapacityError


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

    try:
        if SENSOR_STATE.record_reading(
            data.device_id,
            data.temperature,
            is_normal=fault_type is None,
        ):
            SENSOR_STUCK_EPISODES_TOTAL.inc()
    except SensorStateCapacityError as error:
        raise HTTPException(
            status_code=503,
            detail="Sensor state capacity reached"
        ) from error

    logger.info(
        "Received data from device %s",
        data.device_id
    )

    try:
        CLOUD_FORWARD_ATTEMPTS_TOTAL.inc()
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


@app.post("/device-status")
def receive_device_status(status: DeviceStatus):
    try:
        SENSOR_STATE.record_disconnect(status.device_id)
    except SensorStateCapacityError as error:
        raise HTTPException(
            status_code=503,
            detail="Sensor state capacity reached"
        ) from error

    SENSOR_READ_FAILURES_TOTAL.inc()

    logger.warning(
        "Sensor read failed for device %s: %s",
        status.device_id,
        status.status,
    )

    return {
        "status": "recorded"
    }
