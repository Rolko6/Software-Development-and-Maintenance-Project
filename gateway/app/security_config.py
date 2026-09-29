"""Startup checks for the ML-KEM mode switch and the pre-shared key.

DUPLICATED FILE: this exact module is copied verbatim into both
``cloud/app/security_config.py`` and ``gateway/app/security_config.py``
(the services cannot import each other). If you change anything here, make
the identical change in the other copy; tests/crypto checks they match.

It lives outside ``app.crypto`` on purpose: importing that package builds
the ML-KEM machinery, and the mode has to be checked even when it is "off".

- ``parse_mode`` rejects any value other than off / enabled / required, so a
  typo stops the service instead of silently selecting a different mode.
- ``check_psk`` refuses to start in "required" mode when ``ML_KEM_PSK`` is
  missing, is the development placeholder committed in docker-compose.yml,
  or is shorter than ``MIN_PSK_BYTES``. In "enabled" mode the same problems
  are logged as a warning, so the local Compose setup keeps working.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

VALID_MODES = ("off", "enabled", "required")

# The default in docker-compose.yml. Public, so it authenticates nothing.
PLACEHOLDER_PSK = "dev-only-insecure-psk-change-me"

# Same length as the HMAC-SHA256 output and the AES-256 key. `openssl rand
# -hex 32` produces 64 characters.
MIN_PSK_BYTES = 32


class InsecureConfigurationError(RuntimeError):
    """The service must not start with this configuration."""


def parse_mode(raw: Optional[str], variable: str) -> str:
    """Normalise a *_ML_KEM_MODE value; unset means "off"."""
    value = (raw if raw is not None else "off").strip().lower()
    if value not in VALID_MODES:
        raise InsecureConfigurationError(
            f"{variable}={raw!r} is not one of {', '.join(VALID_MODES)}"
        )
    return value


def psk_problem(psk: Optional[str]) -> Optional[str]:
    """Why this ML_KEM_PSK value gives no real authentication, or None."""
    if not psk:
        return "ML_KEM_PSK is not set, so the handshake is unauthenticated"
    if psk == PLACEHOLDER_PSK:
        return "ML_KEM_PSK is the public development placeholder from docker-compose.yml"
    if len(psk.encode("utf-8")) < MIN_PSK_BYTES:
        return f"ML_KEM_PSK is shorter than {MIN_PSK_BYTES} bytes"
    return None


def check_psk(mode: str, variable: str) -> None:
    """Raise in "required" mode, warn in "enabled" mode, ignore in "off"."""
    if mode == "off":
        return
    problem = psk_problem(os.environ.get("ML_KEM_PSK"))
    if problem is None:
        return
    if mode == "required":
        raise InsecureConfigurationError(
            f"{problem}; refusing to start with {variable}=required. "
            "Set the same ML_KEM_PSK on gateway and cloud, "
            "for example from `openssl rand -hex 32`."
        )
    logger.warning("%s; %s=%s continues, but do not use this setup beyond local development.",
                   problem, variable, mode)


def load_mode(variable: str) -> str:
    """Read, validate and check one service's mode at startup."""
    mode = parse_mode(os.environ.get(variable), variable)
    check_psk(mode, variable)
    return mode
