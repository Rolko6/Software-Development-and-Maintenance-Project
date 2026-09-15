# Validation record — ML-KEM verification tests, 2026-09-15

Covers the suite added under `tests/crypto/` and `tests/protected_path/`, its
vector fixture, and [docs/testing/ml-kem-verification.md](../testing/ml-kem-verification.md).
No application code was changed for this work.

## Executed checks

Runner: `.venv/bin/python -m pytest` (pytest 9.1.1, Python 3.13.12, macOS 24.6.0).
The service containers use Python 3.12; this suite was not run inside them.

```
$ .venv/bin/python -m pytest \
    tests/crypto/test_ml_kem_acvp_kat.py \
    tests/crypto/test_ml_kem_properties.py \
    tests/crypto/test_ml_kem_implementation_assurance.py \
    tests/protected_path

SKIPPED [1] tests/protected_path/test_protected_path_contract.py:57: gateway/app/kem.py
  does not exist yet: ML-KEM integration is project plan work package 3.
  These tests define what it has to satisfy.
======================== 90 passed, 1 skipped in 0.38s =========================

$ .venv/bin/python -m pytest tests/crypto/test_ml_kem_acvp_kat.py -m kat
======================== 35 passed in 0.16s ====================================
```

The files are named explicitly because parallel work was adding modules to
`tests/crypto/` during this session. The stable figures are 35 known-answer
tests and 23 behaviour and assurance tests; the remainder is the
classical-key-agreement scan, which is parametrised over every `.py` file under
`gateway/`, `cloud/`, and `device/` and therefore grows as the services do.

`git diff --check` — clean.

## Mutation checks

A suite that passes proves nothing until it is shown to fail for the right
reason. Two deliberate defects were injected through a pytest plugin loaded
from a scratch directory; no repository file was modified.

| Injected defect | Result |
| --- | --- |
| `ML_KEM_768.eta_1` set to 3 (FIPS 203 Section 8 specifies 2) | 6 failed, 52 passed — caught by the ACVP known-answer tests and by `test_lattice_parameters_match_the_standard` |
| `select_bytes` replaced so decapsulation always returns the real key, removing implicit rejection | 7 failed, 51 passed — caught by the ACVP modified-ciphertext vectors and by `test_tampered_ciphertext_is_implicitly_rejected` |

Baseline for comparison: `tests/crypto` alone, 58 passed.

## Test vector provenance

`tests/vectors/ml_kem_acvp.json` holds 33 cases extracted verbatim from NIST's
public ACVP vector files:

- Repository: `https://github.com/usnistgov/ACVP-Server`
- Commit: `975de31eb83d87039ec88934fdc47d8c312b892d` (committed 2026-08-12)
- Files: `gen-val/json-files/ML-KEM-keyGen-FIPS203/internalProjection.json` and
  `gen-val/json-files/ML-KEM-encapDecap-FIPS203/internalProjection.json`
- Retrieved: 2026-09-15

Coverage: key generation, encapsulation, decapsulation (valid and modified
ciphertext), encapsulation-key validation, and decapsulation-key validation,
for ML-KEM-512, ML-KEM-768, and ML-KEM-1024.

No expected value was computed locally. `tests/vectors/extract_acvp_subset.py`
regenerates the subset from the upstream files.

## Source inspection

- `kyber-py` 1.2.0, read at `.venv/lib/python3.13/site-packages/kyber_py/ml_kem/ml_kem.py`.
  It implements the FIPS 203 type, modulus, and hash checks, and carries an
  explicit in-source warning that its constant-time selection is not
  guaranteed.
- Its distribution metadata states the library must not be used for
  cryptographic applications and is not constant time. Recorded as the leading
  residual risk in the verification document.

## Checks not run

- **Context7** has no entry for `kyber-py`; `resolve-library-id` returned
  unrelated libraries. The library's installed source and distribution metadata
  were read directly instead, together with NIST FIPS 203. Recorded per the
  documentation rule in [AGENTS.md](../../AGENTS.md).
- **`tests/protected_path/test_protected_path_contract.py`** did not execute.
  `gateway/app/kem.py` does not exist; the module skips by design and the skip
  reason names the work package.
- **Side-channel and timing behaviour** were not measured. See the residual
  risk section of the verification document.
- **The Docker Compose stack** was not started for this work, and the suite
  does not require it.
- **CAVP validation.** No certificate exists for this implementation; ACVP
  vector conformance is not a NIST validation.

## Claim supported by this record

The ML-KEM implementation available to the project computes the algorithm
standardised in FIPS 203, for all three parameter sets, matching NIST's
published vectors. Whether the gateway-to-cloud link uses it is untested,
because the integration does not exist yet.
