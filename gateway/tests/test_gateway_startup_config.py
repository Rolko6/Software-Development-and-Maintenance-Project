"""The gateway refuses to start with an unknown mode or, in required mode,
an unusable ML_KEM_PSK (see app/security_config.py).

Each case imports app.main in a fresh interpreter, because the mode is read
once at import time and this test session has already imported the app.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

GATEWAY_DIR = Path(__file__).resolve().parents[1]
GOOD_PSK = "a" * 64


def _start(mode, psk):
    env = {k: v for k, v in os.environ.items() if k not in ("GATEWAY_ML_KEM_MODE", "ML_KEM_PSK")}
    if mode is not None:
        env["GATEWAY_ML_KEM_MODE"] = mode
    if psk is not None:
        env["ML_KEM_PSK"] = psk
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=GATEWAY_DIR, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.parametrize("mode, psk", [
    ("enabeld", GOOD_PSK),
    ("required", None),
    ("required", "dev-only-insecure-psk-change-me"),
    ("required", "short"),
])
def test_gateway_refuses_to_start(mode, psk):
    result = _start(mode, psk)
    assert result.returncode != 0
    assert "InsecureConfigurationError" in result.stderr
    assert "GATEWAY_ML_KEM_MODE" in result.stderr


@pytest.mark.parametrize("mode, psk", [
    (None, None),
    ("off", None),
    ("enabled", "dev-only-insecure-psk-change-me"),
    ("required", GOOD_PSK),
])
def test_gateway_starts(mode, psk):
    result = _start(mode, psk)
    assert result.returncode == 0, result.stderr
