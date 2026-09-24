"""Pydantic request/response models for the cloud's /secure/* endpoints.

See "Wire format" in docs/security/ml-kem-integration.md for field
encodings (all binary fields are base64, standard alphabet, padded).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HandshakeInfo(BaseModel):
    key_id: str
    algorithm: str
    encapsulation_key: str  # base64, 1184 raw bytes
    fingerprint: str  # sha256 hex digest of the raw encapsulation key


class HandshakeRequest(BaseModel):
    key_id: str
    client_nonce: str  # base64, 16 raw bytes
    ciphertext: str  # base64, 1088 raw bytes (ML-KEM-768 ciphertext)
    mac: Optional[str] = None  # base64 HMAC-SHA256, present iff ML_KEM_PSK is set


class HandshakeResponse(BaseModel):
    session_id: str
    expires_at: float  # UNIX epoch seconds
    algorithm: str
    aead: str
    server_mac: Optional[str] = None  # base64 HMAC-SHA256, present iff ML_KEM_PSK is set


class SecureDataRequest(BaseModel):
    session_id: str
    device_id: str = Field(min_length=1, max_length=200)
    nonce: str  # base64, 12 raw bytes (== big-endian message counter)
    ciphertext: str  # base64, AES-256-GCM ciphertext with 16-byte tag appended


class SecureDataResponse(BaseModel):
    status: str
