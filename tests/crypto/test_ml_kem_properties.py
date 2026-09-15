"""Behavioural properties FIPS 203 requires, checked without NIST vectors.

The known-answer tests in `test_ml_kem_acvp_kat.py` establish conformance on
the inputs NIST chose. These tests cover the behaviour a caller depends on for
inputs nobody chose in advance: fresh keys, tampered ciphertexts, and mismatched
parameter sets.

Together the two files answer "is this ML-KEM?". Neither answers "is ML-KEM
quantum-resistant?" — that is a property of the Module-LWE problem and NIST's
cryptanalysis, not something a test can execute. See
docs/testing/ml-kem-verification.md.
"""

import pytest

from support import (
    FIPS_203_PARAMETERS,
    RING_DEGREE,
    RING_MODULUS,
    implementations,
)


ML_KEM = implementations()

PARAMETER_SETS = sorted(FIPS_203_PARAMETERS)


@pytest.fixture(scope="module")
def keypair_768():
    return ML_KEM["ML-KEM-768"].keygen()


@pytest.mark.parametrize("name", PARAMETER_SETS)
def test_lattice_parameters_match_the_standard(name):
    """Section 8: the published parameters, compared against the library.

    A downgraded k or a smaller modulus would still round-trip correctly while
    offering less security than the name implies, so the values are asserted
    against the standard rather than read back from the object under test.
    """
    kem = ML_KEM[name]

    expected = FIPS_203_PARAMETERS[name]

    assert kem.k == expected["k"]
    assert kem.eta_1 == expected["eta_1"]
    assert kem.eta_2 == expected["eta_2"]
    assert kem.du == expected["du"]
    assert kem.dv == expected["dv"]
    assert kem.oid == expected["oid"], "object identifier must match FIPS 203"

    assert kem.R.q == RING_MODULUS, "ML-KEM is defined over Z_3329"
    assert kem.R.n == RING_DEGREE, "ML-KEM polynomials have degree 256"


@pytest.mark.parametrize("name", PARAMETER_SETS)
def test_artifact_sizes_match_the_standard(name):
    """Table 2: wire sizes are a cheap, visible fingerprint of the algorithm.

    These are the numbers an operator can confirm on a captured packet without
    any key material, which makes them useful evidence during review.
    """
    kem = ML_KEM[name]

    expected = FIPS_203_PARAMETERS[name]

    ek, dk = kem.keygen()
    shared_secret, ciphertext = kem.encaps(ek)

    assert len(ek) == expected["ek_bytes"]
    assert len(dk) == expected["dk_bytes"]
    assert len(ciphertext) == expected["ct_bytes"]
    assert len(shared_secret) == expected["ss_bytes"]


@pytest.mark.parametrize("name", PARAMETER_SETS)
def test_round_trip_agrees_on_the_shared_secret(name):
    """Algorithms 19-21: the property the protocol is built on."""
    kem = ML_KEM[name]

    ek, dk = kem.keygen()
    shared_secret, ciphertext = kem.encaps(ek)

    assert kem.decaps(dk, ciphertext) == shared_secret


def test_encapsulation_is_randomised(keypair_768):
    """Two encapsulations to the same key must not repeat.

    A deterministic KEM would let an eavesdropper recognise repeated sessions,
    and a constant shared secret would make the whole exchange decorative. This
    catches a stubbed or seeded implementation left in place by accident.
    """
    kem = ML_KEM["ML-KEM-768"]

    ek, _ = keypair_768

    first_secret, first_ciphertext = kem.encaps(ek)
    second_secret, second_ciphertext = kem.encaps(ek)

    assert first_ciphertext != second_ciphertext
    assert first_secret != second_secret


def test_shared_secrets_are_not_degenerate(keypair_768):
    """A shared secret of zero bytes, or a repeated one, is a broken build."""
    kem = ML_KEM["ML-KEM-768"]

    ek, _ = keypair_768

    secrets = {kem.encaps(ek)[0] for _ in range(16)}

    assert len(secrets) == 16, "shared secrets repeated across encapsulations"

    for secret in secrets:
        assert secret != bytes(32)
        assert len(set(secret)) > 1, "shared secret has no variation"


def test_tampered_ciphertext_is_implicitly_rejected(keypair_768):
    """Section 7.3: tampering yields a wrong key, not an error.

    This is the property people most often get backwards. Raising on a bad
    ciphertext hands an attacker a decryption oracle, so FIPS 203 returns a
    pseudorandom key derived from the ciphertext and a secret the attacker does
    not hold. The caller finds out later, when the session key does not work.
    """
    kem = ML_KEM["ML-KEM-768"]

    ek, dk = keypair_768

    shared_secret, ciphertext = kem.encaps(ek)

    tampered = bytearray(ciphertext)
    tampered[0] ^= 0x01

    rejection_key = kem.decaps(dk, bytes(tampered))

    assert len(rejection_key) == 32, "implicit rejection still returns a key"
    assert rejection_key != shared_secret


def test_implicit_rejection_is_deterministic_for_a_given_ciphertext(keypair_768):
    """The rejection key must depend only on (z, c), not on fresh randomness.

    A rejection key that changed per call would leak, through timing or through
    a retry, that rejection happened at all.
    """
    kem = ML_KEM["ML-KEM-768"]

    _, dk = keypair_768

    tampered = bytes(1088)

    assert kem.decaps(dk, tampered) == kem.decaps(dk, tampered)


def test_wrong_decapsulation_key_does_not_recover_the_secret():
    """An unrelated key pair must not decapsulate someone else's ciphertext."""
    kem = ML_KEM["ML-KEM-768"]

    ek, _ = kem.keygen()
    _, other_dk = kem.keygen()

    shared_secret, ciphertext = kem.encaps(ek)

    assert kem.decaps(other_dk, ciphertext) != shared_secret


@pytest.mark.parametrize("name", PARAMETER_SETS)
def test_truncated_inputs_are_refused(name):
    """Sections 7.2 and 7.3: length checks come before any use of the input."""
    kem = ML_KEM[name]

    ek, dk = kem.keygen()
    _, ciphertext = kem.encaps(ek)

    with pytest.raises(ValueError):
        kem.encaps(ek[:-1])

    with pytest.raises(ValueError):
        kem.decaps(dk, ciphertext[:-1])

    with pytest.raises(ValueError):
        kem.decaps(dk[:-1], ciphertext)


def test_parameter_sets_cannot_be_confused():
    """Material from one parameter set must not be accepted by another.

    Without this, a peer could negotiate ML-KEM-1024 and be served ML-KEM-512
    material. The length checks make the downgrade fail loudly.
    """
    weak = ML_KEM["ML-KEM-512"]
    strong = ML_KEM["ML-KEM-1024"]

    weak_ek, weak_dk = weak.keygen()
    _, weak_ciphertext = weak.encaps(weak_ek)

    strong_ek, strong_dk = strong.keygen()
    _, strong_ciphertext = strong.encaps(strong_ek)

    with pytest.raises(ValueError):
        strong.encaps(weak_ek)

    with pytest.raises(ValueError):
        weak.encaps(strong_ek)

    with pytest.raises(ValueError):
        strong.decaps(strong_dk, weak_ciphertext)

    with pytest.raises(ValueError):
        weak.decaps(weak_dk, strong_ciphertext)


def test_deployment_parameter_set_meets_the_intended_security_category():
    """ML-KEM-768 is the set the project plans to deploy; record why.

    NIST category 3 is the common floor for new deployments. If the group
    chooses another set, change this test and the reasoning in
    docs/testing/ml-kem-verification.md together.
    """
    from support import MINIMUM_SECURITY_CATEGORY

    chosen = FIPS_203_PARAMETERS["ML-KEM-768"]

    assert chosen["security_category"] >= MINIMUM_SECURITY_CATEGORY
