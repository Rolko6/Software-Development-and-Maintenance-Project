# This defines what valid sensor data looks like.

from pydantic import BaseModel, Field


class SensorData(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=100
    )

    temperature: float