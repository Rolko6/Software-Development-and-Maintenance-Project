"""Source checks that keep classical-only key agreement off the protected path.

Shor's algorithm breaks RSA, finite-field Diffie-Hellman, and every elliptic
curve variant. Adding ML-KEM does not help if a classical key exchange is still
what actually establishes the session key, and that is an easy state to reach
by accident: a library defaults to X25519, the ML-KEM call is left in place,
and every functional test still passes.

These are heuristics over source text, not proofs. They catch the obvious
regression; they cannot see what a dependency does internally. They run today,
before any integration exists, and pass because no key agreement is present at
all — which is itself accurate, and is recorded in the README as a limitation.
"""

import os
import re

import pytest

from support import REPO_ROOT


SERVICE_DIRECTORIES = ("gateway", "cloud", "device")

SKIP_DIRECTORIES = {".venv", ".git", ".trash", "__pycache__", ".pytest_cache", "tests"}

# Public-key primitives that a cryptographically relevant quantum computer
# breaks. Matching a name is not proof of a weakness: signatures and key
# agreement have different consequences, and a hybrid design legitimately uses
# both. The rule applied below is that ML-KEM must be present alongside.
QUANTUM_VULNERABLE = (
    r"\brsa\b",
    r"\bx25519\b",
    r"\bx448\b",
    r"\becdh\b",
    r"\becdsa\b",
    r"\bed25519\b",
    r"\bdiffie",
    r"asymmetric\.dh\b",
)

POST_QUANTUM = (r"ml[_\-]?kem", r"\bkyber\b", r"\bml[_\-]?dsa\b", r"dilithium")

ML_KEM_LIBRARIES = ("kyber-py", "liboqs", "oqs", "pqcrypto", "quantcrypt")


def service_sources():
    for directory in SERVICE_DIRECTORIES:
        root = os.path.join(REPO_ROOT, directory)

        if not os.path.isdir(root):
            continue

        for current, subdirectories, filenames in os.walk(root):
            subdirectories[:] = [d for d in subdirectories if d not in SKIP_DIRECTORIES]

            for filename in filenames:
                if filename.endswith(".py"):
                    yield os.path.join(current, filename)


def matches(patterns, text):
    return sorted({p for p in patterns if re.search(p, text, re.IGNORECASE)})


def test_service_sources_are_discoverable():
    """Guard the scan itself: a walk that finds nothing would pass silently."""
    found = list(service_sources())

    assert found, f"no service sources found under {SERVICE_DIRECTORIES}"


@pytest.mark.parametrize(
    "path",
    sorted(service_sources()),
    ids=lambda p: os.path.relpath(p, REPO_ROOT),
)
def test_classical_key_agreement_is_never_used_on_its_own(path):
    """Classical public-key use is allowed only alongside ML-KEM.

    A hybrid exchange, where the session key depends on both a classical and a
    post-quantum secret, is a reasonable migration design and passes this
    check. A file that reaches for X25519 or RSA with no ML-KEM anywhere in it
    is the failure being guarded against.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read()

    classical = matches(QUANTUM_VULNERABLE, source)

    if not classical:
        return

    assert matches(POST_QUANTUM, source), (
        f"{os.path.relpath(path, REPO_ROOT)} uses {classical} with no ML-KEM "
        "in the same module. Either pair it with a post-quantum exchange or "
        "move it off the protected path."
    )


def test_ml_kem_is_pinned_wherever_the_gateway_imports_it():
    """The container must ship the library the tests exercise.

    The suite runs against the shared .venv while the services run in their own
    images. An ML-KEM module that imports a library missing from
    gateway/requirements.txt passes locally and fails in Compose.
    """
    kem_module = os.path.join(REPO_ROOT, "gateway", "app", "kem.py")

    if not os.path.exists(kem_module):
        return

    with open(os.path.join(REPO_ROOT, "gateway", "requirements.txt")) as handle:
        requirements = handle.read().lower()

    assert any(library in requirements for library in ML_KEM_LIBRARIES), (
        "gateway/app/kem.py exists but gateway/requirements.txt pins no ML-KEM "
        f"library (looked for {list(ML_KEM_LIBRARIES)})"
    )

    assert "==" in requirements, "pin the ML-KEM library to an exact version"
