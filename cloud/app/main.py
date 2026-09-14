import logging

from fastapi import FastAPI

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


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.post("/data")
def receive_data(data: SensorData):

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