import base64
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app.main import app
from app.metrics import (
    LEGACY_DATA_RECEIVED_TOTAL,
    SECURE_DATA_REJECTED_TOTAL,
    SECURE_DATA_RECEIVED_TOTAL,
)
from app.storage import stored_data

client = TestClient(app)


def _build_envelope(public_key, payload: dict):
    shared_secret, kem_ciphertext = ML_KEM_768.encaps(public_key)
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, json.dumps(payload).encode(), None)

    return {
        "kem_ciphertext": base64.b64encode(kem_ciphertext).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def test_metrics_endpoint_is_mounted():
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert b"secure_data_received_total" in response.content


def test_secure_data_success_increments_received_counter(cloud_public_key):
    stored_data.clear()
    before = SECURE_DATA_RECEIVED_TOTAL._value.get()

    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    client.post("/data/secure", json=envelope)

    assert SECURE_DATA_RECEIVED_TOTAL._value.get() == before + 1


def test_secure_data_decryption_failure_increments_rejected_counter(cloud_public_key):
    before = SECURE_DATA_REJECTED_TOTAL.labels(reason="decryption_failed")._value.get()

    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["ciphertext"]))
    tampered[0] ^= 0xFF
    envelope["ciphertext"] = base64.b64encode(bytes(tampered)).decode()

    client.post("/data/secure", json=envelope)

    assert SECURE_DATA_REJECTED_TOTAL.labels(reason="decryption_failed")._value.get() == before + 1


def test_secure_data_stale_timestamp_increments_rejected_counter(cloud_public_key):
    before = SECURE_DATA_REJECTED_TOTAL.labels(reason="stale_timestamp")._value.get()

    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time() - 60,
    })
    client.post("/data/secure", json=envelope)

    assert SECURE_DATA_REJECTED_TOTAL.labels(reason="stale_timestamp")._value.get() == before + 1


def test_legacy_data_increments_legacy_counter():
    stored_data.clear()
    before = LEGACY_DATA_RECEIVED_TOTAL._value.get()

    client.post("/data", json={"device_id": "sensor-1", "temperature": 22.5})

    assert LEGACY_DATA_RECEIVED_TOTAL._value.get() == before + 1
