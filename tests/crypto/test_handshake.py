"""Handshake-layer tests: success, mutual PSK authentication, pinned
fingerprint, and the malformed/unavailable negative cases."""

import base64

import pytest
import requests

from .conftest import (
    gateway_client_module,
    gateway_exceptions_module,
    make_transport,
)


def test_successful_handshake_without_psk(secure_client, cloud_app):
    session = secure_client._handshake()
    assert session.session_id
    assert len(session.key) == 32
    assert session.expires_at > 0
    assert cloud_app.session_store.get(session.session_id)[0] is not None


def test_successful_handshake_with_mutual_psk(monkeypatch, test_client, cloud_app):
    monkeypatch.setenv("ML_KEM_PSK", "correct-horse-battery-staple")
    http_get, http_post = make_transport(test_client)
    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=http_post
    )
    session = client._handshake()
    assert session.session_id


def test_handshake_rejected_when_client_mac_missing_but_cloud_requires_psk(
    monkeypatch, test_client
):
    """Cloud has a PSK configured; gateway does not send one. Expect 401,
    surfaced to the gateway as an HTTPError (a RequestException subclass).

    The client's `psk` is resolved once at construction time (SecureCloudClient
    reads ML_KEM_PSK via wire.get_psk() in __init__), so it must be built
    *before* the test sets ML_KEM_PSK for the cloud side -- otherwise the
    client would pick up the same value and authenticate correctly. The
    cloud side, by contrast, calls get_psk() fresh on every request (see
    mode.py), so setting the env var right before the handshake call is
    exactly when the cloud-side requirement takes effect.
    """
    http_get, http_post = make_transport(test_client)
    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=http_post, psk=None
    )
    monkeypatch.setenv("ML_KEM_PSK", "cloud-side-secret")

    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        client._handshake()
    assert excinfo.value.response.status_code == 401


def test_handshake_rejected_on_wrong_psk(monkeypatch, test_client):
    monkeypatch.setenv("ML_KEM_PSK", "cloud-side-secret")
    http_get, http_post = make_transport(test_client)
    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001",
        http_get=http_get,
        http_post=http_post,
        psk=b"gateway-has-the-wrong-secret",
    )
    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        client._handshake()
    assert excinfo.value.response.status_code == 401


def test_gateway_rejects_handshake_if_server_mac_is_forged():
    """Simulates a machine-in-the-middle that answers the handshake with
    its own (unrelated) session but cannot produce a valid server_mac
    because it does not know the PSK. Exercised by monkeypatching the
    transport to return a response with a wrong server_mac."""
    psk = b"shared-secret"

    def http_get(url, timeout):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "key_id": "k1",
                    "algorithm": "ML-KEM-768",
                    "encapsulation_key": base64.b64encode(b"\x00" * 1184).decode(),
                    "fingerprint": __import__("hashlib").sha256(b"\x00" * 1184).hexdigest(),
                }

        return R()

    def http_post(url, json_body, timeout):
        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "session_id": "attacker-session",
                    "expires_at": 9999999999.0,
                    "server_mac": base64.b64encode(b"\x00" * 32).decode(),
                }

        return R()

    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=http_post, psk=psk
    )
    with pytest.raises(gateway_exceptions_module.HandshakeAuthenticationError):
        client._handshake()


def test_gateway_pinned_fingerprint_rejects_wrong_cloud_key(test_client):
    http_get, http_post = make_transport(test_client)
    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001",
        http_get=http_get,
        http_post=http_post,
        pinned_fingerprint="0" * 64,  # deliberately wrong
    )
    with pytest.raises(gateway_exceptions_module.PeerTrustError):
        client._handshake()


def test_gateway_pinned_fingerprint_accepts_matching_cloud_key(test_client, cloud_app):
    http_get, http_post = make_transport(test_client)
    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001",
        http_get=http_get,
        http_post=http_post,
        pinned_fingerprint=cloud_app.key_manager.fingerprint,
    )
    session = client._handshake()
    assert session.session_id


def test_malformed_handshake_body_returns_422(test_client):
    response = test_client.post("http://cloud:8001/secure/handshake", json={"key_id": "only-this"})
    assert response.status_code == 422


def test_handshake_wrong_length_ciphertext_returns_400(test_client, cloud_app):
    response = test_client.post(
        "http://cloud:8001/secure/handshake",
        json={
            "key_id": cloud_app.key_manager.key_id,
            "client_nonce": base64.b64encode(b"x" * 16).decode(),
            "ciphertext": base64.b64encode(b"too-short").decode(),
            "mac": None,
        },
    )
    assert response.status_code == 400


def test_handshake_unknown_key_id_returns_404(test_client):
    response = test_client.post(
        "http://cloud:8001/secure/handshake",
        json={
            "key_id": "not-the-real-key-id",
            "client_nonce": base64.b64encode(b"x" * 16).decode(),
            "ciphertext": base64.b64encode(b"y" * 1088).decode(),
            "mac": None,
        },
    )
    assert response.status_code == 404


def test_secure_endpoints_disabled_returns_403_when_mode_off(monkeypatch, test_client):
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "off")
    response = test_client.get("http://cloud:8001/secure/handshake")
    assert response.status_code == 403


def test_cloud_peer_unavailable_during_handshake_raises_connection_error():
    """No mocking: point at a real loopback port with nothing listening.
    This never binds a port (only attempts an outgoing connection), so it
    does not conflict with any other agent's use of 8000/8001/18000/18001."""
    client = gateway_client_module.SecureCloudClient(base_url="http://127.0.0.1:18391", timeout=1.0)
    with pytest.raises(requests.exceptions.ConnectionError):
        client._handshake()
