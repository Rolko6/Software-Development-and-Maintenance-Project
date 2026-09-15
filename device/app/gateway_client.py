# Initially, this sends data normally over plain HTTP.
# Later, this will become the place where device-to-gateway ML-KEM protection
# is integrated (see gateway/app/cloud_client.py for the matching comment on
# the gateway-to-cloud leg).

from dataclasses import dataclass
from typing import Optional

import requests

from app.models import SensorReading


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    status_code: Optional[int]
    error: Optional[str]


class GatewayClient:
    def __init__(self, url: str, timeout: float, session: Optional[requests.Session] = None):
        self._url = url
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()

    def send(self, reading: SensorReading) -> DeliveryResult:
        try:
            response = self._session.post(
                self._url,
                json=reading.to_payload(),
                timeout=self._timeout
            )
        except requests.RequestException as error:
            return DeliveryResult(
                delivered=False,
                status_code=None,
                error=str(error)
            )

        if 200 <= response.status_code < 300:
            return DeliveryResult(
                delivered=True,
                status_code=response.status_code,
                error=None
            )

        return DeliveryResult(
            delivered=False,
            status_code=response.status_code,
            error=None
        )
