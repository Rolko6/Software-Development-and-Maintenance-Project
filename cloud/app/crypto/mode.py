"""Migration mode switch for the cloud's ML-KEM secure channel.

CLOUD_ML_KEM_MODE has three values, read fresh from the environment on
every call (never cached) so tests and operators see changes take effect
immediately:

- "off" (default): today's behaviour. The /secure/* endpoints reject every
  request with 403; POST /data keeps accepting plaintext readings.
- "enabled": /secure/* endpoints are active; POST /data still also accepts
  plaintext, so a fleet with a mix of upgraded and not-yet-upgraded gateways
  keeps working during rollout.
- "required": /secure/* endpoints are active; POST /data rejects plaintext
  readings with 403 via `enforce_legacy_mode`, so the mode switch can only
  cut plaintext off once every gateway has moved to the secure channel.

See the "Migration strategy" section of docs/security/ml-kem-integration.md
for the intended rollout and rollback order.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

_VALID_MODES = ("off", "enabled", "required")


def get_cloud_mode() -> str:
    value = os.environ.get("CLOUD_ML_KEM_MODE", "off").strip().lower()
    return value if value in _VALID_MODES else "off"


def get_psk() -> Optional[bytes]:
    """Re-exported for convenience; see wire.get_psk for the authoritative
    implementation shared with the gateway side."""
    from . import wire

    return wire.get_psk()


def enforce_secure_enabled() -> None:
    """FastAPI dependency applied to every /secure/* route: 403 when the
    secure channel is switched off."""
    if get_cloud_mode() == "off":
        raise HTTPException(status_code=403, detail="ML-KEM secure channel disabled")


def enforce_legacy_mode() -> None:
    """FastAPI dependency intended for the existing plaintext POST /data
    route (wired in by the integration patch, not by this package -- see
    docs/security/ml-kem-integration.md, "Integration steps for the main
    agent"): 403 once CLOUD_ML_KEM_MODE=required."""
    if get_cloud_mode() == "required":
        raise HTTPException(
            status_code=403,
            detail="plaintext ingestion disabled; use /secure/data",
        )
