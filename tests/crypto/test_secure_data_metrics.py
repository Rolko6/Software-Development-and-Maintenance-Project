"""Every /secure/data rejection is counted (M3), so replays and stale
sessions are visible in Prometheus, not only in HTTP status codes.

AEAD authentication failures keep their own counter,
cloud_crypto_decrypt_failures_total, and are not counted twice.
"""

import base64
import json

import pytest
from prometheus_client import REGISTRY

from .conftest import cloud_wire_module

DATA_URL = "http://cloud:8001/secure/data"


def _rejected(reason):
    value = REGISTRY.get_sample_value("cloud_secure_data_rejected_total", {"reason": reason})
    return value or 0.0


def _decrypt_failures():
    return REGISTRY.get_sample_value("cloud_crypto_decrypt_failures_total") or 0.0


def _encrypt(session, counter, reading, device_id=None):
    device_id = reading["device_id"] if device_id is None else device_id
    nonce = cloud_wire_module.counter_to_nonce(counter)
    aad = cloud_wire_module.build_aad(session.session_id, device_id, nonce)
    ciphertext = cloud_wire_module.aead_encrypt(
        session.key, nonce, json.dumps(reading).encode("utf-8"), aad
    )
    return {
        "session_id": session.session_id,
        "device_id": device_id,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


@pytest.fixture()
def session(secure_client):
    return secure_client._handshake()


def _assert_counted(test_client, body, reason, status):
    before = _rejected(reason)
    response = test_client.post(DATA_URL, json=body)
    assert response.status_code == status
    assert _rejected(reason) - before == 1


def test_replay_is_counted(test_client, session):
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": 1.0})
    assert test_client.post(DATA_URL, json=body).status_code == 200
    _assert_counted(test_client, body, "replay", 409)


def test_unknown_session_is_counted(test_client, session):
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": 1.0})
    body["session_id"] = "session-that-was-never-created"
    _assert_counted(test_client, body, "unknown_session", 404)


def test_expired_session_is_counted(test_client, session, cloud_app):
    cloud_app.session_store._sessions[session.session_id].expires_at = 0
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": 1.0})
    _assert_counted(test_client, body, "expired_session", 410)


def test_malformed_envelope_is_counted(test_client, session):
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": 1.0})
    body["nonce"] = base64.b64encode(b"short").decode()
    _assert_counted(test_client, body, "malformed", 400)


def test_invalid_decrypted_payload_is_counted(test_client, session):
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": "not-a-number"})
    _assert_counted(test_client, body, "invalid_payload", 400)


def test_authentication_failure_uses_the_decrypt_counter_only(test_client, session):
    body = _encrypt(session, 0, {"device_id": "d1", "temperature": 1.0})
    body["device_id"] = "a-different-device"  # AAD no longer matches
    decrypt_before = _decrypt_failures()
    rejected_before = sum(
        _rejected(r) for r in ("malformed", "unknown_session", "expired_session", "replay", "invalid_payload")
    )

    assert test_client.post(DATA_URL, json=body).status_code == 400

    assert _decrypt_failures() - decrypt_before == 1
    rejected_after = sum(
        _rejected(r) for r in ("malformed", "unknown_session", "expired_session", "replay", "invalid_payload")
    )
    assert rejected_after == rejected_before


def test_removed_counters_are_not_exported():
    """M2: counters with no code path that could increment them are gone."""
    for name in (
        "gateway_crypto_encrypt_failures_total",
        "gateway_crypto_decrypt_failures_total",
        "cloud_crypto_encrypt_failures_total",
    ):
        assert REGISTRY.get_sample_value(name) is None
