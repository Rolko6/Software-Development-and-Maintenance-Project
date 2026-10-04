import os

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app.crypto import decapsulate, decrypt_payload, generate_keypair


def test_generate_keypair_sizes():
    # ML-KEM-768 sizes per FIPS 203.
    public_key, private_key = generate_keypair()

    assert len(public_key) == 1184
    assert len(private_key) == 2400


def test_decapsulate_matches_encapsulation():
    public_key, private_key = generate_keypair()
    shared_secret, kem_ciphertext = ML_KEM_768.encaps(public_key)

    assert decapsulate(private_key, kem_ciphertext) == shared_secret


def test_decapsulate_wrong_private_key_gives_different_secret():
    public_key, _ = generate_keypair()
    _, wrong_private_key = generate_keypair()
    shared_secret, kem_ciphertext = ML_KEM_768.encaps(public_key)

    assert decapsulate(wrong_private_key, kem_ciphertext) != shared_secret


def test_decapsulate_tampered_ciphertext_gives_different_secret():
    # FIPS 203 "implicit rejection": a tampered ciphertext doesn't raise,
    # it silently decapsulates to a different (wrong) secret.
    public_key, private_key = generate_keypair()
    shared_secret, kem_ciphertext = ML_KEM_768.encaps(public_key)

    tampered = bytearray(kem_ciphertext)
    tampered[0] ^= 0xFF

    assert decapsulate(private_key, bytes(tampered)) != shared_secret


def test_decrypt_payload_round_trip():
    shared_secret = os.urandom(32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, b"hello", None)

    assert decrypt_payload(shared_secret, nonce, ciphertext) == b"hello"


def test_decrypt_payload_tampered_ciphertext_raises():
    shared_secret = os.urandom(32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, b"hello", None)
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF

    with pytest.raises(InvalidTag):
        decrypt_payload(shared_secret, nonce, bytes(tampered))


def test_decrypt_payload_wrong_shared_secret_raises():
    shared_secret = os.urandom(32)
    wrong_secret = os.urandom(32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(shared_secret).encrypt(nonce, b"hello", None)

    with pytest.raises(InvalidTag):
        decrypt_payload(wrong_secret, nonce, ciphertext)
