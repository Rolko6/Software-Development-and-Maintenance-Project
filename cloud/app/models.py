from pydantic import BaseModel, Field


class SensorData(BaseModel):
    device_id: str

    # NaN and Infinity cannot be written back as JSON, so a stored one would
    # make every later GET /data fail. Checked here so that both /data and
    # /data/secure reject them.
    temperature: float = Field(allow_inf_nan=False)


class SecureEnvelope(BaseModel):
    """ML-KEM-encapsulated + AES-GCM-encrypted request body for /data/secure.
    All three fields are base64-encoded bytes."""
    kem_ciphertext: str
    nonce: str
    ciphertext: str