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
    reserve-counter/encrypt/post sequence."""
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


def _stored_temperatures():
    from .conftest import cloud_storage_module

    return [reading["temperature"] for reading in cloud_storage_module.stored_data]


def _client_with_flaky_data_post(test_client, fail_on_call, fail_after_delivery):
    """A SecureCloudClient whose ``fail_on_call``-th POST /secure/data raises
    a timeout. With ``fail_after_delivery`` the request reaches the cloud
    first (the reading is stored, the response is lost); without it the
    request never arrives. Returns (client, sent) where ``sent`` lists the
    base64 nonce of every /secure/data request the client made."""
    from .conftest import gateway_client_module

    http_get, http_post = make_transport(test_client)
    sent = []

    def flaky_post(url, json_body, timeout):
        if not url.endswith("/secure/data"):
            return http_post(url, json_body, timeout)
        sent.append(json_body["nonce"])
        if len(sent) == fail_on_call:
            if fail_after_delivery:
                http_post(url, json_body, timeout)
            raise requests.exceptions.ReadTimeout("simulated lost response")
        return http_post(url, json_body, timeout)

    client = gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=flaky_post
    )
    return client, sent


def test_lost_response_does_not_reuse_a_nonce(test_client, cloud_app, monkeypatch):
    """S1 regression: the cloud stores a reading but its response is lost.
    The next, different reading must not be encrypted under the same key
    with the same nonce (AES-GCM nonce reuse), and the cloud must accept it
    instead of answering 409 until the session expires."""
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    client, sent = _client_with_flaky_data_post(test_client, fail_on_call=2, fail_after_delivery=True)

    client.send_secure({"device_id": "d1", "temperature": 20.0})
    try:
        client.send_secure({"device_id": "d1", "temperature": 21.0})
    except requests.exceptions.Timeout:
        pass
    client.send_secure({"device_id": "d1", "temperature": 22.0})

    assert len(sent) == len(set(sent)) == 3
    assert _stored_temperatures() == [20.0, 21.0, 22.0]


def test_request_lost_before_delivery_leaves_a_usable_session(test_client, cloud_app, monkeypatch):
    """A request that never reaches the cloud also consumes its counter.
    The cloud accepts the resulting gap, so the session keeps working."""
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    client, sent = _client_with_flaky_data_post(test_client, fail_on_call=2, fail_after_delivery=False)

    client.send_secure({"device_id": "d1", "temperature": 20.0})
    session_id = client._session.session_id
    try:
        client.send_secure({"device_id": "d1", "temperature": 21.0})
    except requests.exceptions.Timeout:
        pass
    client.send_secure({"device_id": "d1", "temperature": 22.0})

    assert len(sent) == len(set(sent)) == 3
    assert client._session.session_id == session_id
    assert _stored_temperatures() == [20.0, 22.0]


def test_counter_rejected_as_replay_triggers_a_new_session(secure_client, cloud_app):
    """If the cloud still answers 409 (client and cloud counters out of
    step for any reason), the client drops the session, re-handshakes and
    delivers the reading under a fresh key instead of failing every reading
    until the session expires."""
    secure_client.send_secure({"device_id": "d1", "temperature": 20.0})
    secure_client.send_secure({"device_id": "d1", "temperature": 21.0})
    first_session_id = secure_client._session.session_id
    secure_client._session.counter = -1  # force the next nonce to repeat counter 0

    secure_client.send_secure({"device_id": "d1", "temperature": 22.0})

    assert secure_client._session.session_id != first_session_id
    assert _stored_temperatures() == [20.0, 21.0, 22.0]
