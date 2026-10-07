import base64
import json
import os
import sqlite3
import time

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey, MLKEM768PublicKey

from app import main as cloud_main
from app.main import app
from app.storage import get_all_data

client = TestClient(app)


def _build_envelope(public_key, payload):
    shared_secret, kem_ciphertext = MLKEM768PublicKey.from_public_bytes(public_key).encapsulate()
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


@pytest.mark.parametrize("path", ["/data", "/data/"])
def test_post_data_is_rejected_by_default_without_storing(path):
    payload = {"device_id": "sensor-1", "temperature": 22.5}
    post_response = client.post(path, json=payload)

    assert post_response.status_code == 403
    assert post_response.json() == {"detail": "Legacy ingestion is disabled"}
    assert get_all_data() == []


def test_post_data_policy_rejects_before_body_validation():
    response = client.post("/data")

    assert response.status_code == 403
    assert get_all_data() == []


def test_get_data_remains_available_when_legacy_ingestion_is_disabled():
    get_response = client.get("/data")

    assert get_response.status_code == 200
    assert get_response.json() == []


def test_explicit_legacy_compatibility_setting_stores_data(monkeypatch):
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)
    payload = {"device_id": "sensor-1", "temperature": 22.5}

    post_response = client.post("/data", json=payload)

    assert post_response.status_code == 200
    assert post_response.json() == {"status": "stored"}
    assert get_all_data() == [payload]


def test_data_model_has_no_device_id_length_limit(monkeypatch):
    # Documents a known gap (see documentation/phases/v1.0.0.md, Section 4):
    # cloud's SensorData model is looser than gateway's — an empty device_id is accepted here.
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)

    response = client.post("/data", json={"device_id": "", "temperature": 22.5})

    assert response.status_code == 200


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_legacy_data_rejects_non_finite_temperature(monkeypatch, literal):
    # A stored NaN cannot be written back as JSON, so it would make every later
    # GET /data fail with 500, and with SQLite storage it survives restarts.
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)

    response = client.post(
        "/data",
        content=f'{{"device_id": "sensor-1", "temperature": {literal}}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert get_all_data() == []
    assert client.get("/data").status_code == 200


def test_legacy_data_endpoint_logs_a_warning(caplog, monkeypatch):
    # /data stays for backward compatibility, but every use should be visibly
    # flagged as insecure (see documentation/phases/v2.0.0.md, Section 2).
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)

    with caplog.at_level("WARNING"):
        response = client.post("/data", json={"device_id": "sensor-1", "temperature": 22.5})

    assert response.status_code == 200
    assert any("legacy" in record.message.lower() for record in caplog.records)


def test_secure_data_valid_request_stores_and_returns_200(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1",
        "temperature": 22.5,
        "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 200
    assert get_all_data() == [{"device_id": "sensor-1", "temperature": 22.5}]


def test_secure_data_tampered_ciphertext_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["ciphertext"]))
    tampered[0] ^= 0xFF
    envelope["ciphertext"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400
    assert get_all_data() == []


def test_secure_data_tampered_kem_ciphertext_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["kem_ciphertext"]))
    tampered[0] ^= 0xFF
    envelope["kem_ciphertext"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400
    assert get_all_data() == []


def test_secure_data_tampered_nonce_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })
    tampered = bytearray(base64.b64decode(envelope["nonce"]))
    tampered[0] ^= 0xFF
    envelope["nonce"] = base64.b64encode(bytes(tampered)).decode()

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400
    assert get_all_data() == []


def test_secure_data_encrypted_with_wrong_public_key_rejected(cloud_public_key):
    # Simulates an attacker (or misconfigured client) using the wrong key entirely.
    wrong_public_key = MLKEM768PrivateKey.generate().public_key().public_bytes_raw()
    envelope = _build_envelope(wrong_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400
    assert get_all_data() == []


def test_secure_data_stale_timestamp_rejected(cloud_public_key):
    # Replay protection: a request older than the acceptance window is rejected
    # even though it decrypts perfectly fine.
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1", "temperature": 22.5, "timestamp": time.time() - 60,
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 401
    assert get_all_data() == []


@pytest.mark.parametrize("timestamp", [None, "now", True, float("nan"), 10 ** 1000])
def test_secure_data_invalid_timestamp_is_controlled_and_not_stored(
    cloud_public_key,
    timestamp,
):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1",
        "temperature": 22.5,
        "timestamp": timestamp,
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 400
    assert get_all_data() == []


@pytest.mark.parametrize(
    "payload, expected_status",
    [
        (["not", "an", "object"], 400),
        ({"temperature": 22.5, "timestamp": 0}, 422),
        (
            {
                "device_id": "sensor-1",
                "temperature": {"bad": "type"},
                "timestamp": 0,
            },
            422,
        ),
    ],
)
def test_secure_data_malformed_payload_is_not_stored(
    cloud_public_key,
    payload,
    expected_status,
):
    # Replace sentinel timestamps with a current value so model validation,
    # rather than replay protection, is what the object-shaped cases exercise.
    if isinstance(payload, dict):
        payload = {**payload, "timestamp": time.time()}

    envelope = _build_envelope(cloud_public_key, payload)
    response = client.post("/data/secure", json=envelope)

    assert response.status_code == expected_status
    assert get_all_data() == []


def test_secure_data_non_finite_temperature_is_rejected(cloud_public_key):
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1",
        "temperature": float("nan"),
        "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 422
    assert get_all_data() == []


def test_secure_data_storage_failure_returns_503(cloud_public_key, monkeypatch):
    def fail_to_store(data):
        raise sqlite3.OperationalError("injected write failure")

    monkeypatch.setattr(cloud_main, "save_sensor_data", fail_to_store)
    envelope = _build_envelope(cloud_public_key, {
        "device_id": "sensor-1",
        "temperature": 22.5,
        "timestamp": time.time(),
    })

    response = client.post("/data/secure", json=envelope)

    assert response.status_code == 503
    assert response.json() == {"detail": "Storage unavailable"}
    assert get_all_data() == []


def test_legacy_data_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)

    def fail_to_store(data):
        raise sqlite3.OperationalError("injected write failure")

    monkeypatch.setattr(cloud_main, "save_sensor_data", fail_to_store)

    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": 22.5},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Storage unavailable"}


def test_get_data_storage_failure_returns_503(monkeypatch):
    def fail_to_read():
        raise sqlite3.OperationalError("injected read failure")

    monkeypatch.setattr(cloud_main, "get_all_data", fail_to_read)

    response = client.get("/data")

    assert response.status_code == 503
    assert response.json() == {"detail": "Storage unavailable"}
