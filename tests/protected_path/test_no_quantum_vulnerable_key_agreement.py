"""Source checks that keep classical-only key agreement off the protected path.

Shor's algorithm breaks RSA, finite-field Diffie-Hellman, and every elliptic
curve variant. Adding ML-KEM does not help if a classical key exchange is still
what actually establishes the session key, and that is an easy state to reach
by accident: a library defaults to X25519, the ML-KEM call is left in place,
and every functional test still passes.

These are heuristics over source text, not proofs. They catch the obvious
regression; they cannot see what a dependency does internally. The services
now establish keys with ML-KEM-768 from `cryptography` (gateway/app/crypto,
cloud/app/crypto; ADR 0002) and use no classical key agreement. The pin check
at the end runs against those modules.
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

# `cryptography` is the library the services actually use: its native
# `cryptography.hazmat.primitives.asymmetric.mlkem`, pinned as
# cryptography==50.0.1 in gateway/ and cloud/requirements.txt. See
# docs/decisions/0002-ml-kem-key-establishment.md, "Library selection".
ML_KEM_LIBRARIES = ("cryptography", "kyber-py", "liboqs", "oqs", "pqcrypto", "quantcrypt")

# How a service module shows that it uses each allowlisted library for ML-KEM.
# `cryptography` counts only when its mlkem module is imported: the services
# also use it for AES-GCM and HKDF, which say nothing about ML-KEM.
ML_KEM_IMPORTS = {
    "cryptography": (
        r"from\s+cryptography\.hazmat\.primitives\.asymmetric\s+import\s+[^\n]*\bmlkem\b"
        r"|cryptography\.hazmat\.primitives\.asymmetric\.mlkem\b"
    ),
    "kyber-py": r"^\s*(from|import)\s+kyber_py\b",
    "liboqs": r"^\s*(from|import)\s+oqs\b",
    "oqs": r"^\s*(from|import)\s+oqs\b",
    "pqcrypto": r"^\s*(from|import)\s+pqcrypto\b",
    "quantcrypt": r"^\s*(from|import)\s+quantcrypt\b",
}

# The service modules that do the ML-KEM work (ADR 0002).
ML_KEM_MODULES = (
    os.path.join("gateway", "app", "crypto", "client.py"),
    os.path.join("cloud", "app", "crypto", "keys.py"),
)

ML_KEM_SERVICES = ("gateway", "cloud")


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


def ml_kem_libraries_imported_by(service):
    """Allowlisted libraries whose ML-KEM API the service's sources import,
    mapped to the importing files."""
    found = {}
    prefix = os.path.join(REPO_ROOT, service) + os.sep

    for path in service_sources():
        if not path.startswith(prefix):
            continue

        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()

        for library, pattern in ML_KEM_IMPORTS.items():
            if re.search(pattern, source, re.MULTILINE):
                found.setdefault(library, []).append(os.path.relpath(path, REPO_ROOT))

    return found


def exact_pin(requirements, library):
    """The exact `==` version the requirements text pins for `library`, or None."""
    pattern = rf"^\s*{re.escape(library)}(\[[^\]]*\])?\s*==\s*([^\s;#]+)"
    match = re.search(pattern, requirements, re.IGNORECASE | re.MULTILINE)
    return match.group(2) if match else None


@pytest.mark.parametrize("module", ML_KEM_MODULES)
def test_ml_kem_modules_import_the_allowlisted_library(module):
    """The implementation ADR 0002 describes is really there.

    This keeps the pin test below from passing vacuously: if these modules
    stopped importing an allowlisted ML-KEM library, the pin test would have
    nothing to check.
    """
    with open(os.path.join(REPO_ROOT, module), encoding="utf-8") as handle:
        source = handle.read()

    assert re.search(ML_KEM_IMPORTS["cryptography"], source, re.MULTILINE), (
        f"{module} no longer imports cryptography.hazmat.primitives.asymmetric.mlkem"
    )


@pytest.mark.parametrize("service", ML_KEM_SERVICES)
def test_ml_kem_is_pinned_wherever_a_service_imports_it(service):
    """The container must ship the library the tests exercise.

    The suite runs against the shared .venv while the services run in their own
    images. An ML-KEM module that imports a library missing from the service's
    requirements.txt passes locally and fails in Compose. Every allowlisted
    ML-KEM library a service imports must be pinned to an exact version in that
    service's requirements.txt.
    """
    imported = ml_kem_libraries_imported_by(service)

    assert imported, (
        f"{service}/ imports no allowlisted ML-KEM library "
        f"(looked for {list(ML_KEM_LIBRARIES)}); ADR 0002 says it uses "
        "cryptography's mlkem"
    )

    with open(os.path.join(REPO_ROOT, service, "requirements.txt"), encoding="utf-8") as handle:
        requirements = handle.read()

    for library, importers in sorted(imported.items()):
        assert library in ML_KEM_LIBRARIES
        assert exact_pin(requirements, library), (
            f"{', '.join(importers)} import(s) {library} for ML-KEM, but "
            f"{service}/requirements.txt does not pin it with =="
        )
