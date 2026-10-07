from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ML-KEM-768 (FIPS 203) from the `cryptography` package, which uses OpenSSL's
# implementation. The private key is handled as its 64-byte seed.


def generate_keypair():
    """Returns (public_key, private_key_seed) as bytes."""
    private_key = MLKEM768PrivateKey.generate()
    return private_key.public_key().public_bytes_raw(), private_key.private_bytes_raw()


def decapsulate(private_key: bytes, kem_ciphertext: bytes) -> bytes:
    """Returns the 32-byte shared secret. Raises ValueError on a malformed
    ciphertext; a tampered one yields a different secret (implicit rejection)."""
    return MLKEM768PrivateKey.from_seed_bytes(private_key).decapsulate(kem_ciphertext)


def decrypt_payload(shared_secret: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Returns the decrypted plaintext. Raises InvalidTag on tamper/wrong key.
    The ML-KEM shared secret is 32 uniformly random bytes, so it is used
    directly as the AES-256-GCM key."""
    return AESGCM(shared_secret).decrypt(nonce, ciphertext, None)
