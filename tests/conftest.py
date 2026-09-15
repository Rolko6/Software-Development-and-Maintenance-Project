"""Shared configuration for the ML-KEM verification suite.

Two layers live under `tests/`:

* `tests/crypto/` checks the ML-KEM implementation against NIST FIPS 203.
  These tests must pass today. They never skip.
* `tests/integration/` checks that the gateway's protected path actually uses
  ML-KEM. That module does not exist yet (project plan work package 3), so
  those tests skip with an explicit reason until it does.

See docs/testing/ml-kem-verification.md for what each layer can and cannot
establish, and for the residual risks no test here covers.
"""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

from support import implementations, load_vectors  # noqa: E402

# The gateway's import root is deliberately *not* added here. Each service
# imports itself as the top-level package `app`, so putting one of them on
# sys.path for the whole session would shadow the others. The one module that
# needs the gateway adds it itself; see
# tests/integration/test_protected_path_contract.py.


@pytest.fixture(scope="session")
def acvp():
    """The checked-in subset of NIST ACVP test vectors.

    Values are copied verbatim from the upstream NIST files; see `_provenance`
    in the JSON and tests/vectors/extract_acvp_subset.py.
    """
    return load_vectors()


@pytest.fixture(scope="session")
def parameter_sets():
    """Map the ACVP parameter-set names onto kyber-py objects."""
    return implementations()
