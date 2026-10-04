import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kyber_py.ml_kem.default_parameters import ML_KEM_768

from app.crypto import encapsulate, encrypt_payload


def test_encapsulate_produces_correct_sizes():
    public_key, _ = ML_KEM_768.keygen()

    shared_secret, kem_ciphertext = encapsulate(public_key)

    assert len(shared_secret) == 32
    assert len(kem_ciphertext) == 1088


def test_encapsulate_output_decapsulates_correctly_on_the_other_side():
    # Simulates the cloud side using the raw library directly — gateway's
    # own crypto.py only ever implements the client (encapsulate) half.
    public_key, private_key = ML_KEM_768.keygen()

    shared_secret, kem_ciphertext = encapsulate(public_key)
    shared_secret_on_cloud_side = ML_KEM_768.decaps(private_key, kem_ciphertext)

    assert shared_secret == shared_secret_on_cloud_side


def test_encrypt_payload_round_trips_with_matching_shared_secret():
    shared_secret = os.urandom(32)

    nonce, ciphertext = encrypt_payload(shared_secret, b'{"temperature": 21.5}')
    plaintext = AESGCM(shared_secret).decrypt(nonce, ciphertext, None)

    assert plaintext == b'{"temperature": 21.5}'


def test_encrypt_payload_uses_a_fresh_nonce_each_time():
    shared_secret = os.urandom(32)

    nonces = {encrypt_payload(shared_secret, b"x")[0] for _ in range(20)}

    assert len(nonces) == 20
