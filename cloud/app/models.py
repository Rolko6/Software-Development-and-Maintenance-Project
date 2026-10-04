from pydantic import BaseModel


class SensorData(BaseModel):
    device_id: str
    temperature: float


class SecureEnvelope(BaseModel):
    """ML-KEM-encapsulated + AES-GCM-encrypted request body for /data/secure.
    All three fields are base64-encoded bytes."""
    kem_ciphertext: str
    nonce: str
    ciphertext: str