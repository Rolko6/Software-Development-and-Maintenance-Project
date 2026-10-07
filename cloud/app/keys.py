import base64
import os

from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey

# Pre-shared at deployment time rather than fetched over the network at
# runtime, so there's nothing for a man-in-the-middle to intercept on
# bootstrap. The value comes from the untracked .env file written by
# scripts/generate_keys.py and must never be committed. The private key
# never leaves this process.
PRIVATE_KEY = base64.b64decode(os.environ["CLOUD_ML_KEM_PRIVATE_KEY"])

# Fail at startup, not on the first request, if this is not a valid
# ML-KEM-768 private key seed.
MLKEM768PrivateKey.from_seed_bytes(PRIVATE_KEY)
