"""Helpers shared by the ML-KEM tests.

Kept out of `conftest.py` because the known-answer tests need the vectors at
collection time, and `pytest.mark.parametrize` cannot consume a fixture.
`conftest.py` puts this directory on `sys.path`.
"""

import json
import os


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

REPO_ROOT = os.path.dirname(TESTS_DIR)

VECTOR_FILE = os.path.join(TESTS_DIR, "vectors", "ml_kem_acvp.json")

GATEWAY_ROOT = os.path.join(REPO_ROOT, "gateway")

# FIPS 203 Table 2 and Section 8: the sizes and lattice parameters that define
# each approved parameter set, together with the NIST security category. These
# are written out here rather than read from the library, so that a test can
# compare the library against the standard instead of against itself.
FIPS_203_PARAMETERS = {
    "ML-KEM-512": {
        "k": 2,
        "eta_1": 3,
        "eta_2": 2,
        "du": 10,
        "dv": 4,
        "ek_bytes": 800,
        "dk_bytes": 1632,
        "ct_bytes": 768,
        "ss_bytes": 32,
        "oid": (2, 16, 840, 1, 101, 3, 4, 4, 1),
        "security_category": 1,
    },
    "ML-KEM-768": {
        "k": 3,
        "eta_1": 2,
        "eta_2": 2,
        "du": 10,
        "dv": 4,
        "ek_bytes": 1184,
        "dk_bytes": 2400,
        "ct_bytes": 1088,
        "ss_bytes": 32,
        "oid": (2, 16, 840, 1, 101, 3, 4, 4, 2),
        "security_category": 3,
    },
    "ML-KEM-1024": {
        "k": 4,
        "eta_1": 2,
        "eta_2": 2,
        "du": 11,
        "dv": 5,
        "ek_bytes": 1568,
        "dk_bytes": 3168,
        "ct_bytes": 1568,
        "ss_bytes": 32,
        "oid": (2, 16, 840, 1, 101, 3, 4, 4, 3),
        "security_category": 5,
    },
}

# FIPS 203 Section 8: the ring is Z_q[X]/(X^n + 1) with these fixed values for
# every parameter set. A different q or n is a different problem instance, not
# ML-KEM.
RING_MODULUS = 3329

RING_DEGREE = 256

# The parameter set the project intends to deploy on the gateway-cloud link.
# Category 3 is the usual choice for new deployments; see
# docs/testing/ml-kem-verification.md.
MINIMUM_SECURITY_CATEGORY = 3


def load_vectors():
    """Read the checked-in ACVP subset."""
    with open(VECTOR_FILE) as handle:
        return json.load(handle)


def implementations():
    """Map ACVP parameter-set names onto kyber-py objects."""
    from kyber_py.ml_kem import ML_KEM_512, ML_KEM_768, ML_KEM_1024

    return {
        "ML-KEM-512": ML_KEM_512,
        "ML-KEM-768": ML_KEM_768,
        "ML-KEM-1024": ML_KEM_1024,
    }


def cases(document, section, parameter_set=None):
    """Select vector cases, optionally narrowed to one parameter set."""
    selected = document[section]

    if parameter_set is not None:
        selected = [c for c in selected if c["parameterSet"] == parameter_set]

    return selected


def hex_equal(actual, expected):
    """Compare a bytes value against an ACVP hex string.

    The upstream vectors are uppercase hex. They are stored verbatim rather
    than normalised, so the comparison ignores case instead.
    """
    return actual.hex().lower() == expected.lower()


def case_id(case):
    """Readable pytest node id for a vector case."""
    reason = case.get("reason")
    suffix = "-" + reason.replace(" ", "_") if reason else ""
    return f"{case['parameterSet']}-tc{case['tcId']}{suffix}"
