# This defines what valid sensor data looks like.

from pydantic import BaseModel, Field


# Physical range for a general-purpose ambient temperature sensor. Earth's
# recorded surface ambient extremes are roughly -89.2C (Vostok, Antarctica)
# to +56.7C (Death Valley); -40..60 comfortably covers normal and extreme
# ambient deployments while rejecting clearly invalid values (e.g. -273 or
# 1000). This does not change the simulator's 15-30C output range in
# device/app/models.py. Keep in sync with cloud/app/models.py.
MIN_TEMPERATURE_C = -40.0
MAX_TEMPERATURE_C = 60.0


class SensorData(BaseModel):
    device_id: str = Field(
        min_length=1,
        max_length=100
    )

    temperature: float = Field(
        ge=MIN_TEMPERATURE_C,
        le=MAX_TEMPERATURE_C
    )