import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app import main as cloud_main
from app.main import app
from app.metrics import (
    LEGACY_DATA_REJECTED_TOTAL,
    LEGACY_DATA_RECEIVED_TOTAL,
    SECURE_DATA_REJECTED_TOTAL,
    SECURE_DATA_RECEIVED_TOTAL,
)

client = TestClient(app)
CLOUD_ROOT = Path(__file__).resolve().parents[1]


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
    assert b"legacy_data_rejected_total" in response.content
    assert b'secure_data_rejected_total{reason="decryption_failed"}' in response.content
    assert b'secure_data_rejected_total{reason="malformed_payload"}' in response.content
    assert b'secure_data_rejected_total{reason="stale_timestamp"}' in response.content
    assert b'secure_data_rejected_total{reason="validation_failed"}' in response.content
    assert b'secure_data_rejected_total{reason="storage_failed"}' in response.content


def test_known_rejection_labels_are_zero_in_a_fresh_process():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(CLOUD_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from prometheus_client import generate_latest; "
            "import app.metrics; print(generate_latest().decode())",
        ],
        cwd=CLOUD_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    for reason in (
        "decryption_failed",
        "malformed_payload",
        "stale_timestamp",
        "validation_failed",
        "storage_failed",
    ):
        assert f'secure_data_rejected_total{{reason="{reason}"}} 0.0' in result.stdout


def test_secure_data_success_increments_received_counter(cloud_public_key):
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


def test_legacy_data_rejection_increments_rejected_counter():
    received_before = LEGACY_DATA_RECEIVED_TOTAL._value.get()
    rejected_before = LEGACY_DATA_REJECTED_TOTAL._value.get()

    response = client.post("/data", json={"device_id": "sensor-1", "temperature": 22.5})

    assert response.status_code == 403
    assert LEGACY_DATA_RECEIVED_TOTAL._value.get() == received_before
    assert LEGACY_DATA_REJECTED_TOTAL._value.get() == rejected_before + 1


def test_explicitly_allowed_legacy_data_increments_received_counter(monkeypatch):
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)
    before = LEGACY_DATA_RECEIVED_TOTAL._value.get()

    response = client.post("/data", json={"device_id": "sensor-1", "temperature": 22.5})

    assert response.status_code == 200
    assert LEGACY_DATA_RECEIVED_TOTAL._value.get() == before + 1


def test_legacy_storage_failure_does_not_increment_received_counter(monkeypatch):
    monkeypatch.setattr(cloud_main, "ALLOW_LEGACY_INGESTION", True)
    received_before = LEGACY_DATA_RECEIVED_TOTAL._value.get()

    def fail_to_store(data):
        raise sqlite3.OperationalError("injected write failure")

    monkeypatch.setattr(cloud_main, "save_sensor_data", fail_to_store)

    response = client.post(
        "/data",
        json={"device_id": "sensor-1", "temperature": 22.5},
    )

    assert response.status_code == 503
    assert LEGACY_DATA_RECEIVED_TOTAL._value.get() == received_before


def test_storage_failure_does_not_increment_secure_success_counter(
    cloud_public_key,
    monkeypatch,
):
    received_before = SECURE_DATA_RECEIVED_TOTAL._value.get()
    rejected_before = SECURE_DATA_REJECTED_TOTAL.labels(reason="storage_failed")._value.get()

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
    assert SECURE_DATA_RECEIVED_TOTAL._value.get() == received_before
    assert (
        SECURE_DATA_REJECTED_TOTAL.labels(reason="storage_failed")._value.get()
        == rejected_before + 1
    )
