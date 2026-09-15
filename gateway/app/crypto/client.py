"""Initiator side of the gateway<->cloud ML-KEM secure channel.

`SecureCloudClient` performs an ML-KEM-768 handshake against the cloud's
``/secure/handshake`` endpoints, caches the resulting AES-256-GCM session
key, and encrypts readings for ``POST /secure/data``. It transparently
re-handshakes when the cached session is unknown or expired to the cloud
(e.g. after a cloud restart, which forgets every in-memory session), and
proactively rekeys shortly before the cached session's TTL would otherwise
expire so the common path never pays for a round trip to discover that.

All failures raise a subclass of ``requests.exceptions.RequestException``
(see exceptions.py), matching the exception family the existing plaintext
``send_to_cloud`` raises today.

Concurrency: sending is serialized per client instance with a single lock
held across "read counter -> encrypt -> POST -> commit counter" (including
the re-handshake-and-retry path). FastAPI's sync endpoints run on a
threadpool, so without this a race between two concurrent device-data
requests could increment the shared counter non-atomically and reuse a
nonce under the same AES-GCM key -- catastrophic for GCM. For this
project's single-device, one-reading-every-five-seconds workload this is
not a throughput bottleneck; a sliding replay window (rather than a single
strictly-increasing counter) would be the natural extension if concurrent
senders under one session were ever needed.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import time
from typing import Callable, Optional

import requests
from cryptography.hazmat.primitives.asymmetric import mlkem

from . import wire
from .exceptions import HandshakeAuthenticationError, PeerTrustError, ProtocolError
from .session import ClientSession

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_REKEY_SKEW_SECONDS = 15.0

HttpGet = Callable[[str, float], "requests.Response"]
HttpPost = Callable[[str, dict, float], "requests.Response"]


def _default_http_get(url: str, timeout: float) -> "requests.Response":
    return requests.get(url, timeout=timeout)


def _default_http_post(url: str, json_body: dict, timeout: float) -> "requests.Response":
    return requests.post(url, json=json_body, timeout=timeout)


class SecureCloudClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        psk: Optional[bytes] = None,
        pinned_fingerprint: Optional[str] = None,
        rekey_skew_seconds: float = DEFAULT_REKEY_SKEW_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_get: HttpGet = _default_http_get,
        http_post: HttpPost = _default_http_post,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("GATEWAY_CLOUD_BASE_URL", "http://localhost:8001")
        ).rstrip("/")
        self._psk = psk if psk is not None else wire.get_psk()
        self._pinned_fingerprint = (
            pinned_fingerprint
            if pinned_fingerprint is not None
            else (os.environ.get("GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT") or None)
        )
        self._skew = rekey_skew_seconds
        self._timeout = timeout
        self._http_get = http_get
        self._http_post = http_post
        self._lock = threading.Lock()
        self._session: Optional[ClientSession] = None

    # -- URLs ----------------------------------------------------------

    def _handshake_url(self) -> str:
        return f"{self._base_url}/secure/handshake"

    def _data_url(self) -> str:
        return f"{self._base_url}/secure/data"

    # -- Handshake -------------------------------------------------------

    def _fetch_encapsulation_key(self):
        response = self._http_get(self._handshake_url(), self._timeout)
        response.raise_for_status()
        try:
            body = response.json()
            key_id = body["key_id"]
            ek_bytes = base64.b64decode(body["encapsulation_key"], validate=True)
            fingerprint = body["fingerprint"]
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise ProtocolError("malformed handshake info from cloud") from exc

        if len(ek_bytes) != wire.EK_LEN:
            raise ProtocolError(f"unexpected encapsulation key length: {len(ek_bytes)}")
        if fingerprint != wire.fingerprint(ek_bytes):
            raise ProtocolError("encapsulation key fingerprint does not match its bytes")
        if self._pinned_fingerprint and fingerprint.lower() != self._pinned_fingerprint.lower():
            raise PeerTrustError(
                "cloud encapsulation key fingerprint does not match "
                "GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT"
            )
        return key_id, ek_bytes, fingerprint

    def _handshake(self) -> ClientSession:
        key_id, ek_bytes, fingerprint = self._fetch_encapsulation_key()
        public_key = mlkem.MLKEM768PublicKey.from_public_bytes(ek_bytes)
        shared_secret, ciphertext = public_key.encapsulate()
        client_nonce = os.urandom(wire.CLIENT_NONCE_LEN)
        fingerprint_bytes = bytes.fromhex(fingerprint)

        mac_b64 = None
        if self._psk is not None:
            mac = wire.compute_mac(
                self._psk, b"client", key_id.encode("utf-8"), client_nonce, fingerprint_bytes, ciphertext
            )
            mac_b64 = base64.b64encode(mac).decode("ascii")

        request_body = {
            "key_id": key_id,
            "client_nonce": base64.b64encode(client_nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "mac": mac_b64,
        }
        response = self._http_post(self._handshake_url(), request_body, self._timeout)
        response.raise_for_status()

        try:
            body = response.json()
            session_id = body["session_id"]
            expires_at = float(body["expires_at"])
            server_mac_b64 = body.get("server_mac")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("malformed handshake response from cloud") from exc

        if self._psk is not None:
            expected = wire.compute_mac(
                self._psk,
                b"server",
                key_id.encode("utf-8"),
                client_nonce,
                fingerprint_bytes,
                ciphertext,
                session_id.encode("utf-8"),
            )
            try:
                got = base64.b64decode(server_mac_b64, validate=True) if server_mac_b64 else b""
            except (binascii.Error, ValueError) as exc:
                raise ProtocolError("malformed server_mac from cloud") from exc
            if not wire.constant_time_equal(expected, got):
                raise HandshakeAuthenticationError(
                    "cloud did not prove knowledge of the pre-shared key "
                    "(wrong ML_KEM_PSK, or a machine-in-the-middle)"
                )

        session_key = wire.derive_session_key(shared_secret, client_nonce, key_id)
        session = ClientSession(session_id=session_id, key=session_key, expires_at=expires_at, counter=-1)
        self._session = session
        return session

    def _ensure_fresh_session(self) -> ClientSession:
        session = self._session
        if session is None or time.time() >= (session.expires_at - self._skew):
            session = self._handshake()
        return session

    # -- Data --------------------------------------------------------------

    def send_secure(self, payload: dict) -> dict:
        """Encrypt and send one sensor reading to the cloud.

        Returns the cloud's decoded JSON response (mirrors the existing
        ``send_to_cloud(sensor_data) -> dict`` contract). Raises a
        ``requests.exceptions.RequestException`` subclass on any failure
        (network, protocol, or the cloud rejecting the request).
        """
        with self._lock:
            return self._send_locked(payload)

    def _send_locked(self, payload: dict, _retried: bool = False) -> dict:
        session = self._ensure_fresh_session()
        counter = session.counter + 1
        nonce = wire.counter_to_nonce(counter)
        device_id = str(payload.get("device_id", ""))
        plaintext = json.dumps(payload).encode("utf-8")
        aad = wire.build_aad(session.session_id, device_id, nonce)
        ciphertext = wire.aead_encrypt(session.key, nonce, plaintext, aad)

        request_body = {
            "session_id": session.session_id,
            "device_id": device_id,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        response = self._http_post(self._data_url(), request_body, self._timeout)

        if response.status_code in (404, 410) and not _retried:
            # Unknown/expired session on the cloud side -- most likely the
            # cloud process restarted and forgot its in-memory sessions.
            # Re-handshake once and retry the same reading rather than
            # dropping it.
            self._session = None
            return self._send_locked(payload, _retried=True)

        response.raise_for_status()
        session.counter = counter
        return response.json()


_default_client: Optional[SecureCloudClient] = None
_default_client_lock = threading.Lock()


def get_default_client() -> SecureCloudClient:
    global _default_client
    if _default_client is None:
        with _default_client_lock:
            if _default_client is None:
                _default_client = SecureCloudClient()
    return _default_client


def send_secure(payload: dict) -> dict:
    """Convenience wrapper around a process-wide default SecureCloudClient.
    See SecureCloudClient.send_secure for the contract."""
    return get_default_client().send_secure(payload)
