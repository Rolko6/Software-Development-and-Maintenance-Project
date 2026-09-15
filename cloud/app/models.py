from pydantic import BaseModel, Field


# Kept consistent with gateway/app/models.py so the cloud never accepts a
# device ID or temperature the gateway would reject. See that file for the
# reasoning behind these bounds.
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