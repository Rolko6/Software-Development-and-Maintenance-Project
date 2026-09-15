# Defines a single simulated sensor reading and its wire representation.

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SensorReading:
    device_id: str
    temperature: float

    # recorded_at is deliberately local-only: the legacy gateway contract
    # (see gateway/app/models.py::SensorData) carries only device_id and
    # temperature, so this timestamp never leaves the device process.
    recorded_at: datetime

    def to_payload(self) -> dict:
        return {
            "device_id": self.device_id,
            "temperature": round(float(self.temperature), 2)
        }
