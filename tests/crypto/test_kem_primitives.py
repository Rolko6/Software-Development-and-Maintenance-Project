"""ML-KEM-768 round-trip correctness, FIPS 203 sizes, and the crypto
primitives in wire.py, exercised against the actual code the services ship
(cloud/app/crypto/keys.py and */crypto/wire.py) rather than a separate
throwaway script."""

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .conftest import cloud_keys_module, cloud_wire_module, gateway_wire_module


def test_keymanager_sizes_match_fips_203_ml_kem_768():
    manager = cloud_keys_module.KeyManager()
    assert len(manager.public_key_bytes) == 1184
    assert len(manager.fingerprint) == 64  # sha256 hex digest


def test_keymanager_roundtrip_via_gateway_encapsulation():
    from cryptography.hazmat.primitives.asymmetric import mlkem

    manager = cloud_keys_module.KeyManager()
    public_key = mlkem.MLKEM768PublicKey.from_public_bytes(manager.public_key_bytes)
    shared_secret, ciphertext = public_key.encapsulate()

    assert len(shared_secret) == 32
    assert len(ciphertext) == 1088

    recovered = manager.decapsulate(ciphertext)
    assert recovered == shared_secret


def test_tampered_ciphertext_is_not_rejected_by_decapsulate_itself():
    """FIPS 203 implicit rejection: a same-length, content-tampered
    ciphertext does not raise -- it silently yields a *different* shared
    secret. Tamper detection is the AEAD layer's job (see
    test_secure_data.py::test_tampered_ciphertext_rejected)."""
    from cryptography.hazmat.primitives.asymmetric import mlkem

    manager = cloud_keys_module.KeyManager()
    public_key = mlkem.MLKEM768PublicKey.from_public_bytes(manager.public_key_bytes)
    shared_secret, ciphertext = public_key.encapsulate()

    tampered = bytearray(ciphertext)
    tampered[7] ^= 0xFF
    recovered = manager.decapsulate(bytes(tampered))

    assert recovered != shared_secret
    assert len(recovered) == 32


def test_wrong_length_ciphertext_raises_value_error():
    manager = cloud_keys_module.KeyManager()
    import pytest

    with pytest.raises(ValueError):
        manager.decapsulate(b"too-short")


def test_wire_module_is_byte_for_byte_identical_between_services():
    """The two copies of wire.py must stay in sync -- see the DUPLICATED
    FILE header comment in both. This test guards against silent drift."""
    from pathlib import Path

    cloud_source = Path(cloud_wire_module.__file__).read_text()
    gateway_source = Path(gateway_wire_module.__file__).read_text()
    assert cloud_source == gateway_source


def test_hkdf_derive_is_deterministic_for_same_inputs():
    shared_secret = b"x" * 32
    client_nonce = b"y" * 16
    key_a = cloud_wire_module.derive_session_key(shared_secret, client_nonce, "cloud-mlkem768-1")
    key_b = cloud_wire_module.derive_session_key(shared_secret, client_nonce, "cloud-mlkem768-1")
    assert key_a == key_b
    assert len(key_a) == 32


def test_hkdf_derive_differs_for_different_salts():
    shared_secret = b"x" * 32
    key_a = cloud_wire_module.derive_session_key(shared_secret, b"a" * 16, "k1")
    key_b = cloud_wire_module.derive_session_key(shared_secret, b"b" * 16, "k1")
    assert key_a != key_b


def test_aead_roundtrip_and_tamper_detection():
    key = AESGCM.generate_key(bit_length=256)
    nonce = cloud_wire_module.counter_to_nonce(0)
    aad = cloud_wire_module.build_aad("sess-1", "dev-1", nonce)
    ciphertext = cloud_wire_module.aead_encrypt(key, nonce, b"payload", aad)

    assert cloud_wire_module.aead_decrypt(key, nonce, ciphertext, aad) == b"payload"

    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    try:
        cloud_wire_module.aead_decrypt(key, nonce, bytes(tampered), aad)
        assert False, "expected InvalidTag"
    except InvalidTag:
        pass


def test_counter_nonce_roundtrip():
    for counter in (0, 1, 255, 65536, 2**32 - 1):
        nonce = cloud_wire_module.counter_to_nonce(counter)
        assert len(nonce) == 12
        assert cloud_wire_module.nonce_to_counter(nonce) == counter


def test_compute_mac_is_domain_separated_by_label():
    psk = b"shared-secret"
    a = cloud_wire_module.compute_mac(psk, b"client", b"part")
    b = cloud_wire_module.compute_mac(psk, b"server", b"part")
    assert a != b
