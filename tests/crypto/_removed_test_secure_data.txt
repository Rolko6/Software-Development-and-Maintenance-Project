"""POST /secure/data: happy path plus every required negative case --
tampered ciphertext, tampered associated data, unknown/expired session,
replayed nonce, and malformed request."""

import base64
import time

import pytest
import requests

from .conftest import cloud_storage_module, cloud_wire_module


def test_happy_path_stored_value_equals_original_reading(secure_client, cloud_app):
    reading = {"device_id": "sensor-001", "temperature": 23.75}
    result = secure_client.send_secure(reading)
    assert result == {"status": "stored"}
    assert cloud_storage_module.get_all_data() == [reading]


def test_multiple_messages_increment_counter_and_all_are_stored(secure_client, cloud_app):
    for i in range(3):
        secure_client.send_secure({"device_id": "sensor-001", "temperature": 20.0 + i})
    stored = cloud_storage_module.get_all_data()
    assert [r["temperature"] for r in stored] == [20.0, 21.0, 22.0]


def _handshake_and_encrypt(secure_client, reading):
    """Helper: perform a real handshake through the fixture client, then
    hand back the raw wire fields so a test can tamper with them before
    posting directly (bypassing SecureCloudClient's own send_secure)."""
    import json

    session = secure_client._handshake()
    counter = session.counter + 1
    nonce = cloud_wire_module.counter_to_nonce(counter)
    device_id = reading["device_id"]
    plaintext = json.dumps(reading).encode("utf-8")
    aad = cloud_wire_module.build_aad(session.session_id, device_id, nonce)
    ciphertext = cloud_wire_module.aead_encrypt(session.key, nonce, plaintext, aad)
    return {
        "session_id": session.session_id,
        "device_id": device_id,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def test_tampered_ciphertext_rejected(secure_client, test_client, cloud_app):
    body = _handshake_and_encrypt(secure_client, {"device_id": "d1", "temperature": 1.0})
    raw = bytearray(base64.b64decode(body["ciphertext"]))
    raw[0] ^= 0xFF
    body["ciphertext"] = base64.b64encode(bytes(raw)).decode()

    response = test_client.post("http://cloud:8001/secure/data", json=body)
    assert response.status_code == 400
    assert cloud_storage_module.get_all_data() == []


def test_tampered_associated_data_rejected(secure_client, test_client, cloud_app):
    """Change the outer device_id (which feeds the AAD) without
    re-encrypting -- must fail AEAD authentication, not just a device_id
    mismatch check, distinguishing it from a ciphertext-only tamper."""
    body = _handshake_and_encrypt(secure_client, {"device_id": "d1", "temperature": 1.0})
    body["device_id"] = "a-different-device"

    response = test_client.post("http://cloud:8001/secure/data", json=body)
    assert response.status_code == 400
    assert cloud_storage_module.get_all_data() == []


def test_unknown_session_id_returns_404(test_client, cloud_app):
    nonce = cloud_wire_module.counter_to_nonce(0)
    body = {
        "session_id": "session-that-was-never-created",
        "device_id": "d1",
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(b"x" * 32).decode(),
    }
    response = test_client.post("http://cloud:8001/secure/data", json=body)
    assert response.status_code == 404


def test_expired_session_returns_410(secure_client, test_client, cloud_app):
    session = secure_client._handshake()
    # Force expiry without sleeping: mutate the same Session object the
    # store holds (returned by reference from SessionStore.create/get).
    stored_session, _ = cloud_app.session_store.get(session.session_id)
    stored_session.expires_at = time.time() - 1

    import json

    counter = session.counter + 1
    nonce = cloud_wire_module.counter_to_nonce(counter)
    plaintext = json.dumps({"device_id": "d1", "temperature": 1.0}).encode()
    aad = cloud_wire_module.build_aad(session.session_id, "d1", nonce)
    ciphertext = cloud_wire_module.aead_encrypt(session.key, nonce, plaintext, aad)

    response = test_client.post(
        "http://cloud:8001/secure/data",
        json={
            "session_id": session.session_id,
            "device_id": "d1",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        },
    )
    assert response.status_code == 410


def test_replayed_nonce_rejected(secure_client, test_client, cloud_app):
    body = _handshake_and_encrypt(secure_client, {"device_id": "d1", "temperature": 5.0})

    first = test_client.post("http://cloud:8001/secure/data", json=body)
    assert first.status_code == 200

    replay = test_client.post("http://cloud:8001/secure/data", json=body)
    assert replay.status_code == 409
    assert cloud_storage_module.get_all_data() == [{"device_id": "d1", "temperature": 5.0}]


def test_out_of_order_lower_counter_rejected_after_higher_one_seen(
    secure_client, cloud_app, test_client
):
    secure_client.send_secure({"device_id": "d1", "temperature": 1.0})
    secure_client.send_secure({"device_id": "d1", "temperature": 2.0})

    # Manually craft a message reusing counter 0 (already superseded by
    # counter 1) against the now-cached session.
    session = secure_client._session
    import json

    nonce = cloud_wire_module.counter_to_nonce(0)
    plaintext = json.dumps({"device_id": "d1", "temperature": 99.0}).encode()
    aad = cloud_wire_module.build_aad(session.session_id, "d1", nonce)
    ciphertext = cloud_wire_module.aead_encrypt(session.key, nonce, plaintext, aad)

    response = test_client.post(
        "http://cloud:8001/secure/data",
        json={
            "session_id": session.session_id,
            "device_id": "d1",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        },
    )
    assert response.status_code == 409


def test_malformed_secure_data_request_returns_422(test_client):
    response = test_client.post("http://cloud:8001/secure/data", json={"session_id": "only-this"})
    assert response.status_code == 422


def test_malformed_base64_returns_400(test_client, cloud_app, secure_client):
    session = secure_client._handshake()
    response = test_client.post(
        "http://cloud:8001/secure/data",
        json={
            "session_id": session.session_id,
            "device_id": "d1",
            "nonce": "not-valid-base64!!!",
            "ciphertext": base64.b64encode(b"x" * 32).decode(),
        },
    )
    assert response.status_code == 400


def test_secure_data_disabled_returns_403_when_mode_off(monkeypatch, test_client, secure_client, cloud_app):
    session = secure_client._handshake()
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "off")
    response = test_client.post(
        "http://cloud:8001/secure/data",
        json={
            "session_id": session.session_id,
            "device_id": "d1",
            "nonce": base64.b64encode(cloud_wire_module.counter_to_nonce(0)).decode(),
            "ciphertext": base64.b64encode(b"x" * 32).decode(),
        },
    )
    assert response.status_code == 403


def test_gateway_transparently_rehandshakes_after_cloud_forgets_session(
    secure_client, cloud_app, test_client
):
    """Simulates 'cloud restarted and forgot the session': the cloud clears
    its SessionStore (as a fresh process would) but the gateway still has a
    cached session. send_secure must re-handshake and deliver the reading
    rather than raising or dropping it."""
    secure_client.send_secure({"device_id": "d1", "temperature": 10.0})
    assert secure_client._session is not None
    first_session_id = secure_client._session.session_id

    # Simulate a cloud restart: a brand new, empty SessionStore replaces the
    # old one (same effect as the process losing all in-memory state), but
    # the router closure captured the old store -- so instead we directly
    # clear the store's sessions the way a restart would leave them absent.
    cloud_app.session_store._sessions.clear()  # noqa: SLF001 (white-box test)

    result = secure_client.send_secure({"device_id": "d1", "temperature": 11.0})
    assert result == {"status": "stored"}
    # Prove re-handshake actually happened (a fresh session_id), rather than
    # only inferring it from the absence of an exception.
    assert secure_client._session.session_id != first_session_id
    stored = cloud_storage_module.get_all_data()
    assert [r["temperature"] for r in stored] == [10.0, 11.0]


def test_cloud_peer_unavailable_during_send_raises_connection_error():
    from .conftest import gateway_client_module

    client = gateway_client_module.SecureCloudClient(base_url="http://127.0.0.1:18392", timeout=1.0)
    with pytest.raises(requests.exceptions.ConnectionError):
        client.send_secure({"device_id": "d1", "temperature": 1.0})
