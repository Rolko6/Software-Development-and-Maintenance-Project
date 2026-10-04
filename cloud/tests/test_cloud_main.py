import base64
import json
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app.main import app
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


def test_health_returns_200():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_post_data_stores_and_get_data_returns_it():
    # stored_data is shared module state, so reset it to keep this test isolated.
    stored_data.clear()

    payload = {"device_id": "sensor-1", "temperature": 22.5}
    post_response = client.post("/data", json=payload)

    assert post_response.status_code == 200
    assert post_response.json() == {"status": "stored"}

    get_response = client.get("/data")
    assert get_response.json() == [payload]


def test_data_model_has_no_device_id_length_limit():
    # Documents a known gap (see documentation/phases/v1.0.0.md, Section 4):
    # cloud's SensorData model is looser than gateway's — an empty device_id is accepted here.
    stored_data.clear()

    response = client.post("/data", json={"device_id": "", "temperature": 22.5})

    assert response.status_code == 200


def test_legacy_data_endpoint_logs_a_warning(caplog):
    # /data stays for backward compatibility, but every use should be visibly
    # flagged as insecure (see documentation/phases/v2.0.0.md, Section 2).
    stored_data.clear()

    with caplog.at_level("WARNING"):
        response = client.post("/data", json={"device_id": "sensor-1", "temperature": 22.5})

    assert response.status_code == 200
    assert any("legacy" in record.message.lower() for record in caplog.records)


def test_secure_data_valid_request_stores_and_returns_200(cloud_public_key):
    stored_data.clear()
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1",
        "temperature": 22.5,
        "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 200
    assert stored_data == [{"device_id": "sensor-1", "temperature": 22.5}]


def test_secure_data_tampered_ciphertext_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["ciphertext"]))
    tampered[0] ^= 0xFF
    envelope["ciphertext"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400


def test_secure_data_tampered_kem_ciphertext_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["kem_ciphertext"]))
    tampered[0] ^= 0xFF
    envelope["kem_ciphertext"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400


def test_secure_data_tampered_nonce_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["nonce"]))
    tampered[0] ^= 0xFF
    envelope["nonce"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400


def test_secure_data_encrypted_with_wrong_public_key_rejected(cloud_public_key):
    # Simulates an attacker (or misconfigured client) using the wrong key entirely.
    wrong_public_key, _ = ML_KEM_768.keygen()
    envelope = _build_envelope(wrong_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400


def test_secure_data_stale_timestamp_rejected(cloud_public_key):
    # Replay protection: a request older than the acceptance window is rejected
    # even though it decrypts perfectly fine.
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time() - 60,
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 401
