import base64
import os

from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PublicKey

# Pre-shared at deployment time (from the .env file written by
# scripts/generate_keys.py) rather than fetched from the cloud at runtime, so
# there's nothing for a man-in-the-middle to intercept/substitute on bootstrap.
CLOUD_PUBLIC_KEY = base64.b64decode(os.environ["CLOUD_ML_KEM_PUBLIC_KEY"])

# Fail at startup, not on the first request, if this is not a valid
# ML-KEM-768 public key.
MLKEM768PublicKey.from_public_bytes(CLOUD_PUBLIC_KEY)
