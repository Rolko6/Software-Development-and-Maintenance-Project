# This defines what valid sensor data looks like.

from typing import Literal

from pydantic import BaseModel, Field


class SensorData(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=100
    )

    temperature: float = Field(allow_inf_nan=False)


class DeviceStatus(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=100
    )

    status: Literal["disconnected"]
