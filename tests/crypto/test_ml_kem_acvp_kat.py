"""Known-answer tests against NIST's published ML-KEM vectors.

This is the only test file in the repository that connects the code to the
security claim behind ML-KEM. FIPS 203 analyses one specific algorithm; NIST's
analysis applies to our deployment only if our code computes that algorithm and
nothing else. A known-answer test is how that is shown: NIST supplies the
inputs and the expected outputs, and the implementation has to reproduce them
byte for byte.

The expected values come from the NIST ACVP vector files and were never
computed locally. An implementation checked only against itself would agree
with itself while being wrong.

Reference: NIST FIPS 203, Module-Lattice-Based Key-Encapsulation Mechanism
Standard, https://csrc.nist.gov/pubs/fips/203/final
"""

import pytest

from support import case_id, cases, hex_equal, implementations, load_vectors


pytestmark = pytest.mark.kat

VECTORS = load_vectors()

ML_KEM = implementations()


def test_vectors_declare_their_origin():
    """A vector file without provenance is an unverifiable claim."""
    provenance = VECTORS["_provenance"]

    assert provenance["repository"] == "https://github.com/usnistgov/ACVP-Server"
    assert provenance["standard"] == "NIST FIPS 203 (ML-KEM)"
    assert len(provenance["commit"]) == 40, "pin the upstream commit, not a branch"
    assert provenance["files"], "record which upstream files the subset came from"


@pytest.mark.parametrize("case", cases(VECTORS, "keyGen"), ids=case_id)
def test_key_generation_matches_nist_vectors(case):
    """Algorithm 16: seeds (d, z) must expand to NIST's exact key pair.

    Key generation is deterministic given its two seeds. `keygen()` draws them
    from the system RNG, so the test drives the internal seeded form, which is
    what ACVP specifies.
    """
    kem = ML_KEM[case["parameterSet"]]

    ek, dk = kem._keygen_internal(bytes.fromhex(case["d"]), bytes.fromhex(case["z"]))

    assert hex_equal(ek, case["ek"]), "encapsulation key differs from FIPS 203"
    assert hex_equal(dk, case["dk"]), "decapsulation key differs from FIPS 203"


@pytest.mark.parametrize("case", cases(VECTORS, "encap"), ids=case_id)
def test_encapsulation_matches_nist_vectors(case):
    """Algorithm 17: message m and key ek must produce NIST's exact (K, c)."""
    kem = ML_KEM[case["parameterSet"]]

    shared_secret, ciphertext = kem._encaps_internal(
        bytes.fromhex(case["ek"]),
        bytes.fromhex(case["m"]),
    )

    assert hex_equal(ciphertext, case["c"]), "ciphertext differs from FIPS 203"
    assert hex_equal(shared_secret, case["k"]), "shared secret differs from FIPS 203"


@pytest.mark.parametrize("case", cases(VECTORS, "decap"), ids=case_id)
def test_decapsulation_matches_nist_vectors(case):
    """Algorithm 18, including the implicit-rejection branch.

    NIST's `modified ciphertext` cases are the interesting ones. FIPS 203 does
    not report a tampered ciphertext as an error; it derives an unrelated key
    from the ciphertext and the private z value, so an attacker learns nothing
    from the response. The expected value for those cases is that rejection
    key, and it has to match exactly.
    """
    kem = ML_KEM[case["parameterSet"]]

    shared_secret = kem.decaps(bytes.fromhex(case["dk"]), bytes.fromhex(case["c"]))

    assert hex_equal(shared_secret, case["k"]), (
        f"decapsulation differs from FIPS 203 for a {case['reason']!r} case"
    )


@pytest.mark.parametrize(
    "case", cases(VECTORS, "encapsulationKeyCheck"), ids=case_id
)
def test_encapsulation_key_validation_matches_nist_vectors(case):
    """Section 7.2: malformed encapsulation keys must be refused.

    The negative cases carry coefficients outside the ring modulus. Accepting
    them would mean encapsulating against something that is not a valid ML-KEM
    key, so the type and modulus checks are part of the algorithm, not an
    optional hardening step.
    """
    kem = ML_KEM[case["parameterSet"]]

    if case["testPassed"]:
        shared_secret, ciphertext = kem.encaps(bytes.fromhex(case["ek"]))

        assert len(shared_secret) == 32
        assert len(ciphertext) == 32 * (kem.du * kem.k + kem.dv)
        return

    with pytest.raises(ValueError):
        kem.encaps(bytes.fromhex(case["ek"]))


@pytest.mark.parametrize(
    "case", cases(VECTORS, "decapsulationKeyCheck"), ids=case_id
)
def test_decapsulation_key_validation_matches_nist_vectors(case):
    """Section 7.3: malformed decapsulation keys must be refused.

    The negative cases hold a corrupted hash of the embedded public key. The
    hash check catches a decapsulation key whose public and private halves do
    not belong together.
    """
    kem = ML_KEM[case["parameterSet"]]

    dk = bytes.fromhex(case["dk"])

    ek = dk[384 * kem.k : 768 * kem.k + 32]

    _, ciphertext = kem.encaps(ek)

    if case["testPassed"]:
        assert len(kem.decaps(dk, ciphertext)) == 32
        return

    with pytest.raises(ValueError):
        kem.decaps(dk, ciphertext)


def test_every_approved_parameter_set_is_covered():
    """A suite that only exercises one parameter set proves less than it looks.

    Covering all three catches a build that silently selects different lattice
    parameters from the ones the deployment believes it is using.
    """
    for section in ("keyGen", "encap", "decap"):
        covered = {case["parameterSet"] for case in VECTORS[section]}

        assert covered == {"ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"}, (
            f"{section} vectors cover only {sorted(covered)}"
        )
