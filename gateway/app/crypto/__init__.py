"""ML-KEM secure-channel initiator package for the gateway service.

Exposes ``send_secure(payload) -> dict`` (backed by a process-wide default
``SecureCloudClient``) and the ``GATEWAY_ML_KEM_MODE`` mode-switch helpers.
See docs/security/ml-kem-integration.md for the full design and the exact
integration patch for gateway/app/cloud_client.py.
"""

from .client import SecureCloudClient, get_default_client, send_secure
from .exceptions import (
    HandshakeAuthenticationError,
    PeerTrustError,
    ProtocolError,
    SecureCloudError,
)
from .mode import get_gateway_mode, secure_channel_enabled

__all__ = [
    "SecureCloudClient",
    "get_default_client",
    "send_secure",
    "get_gateway_mode",
    "secure_channel_enabled",
    "SecureCloudError",
    "HandshakeAuthenticationError",
    "PeerTrustError",
    "ProtocolError",
]
