"""Exceptions raised by gateway.app.crypto.

All of these subclass ``requests.exceptions.RequestException`` -- the same
exception family the existing plaintext ``send_to_cloud`` raises today (via
``requests.post(...).raise_for_status()`` -> ``HTTPError``, or a transport
failure -> ``ConnectionError``/``Timeout``, both RequestException
subclasses). Because gateway.app.main's ``receive_device_data`` catches a
bare ``Exception`` around the forwarding call and maps it to HTTP 502, this
is not strictly required for that handler to keep working -- but it is
required by design so that any *other*, more specific error handling added
later around ``send_to_cloud``/``send_secure`` keeps working unmodified
when a device reading moves from the plaintext path to the secure one.
"""

from __future__ import annotations

import requests


class SecureCloudError(requests.exceptions.RequestException):
    """Base class for ML-KEM secure-channel failures."""


class HandshakeAuthenticationError(SecureCloudError):
    """The cloud's server MAC did not match ours (PSK mismatch, or a
    machine-in-the-middle answered the handshake instead of the real
    cloud). Only raised when ML_KEM_PSK is configured on the gateway."""


class PeerTrustError(SecureCloudError):
    """The cloud's published encapsulation key failed the pinned
    fingerprint check (GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT)."""


class ProtocolError(SecureCloudError):
    """The cloud returned data that does not match the expected wire
    format (missing field, wrong size, wrong type)."""
