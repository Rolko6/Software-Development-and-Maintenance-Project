"""Gateway-specific behaviour not already covered by test_handshake.py /
test_secure_data.py: exception hierarchy, proactive rekey before expiry,
and serialized concurrent sends (nonce-reuse prevention)."""

import threading
import time

import requests

from .conftest import gateway_exceptions_module, make_transport


def test_exception_hierarchy_matches_requests_request_exception():
    assert issubclass(
        gateway_exceptions_module.SecureCloudError, requests.exceptions.RequestException
    )
    for cls in (
        gateway_exceptions_module.HandshakeAuthenticationError,
        gateway_exceptions_module.PeerTrustError,
        gateway_exceptions_module.ProtocolError,
    ):
        assert issubclass(cls, gateway_exceptions_module.SecureCloudError)
        assert issubclass(cls, requests.exceptions.RequestException)


def test_proactive_rekey_before_expiry(secure_client, cloud_app):
    """A session with very little time left should trigger a fresh
    handshake on the next send rather than being used until it actually
    expires and gets a 410 round trip."""
    secure_client.send_secure({"device_id": "d1", "temperature": 1.0})
    first_session_id = secure_client._session.session_id

    # Simulate "about to expire": within the rekey skew window.
    secure_client._session.expires_at = time.time() + 1  # well under the 15s default skew

    secure_client.send_secure({"device_id": "d1", "temperature": 2.0})
    assert secure_client._session.session_id != first_session_id


def test_concurrent_sends_do_not_reuse_a_counter(test_client, cloud_app, monkeypatch):
    """Two threads calling send_secure concurrently on one SecureCloudClient
    must not produce two messages with the same (session, counter): the
    client's internal lock serializes the whole
    read-counter/encrypt/post/commit sequence."""
    from .conftest import gateway_client_module

    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    http_get, http_post = make_transport(test_client)

    seen_nonces = []
    lock = threading.Lock()
    real_post = http_post

    def recording_post(url, json_body, timeout):
        response = real_post(url, json_body, timeout)
        if url.endswith("/secure/data"):
            with lock:
                seen_nonces.append(json_body["nonce"])
        return response

    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=recording_post
    )
    client._handshake()

    def worker(i):
        client.send_secure({"device_id": "d1", "temperature": float(i)})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen_nonces) == len(set(seen_nonces)) == 8
