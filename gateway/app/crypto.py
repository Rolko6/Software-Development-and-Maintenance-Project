import os

from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encapsulate(public_key: bytes):
    """Returns (shared_secret, kem_ciphertext), using ML-KEM-768 from the
    `cryptography` package (OpenSSL). Raises ValueError on a malformed key."""
    return MLKEM768PublicKey.from_public_bytes(public_key).encapsulate()


def encrypt_payload(shared_secret: bytes, plaintext: bytes):
    """Returns (nonce, ciphertext). A fresh random nonce is used every call.
    The 32-byte ML-KEM shared secret is used directly as the AES-256-GCM key."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, plaintext, None)
    return nonce, ciphertext
