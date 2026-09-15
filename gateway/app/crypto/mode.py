"""Migration mode switch for the gateway's ML-KEM secure channel.

GATEWAY_ML_KEM_MODE has three values, read fresh from the environment on
every call (never cached):

- "off" (default): send readings exactly as today, plaintext POST /data.
- "enabled": use the secure channel (handshake + POST /secure/data).
- "required": also use the secure channel. This gateway has no plaintext
  fallback once turned on, so "enabled" and "required" behave identically
  here -- the distinction that matters operationally is on the *cloud*
  side, which can keep tolerating plaintext from not-yet-upgraded gateways
  in "enabled" but must refuse it once flipped to "required". Both values
  are provided on the gateway for symmetry with the cloud switch and so a
  future gateway-side downgrade policy has a place to live; see the
  "Migration strategy" section of docs/security/ml-kem-integration.md.
"""

from __future__ import annotations

import os

_VALID_MODES = ("off", "enabled", "required")


def get_gateway_mode() -> str:
    value = os.environ.get("GATEWAY_ML_KEM_MODE", "off").strip().lower()
    return value if value in _VALID_MODES else "off"


def secure_channel_enabled() -> bool:
    return get_gateway_mode() in ("enabled", "required")
