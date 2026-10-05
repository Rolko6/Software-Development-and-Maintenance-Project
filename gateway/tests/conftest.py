import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kyber_py.ml_kem.default_parameters import ML_KEM_768

# app.keys reads CLOUD_ML_KEM_PUBLIC_KEY at import time, so it must be set
# before anything imports app.main. The matching private key is discarded —
# gateway never needs it, and tests that need a real round trip generate
# their own keypair and monkeypatch it in (see test_cloud_client.py).
_dummy_public_key, _ = ML_KEM_768.keygen()
os.environ.setdefault("CLOUD_ML_KEM_PUBLIC_KEY", base64.b64encode(_dummy_public_key).decode())


@pytest.fixture(autouse=True)
def reset_sensor_state():
    from app.sensor_state import SENSOR_STATE

    SENSOR_STATE.clear()
    yield
    SENSOR_STATE.clear()
