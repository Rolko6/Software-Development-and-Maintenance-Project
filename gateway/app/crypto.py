import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kyber_py.ml_kem.default_parameters import ML_KEM_768


def encapsulate(public_key: bytes):
    """Returns (shared_secret, kem_ciphertext)."""
    return ML_KEM_768.encaps(public_key)


def encrypt_payload(shared_secret: bytes, plaintext: bytes):
    """Returns (nonce, ciphertext). A fresh random nonce is used every call."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, plaintext, None)
    return nonce, ciphertext
