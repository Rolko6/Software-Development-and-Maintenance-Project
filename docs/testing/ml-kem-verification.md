# Verifying ML-KEM: what the tests establish, and what they cannot

Recorded: 2026-09-15. Covers `tests/crypto/` and `tests/protected_path/`.
Evidence for every claim below, including the mutation checks that show the
suite fails for the right reasons:
[validation record](../validation/2026-09-15-ml-kem-tests.md).

## The question these tests answer

"Is it really post-quantum?" cannot be answered by running code.

Quantum resistance is not a behaviour that a program exhibits or fails to
exhibit. It is a claim about a mathematical problem: ML-KEM's security reduces
to the Module Learning With Errors problem, for which no efficient quantum
algorithm is known, whereas RSA and elliptic-curve key agreement reduce to
factoring and discrete logarithms, which Shor's algorithm solves on a
sufficiently large quantum computer. That distinction was established by
cryptanalysis over years of public review, and it is what NIST standardised in
FIPS 203. No assertion in this repository adds to it or subtracts from it.

A test suite also cannot demonstrate the failure case. Nobody has a quantum
computer that breaks RSA-2048, so a test that "attacks" our key exchange would
prove nothing either way, and a passing one would be actively misleading.

What the suite can do is check the three things that stand between the
standard's security claim and this project's deployment:

| # | Claim | Where it is checked | Evidence |
| --- | --- | --- | --- |
| 1 | The code computes the algorithm NIST analysed | `tests/crypto/test_ml_kem_acvp_kat.py` | NIST's own published inputs and expected outputs |
| 2 | It behaves as FIPS 203 requires on inputs NIST did not publish | `tests/crypto/test_ml_kem_properties.py` | Round-trip, implicit rejection, input validation, parameter confusion |
| 3 | The protected link actually uses it | `tests/protected_path/` | Captured outbound bytes; source scan for classical key agreement |

If all three hold, the honest statement is: *this link uses ML-KEM-768 as
standardised in FIPS 203, and NIST's post-quantum security claim applies to
that algorithm.* The claim is inherited, not demonstrated. That is the strongest
claim anyone can make about a deployment, including a commercial one.

## 1. Conformance: known-answer tests

This is the part that does the work.

The expected values come from NIST's ACVP vector files and are stored verbatim
in `tests/vectors/ml_kem_acvp.json`, with the upstream repository, commit, and
file paths recorded in its `_provenance` block. `tests/vectors/extract_acvp_subset.py`
regenerates the subset from the upstream files.

Nothing in that file was computed locally, and this matters more than it looks.
An implementation checked against values it produced itself will agree with
itself perfectly while computing the wrong function. A wrong function may still
round-trip: encapsulation and decapsulation would agree on a shared secret, the
services would interoperate, every functional test would pass, and the result
would be a home-made scheme with no analysis behind it.

Key generation, encapsulation, and decapsulation are deterministic once their
seeds are fixed, so the tests drive kyber-py's seeded internal functions
(`_keygen_internal`, `_encaps_internal`) with the `d`, `z`, and `m` values ACVP
supplies. Those are private functions; `requirements-dev.txt` pins
`kyber-py==1.2.0` for that reason, and
`tests/crypto/test_ml_kem_implementation_assurance.py` fails if the pinned
version changes.

Coverage: all three approved parameter sets (ML-KEM-512, ML-KEM-768,
ML-KEM-1024), across key generation, encapsulation, decapsulation including
NIST's modified-ciphertext cases, and both key-validation functions.

## 2. Required behaviour

Beyond the fixed vectors, `test_ml_kem_properties.py` checks the properties a
caller relies on:

- **Lattice parameters and sizes** match FIPS 203 Table 2 and Section 8,
  asserted against values written out from the standard rather than read back
  from the library. A build that silently selected ML-KEM-512 while calling
  itself ML-KEM-768 would pass every round-trip test; it fails this one.
- **Implicit rejection.** A tampered ciphertext does not raise. FIPS 203 returns
  a pseudorandom key derived from the ciphertext and a secret value held only by
  the recipient, because reporting the failure would hand an attacker a
  decryption oracle. Tests that expect an exception here are testing the wrong
  behaviour, and this is the most common mistake in ML-KEM test suites.
- **Randomised encapsulation.** Two encapsulations to the same key must differ,
  which catches a stub or a seeded generator left in place.
- **Input validation.** Truncated keys and ciphertexts are refused, and material
  from one parameter set is refused by another, so a downgrade attempt fails
  loudly rather than proceeding at lower strength.

## 3. The protected path

Conformance in a library that nothing calls protects nothing.
`tests/protected_path/` addresses the threat ML-KEM exists to counter: an
attacker records traffic today and decrypts it once a quantum computer exists —
"harvest now, decrypt later". For sensor telemetry the recorded data may still
matter years later, which is why migration is worth doing before the threat is
real.

`test_protected_path_contract.py` takes the recorder's view. It captures the
bytes the gateway sends to the cloud and asserts that the temperature, the
device identifier, and even the field names are absent, and that ML-KEM
material of the right size is present. Absence of plaintext alone is not enough:
a base64 wrapper or a classical cipher would pass that check.

Two further tests matter more than they appear to:

- **The kill switch.** `test_the_ml_kem_secret_changes_the_session_key` varies
  only the ML-KEM secret and requires the derived session key to change. In a
  hybrid design it is easy to feed the ML-KEM secret into a key derivation that
  ignores it. The result interoperates, round-trips, and provides no
  post-quantum protection whatsoever. Nothing except a test like this notices.
- **Failing closed.** If key establishment fails, the gateway must send nothing
  rather than fall back to plaintext, and the failure must reach a counter so it
  is observable.

`test_no_quantum_vulnerable_key_agreement.py` scans the service sources for
RSA, Diffie-Hellman, and elliptic-curve primitives. A hybrid exchange that
combines a classical and a post-quantum secret is a reasonable migration design
and passes; classical key agreement with no ML-KEM in the same module does not.
This is a text heuristic over first-party source. It cannot see inside a
dependency.

**These tests skip today.** `gateway/app/kem.py` does not exist; ML-KEM
integration is work package 3 of the [project plan](../project-plan.md). The
skip is conditional on the module under test being absent, not a suppressed
failure: no test here is marked `xfail`, and the conformance layer never skips.
The module docstring states the interface the tests assume. That interface is a
proposal from the test suite, not a decision the group has taken; work package 3
may rename any of it, provided the tests are updated alongside the
implementation rather than deleted.

## Residual risk: what no test here covers

The project's [shared agent instructions](../../AGENTS.md) require residual
risks to be recorded for cryptographic work. These are the ones that matter.

**The implementation is not suitable for deployment.** kyber-py is an
educational library. Its own documentation states that under no circumstances
should it be used for cryptographic applications, and that it is not constant
time and offers no resistance to side channel attack. It is a sound choice for a
course prototype and for conformance testing, and an unsound one for anything
carrying real data. A correct algorithm in a leaky implementation gives an
attacker a practical break today, with no quantum computer needed — which would
make the migration worse than useless. Moving to a hardened implementation
(liboqs, or a validated provider through the `cryptography` package) is a
prerequisite for any claim beyond "prototype".

**Timing is not measured.** A side channel test needs dedicated hardware and
statistical methodology; a shared CI runner produces noise. Pure-Python ML-KEM
would fail such a measurement regardless. `test_side_channel_risk_is_recorded_rather_than_tested`
exists to keep this paragraph from being forgotten, not to substitute for the
measurement.

**There is no CAVP validation certificate.** Conformance against public ACVP
vectors is strong evidence and is not the same as a NIST-issued validation. If
the report claims validation, it needs a certificate number.

**A KEM is not a protocol.** ML-KEM establishes a shared secret with whoever
holds the encapsulation key. It says nothing about whether that party is the
real cloud service. Without authenticated key trust — pinned keys, certificates,
or a trusted distribution step — an active attacker can run their own ML-KEM
exchange with the gateway and read everything. Key lifetime, rotation, and
replay protection are likewise outside what these tests check and must be
designed in work package 3.

**Only one link is in scope.** The device-to-gateway hop stays plain HTTP, as
recorded in the README's known limitations. The simulated legacy device is the
reason, and that is a legitimate scoping decision, but it means the system as a
whole is not protected end to end and should not be described as such.

**Key material in these tests is public.** Every key in
`tests/vectors/ml_kem_acvp.json` is published by NIST. None of it may be reused
outside the test suite.

## Running the tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/crypto tests/protected_path
```

The ML-KEM suite needs no running services and no network access. `tests/integration/`
additionally requires the Docker Compose stack; run it separately after
`docker compose up --build -d`.

To refresh the vectors from upstream, follow the instructions at the top of
`tests/vectors/extract_acvp_subset.py` and record the new commit in the
`_provenance` block.

## References

- [NIST FIPS 203: Module-Lattice-Based Key-Encapsulation Mechanism Standard](https://csrc.nist.gov/pubs/fips/203/final)
- [NIST ACVP-Server test vectors](https://github.com/usnistgov/ACVP-Server) — `gen-val/json-files/ML-KEM-keyGen-FIPS203` and `ML-KEM-encapDecap-FIPS203`
- [kyber-py](https://github.com/GiacomoPope/kyber-py) — the implementation under test, and its disclaimer
- [Project plan](../project-plan.md) — work package 3, ML-KEM design and integration
