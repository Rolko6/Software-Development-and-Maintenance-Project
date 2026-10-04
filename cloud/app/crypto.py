from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kyber_py.ml_kem.default_parameters import ML_KEM_768


def generate_keypair():
    """Returns (public_key, private_key) as bytes."""
    return ML_KEM_768.keygen()


def decapsulate(private_key: bytes, kem_ciphertext: bytes) -> bytes:
    """Returns the 32-byte shared secret."""
    return ML_KEM_768.decaps(private_key, kem_ciphertext)


def decrypt_payload(shared_secret: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Returns the decrypted plaintext. Raises InvalidTag on tamper/wrong key."""
    return AESGCM(shared_secret).decrypt(nonce, ciphertext, None)
