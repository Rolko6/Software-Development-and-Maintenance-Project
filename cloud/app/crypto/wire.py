"""Shared ML-KEM handshake wire format and crypto helpers.

DUPLICATED FILE: this exact module is copied verbatim into both
``cloud/app/crypto/wire.py`` and ``gateway/app/crypto/wire.py``. The two
services build into separate container images and cannot import each
other, so the framing and crypto glue that both sides must agree on
byte-for-byte is duplicated here rather than shared via a package.

If you change anything in this file, make the identical change in the
other copy. See the "Message protection" and "Wire format" sections of
docs/security/ml-kem-integration.md for the design this implements.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# --- Protocol identifiers -------------------------------------------------

PROTOCOL_VERSION = "mlkem-gw-cloud-v1"
KEM_ALGORITHM = "ML-KEM-768"
AEAD_ALGORITHM = "AES-256-GCM"

# --- FIPS 203 ML-KEM-768 fixed sizes (bytes) ------------------------------
# Source: NIST FIPS 203 (https://csrc.nist.gov/pubs/fips/203/final) and
# confirmed against cryptography==50.0.1's mlkem module locally (see
# docs/decisions/0002-ml-kem-key-establishment.md, "Verification").

EK_LEN = 1184
CIPHERTEXT_LEN = 1088
SHARED_SECRET_LEN = 32

# --- Session-layer sizes ---------------------------------------------------

CLIENT_NONCE_LEN = 16
NONCE_LEN = 12
SESSION_KEY_LEN = 32  # AES-256-GCM key


def fingerprint(ek_bytes: bytes) -> str:
    """SHA-256 fingerprint of a raw ML-KEM-768 encapsulation key, hex-encoded.

    The encapsulation key is public data (KEM security does not require it
    to be secret); the fingerprint exists so it can be logged, pinned
    (GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT), and bound into the handshake MAC.
    """
    return hashlib.sha256(ek_bytes).hexdigest()


def derive_session_key(shared_secret: bytes, client_nonce: bytes, key_id: str) -> bytes:
    """HKDF-SHA256(shared_secret) -> 32-byte AES-256-GCM session key.

    salt = client_nonce: fresh random bytes chosen by the gateway for this
    handshake attempt, so a byte-for-byte replay of an old handshake message
    derives the same key an idempotent number of times rather than a *new*
    exploitable key, and two different handshakes never share a salt.

    info = protocol version + role + key_id: domain-separates this key from
    any other use of the same ML-KEM shared secret and from other cloud keys.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=SESSION_KEY_LEN,
        salt=client_nonce,
        info=f"{PROTOCOL_VERSION}|session|{key_id}".encode("utf-8"),
    )
    return hkdf.derive(shared_secret)


def build_aad(session_id: str, device_id: str, nonce: bytes) -> bytes:
    """Associated data for the per-message AEAD.

    Binds the ciphertext to: the protocol version, the session it was
    encrypted under, the device_id claimed alongside it, and its own nonce.
    A valid ciphertext therefore cannot be replayed under a different
    session_id, nor relabeled with a different device_id, without failing
    AEAD authentication (cryptography.exceptions.InvalidTag).
    """
    return (
        PROTOCOL_VERSION.encode("utf-8") + b"|"
        + session_id.encode("utf-8") + b"|"
        + device_id.encode("utf-8") + b"|"
        + nonce
    )


def counter_to_nonce(counter: int) -> bytes:
    """Deterministic nonce = big-endian 12-byte message counter.

    This is safe from nonce reuse because (a) every session has a freshly
    HKDF-derived key that is never reused across sessions, and (b) the
    counter is enforced strictly increasing per session by the cloud's
    SessionStore and only ever incremented by the gateway's serialized
    SecureCloudClient -- so a given (key, nonce) pair is used at most once.
    See "Message protection" / nonce strategy in the design doc for the
    process-restart argument that makes this hold across gateway restarts.
    """
    return counter.to_bytes(NONCE_LEN, "big")


def nonce_to_counter(nonce: bytes) -> int:
    return int.from_bytes(nonce, "big")


def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    return AESGCM(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Raises cryptography.exceptions.InvalidTag on tampering, wrong key, or
    mismatched associated data."""
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def compute_mac(psk: bytes, label: bytes, *parts: bytes) -> bytes:
    """HMAC-SHA256(psk, label || '|' || parts...).

    `label` domain-separates the client->cloud MAC (b"client") from the
    cloud->gateway confirmation MAC (b"server") so one can never be replayed
    in place of the other.
    """
    mac = hmac.new(psk, digestmod=hashlib.sha256)
    mac.update(label)
    for part in parts:
        mac.update(b"|")
        mac.update(part)
    return mac.digest()


def constant_time_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


def get_psk() -> Optional[bytes]:
    """Reads the shared pre-shared-key trust anchor from ML_KEM_PSK.

    Read fresh from the environment on every call (not cached at import
    time) so both tests and a live operator changing the environment take
    effect without extra caching logic. Returns None when unset or empty,
    in which case the handshake is unauthenticated -- see the peer/key
    trust section of docs/security/ml-kem-integration.md.
    """
    value = os.environ.get("ML_KEM_PSK")
    return value.encode("utf-8") if value else None
