# Decision 0002: ML-KEM key establishment for the gateway-cloud link

- Date: 2026-09-15
- Status: implemented as new, additive files (`cloud/app/crypto/`,
  `gateway/app/crypto/`, `tests/crypto/`); not yet wired into
  `cloud/app/main.py` or `gateway/app/cloud_client.py` -- that integration is
  a separate, small patch (see "Integration steps for the main agent" at the
  end of [docs/security/ml-kem-integration.md](../security/ml-kem-integration.md)).
  Human review of the design and the library choice is not recorded.
- Origin: [project plan](../project-plan.md) work package 3, "Design and
  integrate ML-KEM". This agent's file ownership for the task does not
  include `docs/ai/**`, so no entry was added to
  [docs/ai/README.md](../ai/README.md)'s evidence log; the disposition below
  serves that purpose for this decision.

## Context

The device-gateway-cloud prototype currently sends every reading over plain
HTTP end to end. Work package 3 asks for the gateway-cloud leg to be
protected against a future quantum adversary, using an existing ML-KEM
(FIPS 203) implementation rather than a hand-rolled one, while the
device-gateway leg stays plain HTTP (legacy compatibility; documented as a
remaining exposure, not hidden). See
[docs/security/ml-kem-integration.md](../security/ml-kem-integration.md) for
the full design; this record is about the library and protocol-shape
choices and their reasons.

ML-KEM is a key-encapsulation mechanism: on its own it produces a shared
secret between two parties, nothing more. It does not encrypt application
data and does not authenticate either peer. Both of those had to be decided
separately (a KDF + AEAD for message protection; an optional pre-shared-key
MAC for peer authentication) -- see the design doc's "Message protection"
and "Peer/key trust" sections.

## Decision

Use `cryptography`'s native ML-KEM-768 implementation
(`cryptography.hazmat.primitives.asymmetric.mlkem.MLKEM768PrivateKey` /
`MLKEM768PublicKey`, OpenSSL-backed) as the KEM, and the same library's
`HKDF` (SHA-256) and `AESGCM` for message protection. One dependency
(`cryptography==50.0.1`, see `requirements-crypto.txt`) serves the KEM, the
KDF, and the AEAD in both services.

Protocol shape (full detail in the design doc):

1. The cloud holds a long-term ML-KEM-768 key pair (generated at startup,
   optionally persisted via `CLOUD_ML_KEM_KEY_PATH`) and publishes its
   encapsulation key at `GET /secure/handshake`.
2. The gateway encapsulates against that key, POSTs the ciphertext to
   `POST /secure/handshake`, and both sides derive an AES-256-GCM session
   key via `HKDF-SHA256(shared_secret, salt=client_nonce, info=...)`.
3. If `ML_KEM_PSK` is configured on both sides, the handshake carries a
   client-direction and a server-direction HMAC-SHA256 over the handshake
   transcript (domain-separated by label), giving mutual authentication
   from a pre-shared secret; if unset, the handshake is explicitly
   unauthenticated (documented, not hidden -- see "Peer/key trust").
4. Each reading is sent once, individually AEAD-protected, to
   `POST /secure/data`, under a session that is reused for multiple
   readings until it expires (default 300s) or a proactive rekey margin is
   reached, rather than re-running the KEM handshake per message.
5. The message nonce is the big-endian encoding of a per-session,
   strictly-increasing counter; the cloud enforces strict monotonicity per
   session, which is both the nonce-uniqueness argument and the replay
   defence.

### Why a session, not a fresh KEM handshake per message

A concurrently-written test module in this repository,
`tests/protected_path/test_protected_path_contract.py` (written by a
different agent; not owned by this task -- see "Relationship to the
parallel verification suite" below), proposes the alternative that "every
forwarded reading carries the ML-KEM ciphertext, so each message is
independently decryptable and a lost message costs nothing," and says
explicitly that a session-based design is "equally reasonable" and would
need that test rewritten to match. This decision takes that fork
deliberately: an ML-KEM-768 ciphertext is 1088 bytes and a fresh
encapsulation costs a fraction of a millisecond natively (see
"Verification" below) but still requires a full request/response round
trip before every reading can be sent, and requires the cloud to run
decapsulation on every message. Amortizing that over a session -- rekeyed
periodically and re-established transparently whenever the cloud has
forgotten it -- keeps the steady-state per-message cost to one AES-GCM
call (measured at ~0.0025 ms locally) instead of a full handshake
round-trip, which matters for a device polling every five seconds
indefinitely. The cost is the session-lifecycle machinery (expiry,
counter tracking, re-handshake-on-loss) documented in the design doc's
"Key lifecycle" and "Failure behaviour" sections.

## Library selection

Compared on FIPS 203 conformance, maturity, install friction in a slim
container, and explicit production-readiness posture.

| Candidate | FIPS 203 conformance | Maturity / audit posture | Install friction (Python 3.12 slim) | Production readiness |
| --- | --- | --- | --- | --- |
| **`cryptography`'s native `mlkem` (chosen)** | Implements ML-KEM-768/512/1024; OpenSSL-backed (this environment: OpenSSL 4.0.2, well past OpenSSL 3.5 where upstream ML-KEM landed). Verified locally (see below). | `cryptography` is the de facto standard Python crypto library, audited, widely deployed; ML-KEM support is a *very recent* addition (see caveat below). | None beyond the existing wheel: manylinux wheels ship a bundled/linked OpenSSL, no compiler or extra system packages needed in a slim image. | General-purpose library with a strong track record; the ML-KEM code path specifically is new and has had far less real-world exposure than, say, its RSA/EC code. |
| `kyber-py` 1.2.0 (pure Python) | Implements ML-KEM (FIPS 203) and Kyber round 3; passes NIST ACVP KATs (see the parallel `tests/crypto/test_ml_kem_acvp_kat.py` suite, which exercises this directly). Confirmed locally: correct round-trip, correct FIPS 203 sizes (ek 1184B, ct 1088B, ss 32B for ML-KEM-768), and the FIPS 203 implicit-rejection behaviour on tampered ciphertext. | Small, single-maintainer educational project. Depends on `pycryptodome` for its DRBG. | Pure Python plus one small dependency; trivially installs in any slim image, no native build step at all. | **Explicitly not production-safe.** Verbatim from its own PyPI metadata: "Under no circumstances should this be used for cryptographic applications. This is an educational resource and has not been designed to be secure against any form of side-channel attack." And: "This code is not constant time, or written to be performant... No cryptographic guarantees are made of this work." |
| `liboqs-python` / `pqcrypto` (native bindings to Open Quantum Safe's `liboqs`) | `liboqs` is the reference implementation most PQC research and pre-standardization deployments (e.g. early browser/TLS experiments) have used; tracks NIST's algorithms closely, including ML-KEM. Not installed or exercised in this environment -- assessment is from documented behaviour, not a hands-on check here. | The most battle-tested *native* PQC implementation available in Python as of this decision, with a large deployment history predating NIST's final standard. | High: `liboqs-python`/`pqcrypto` require compiling the `liboqs` C library (CMake, a C/C++ toolchain, and its own build time) unless a prebuilt wheel matching the target platform exists; this is a materially heavier and slower Docker build than a pure-Python or already-wheel-based dependency, and increases final image size. | `liboqs` documents itself as **not vetted for production use** ("NOT ready for production use" is the project's own long-standing framing) despite being more mature/battle-tested than `kyber-py` specifically because of its native, less-audited-per-release build surface and its own explicit disclaimer. |

Chosen: **`cryptography`'s native `mlkem`**. It is the only candidate that
is simultaneously FIPS-203-conformant (verified locally, not just
documented), has no extra install cost in a slim container (no compiler,
no second dependency), and carries the general-purpose maturity of
`cryptography` itself -- while `kyber-py`'s *own* documentation disallows
production use outright, and `liboqs`/`pqcrypto` trade a heavier, slower
container build for native-code maturity that `cryptography` already
offers via its own OpenSSL binding.

**Production-readiness caveat that applies to the chosen candidate too:**
ML-KEM support in `cryptography` is very new. This environment's
`cryptography==50.0.1` (confirmed via `pip show`) already includes it, but
this is a recent capability, not a years-proven one -- there has been far
less real-world exposure of this specific code path than of `cryptography`'s
long-established RSA/EC/AEAD primitives. Before this pin ships in a real
deployment (as opposed to a course project), confirm: (a) that the pinned
version is actually resolvable for the target container's Python 3.12 /
platform combination on PyPI, and (b) whether any later `cryptography`
advisory affects the `mlkem` module specifically. If native ML-KEM support
were ever unavailable for a target platform, `kyber-py` remains the
portable pure-Python fallback for *interoperability testing and protocol
development* -- not for production, per its own disclaimer above.

## Alternatives considered

- **Per-message KEM handshake, no session** (the design
  `tests/protected_path/test_protected_path_contract.py` was written
  against). Rejected for steady-state overhead reasons explained above;
  documented so the divergence from that test's assumption is deliberate,
  not accidental. That test file is owned by a different agent/work slice
  and is free to be rewritten against the session-based design, per its own
  docstring ("Decide that in work package 3, then change the test").
- **`liboqs-python` / `pqcrypto`**: rejected primarily for slim-container
  install friction (a native build step this project's Dockerfiles do not
  currently have, and would need to add: a C/C++ toolchain and CMake) for
  no conformance benefit over `cryptography`'s own OpenSSL-backed
  implementation, which is already a dependency-free (from the image's
  perspective) native binding.
- **`kyber-py`**: rejected for production use because its own
  documentation prohibits that use; kept as a reference-quality
  cross-check during development (its FIPS 203 sizes and round-trip
  behaviour were used to sanity-check the environment before choosing
  `cryptography`'s implementation) but is **not** in
  `requirements-crypto.txt` and does not ship in either service image.
- **A classical-only stopgap (e.g. X25519) "for now"**: rejected outright
  -- it does not address the stated threat (a future quantum adversary
  against today's recorded traffic) and the project plan specifically asks
  for ML-KEM.
- **Authentication out of scope entirely** (no PSK option at all): rejected
  in favor of making the PSK mechanism available but optional, since a
  bare KEM handshake over HTTP is honestly MITM-vulnerable and the task
  requires either a trust anchor or an explicit statement of that gap. Both
  are provided: `ML_KEM_PSK` for those who configure it, and an explicit,
  logged, documented statement of the residual risk for those who do not.
  See "Peer/key trust" in the design doc.

## Relationship to the parallel verification suite

While this work was in progress, a different, concurrently-running agent
populated `tests/conftest.py`, `tests/support.py`,
`tests/protected_path/**`, `tests/integration/**`, `tests/reliability/**`,
`tests/vectors/**`, three files inside `tests/crypto/`
(`test_ml_kem_acvp_kat.py`, `test_ml_kem_properties.py`,
`test_ml_kem_implementation_assurance.py`), and
`docs/testing/ml-kem-verification.md` -- despite this task's instructions
stating `tests/crypto/` is owned exclusively by this task. Those three
files were left in place (never delete another contributor's work) and
coexist without collision: `./.venv/bin/python -m pytest tests/crypto -q`
passes all 106 tests (48 from this task, 58 from the other agent) in one
run. Their `test_ml_kem_acvp_kat.py` independently confirms this decision's
FIPS 203 size/behaviour claims against NIST's own ACVP vectors (using
`kyber-py`, consistent with "reference-quality cross-check" above, not a
production claim). Their `tests/protected_path/test_protected_path_contract.py`
proposes the flat `gateway/app/kem.py` interface and per-message design
discussed above, and currently skips ("gateway/app/kem.py does not exist
yet") because this task's integration lives at `gateway/app/crypto/`
instead. This divergence, and the resulting need for someone to either
reconcile the two contracts or accept that the protected-path contract test
was a proposal rather than a decision, is called out again in the final
report handed back for this task -- it is not resolved by this record, only
recorded.

A second, more mechanical mismatch: `tests/protected_path/test_no_quantum_vulnerable_key_agreement.py`
checks that any module using a classical key-agreement primitive also
mentions a post-quantum one, via a hardcoded pattern list
`POST_QUANTUM = (r"ml[_\-]?kem", r"\bkyber\b", ...)` (this task's code
matches that pattern, since `wire.py` and `client.py` both say
`ML-KEM-768`/`ml_kem`) -- that check is unaffected. But the same file's
`test_ml_kem_is_pinned_wherever_the_gateway_imports_it` checks
`gateway/requirements.txt` for one of
`ML_KEM_LIBRARIES = ("kyber-py", "liboqs", "oqs", "pqcrypto", "quantcrypt")`
once `gateway/app/kem.py` exists -- **`cryptography` is not in that list**,
so if `gateway/app/kem.py` is ever created (per that suite's proposed
interface) while this task's `requirements-crypto.txt` (`cryptography`
only) is what actually gets merged into `gateway/requirements.txt`, that
check will fail even though the dependency is correctly pinned. Whoever
reconciles the two contracts should either add `cryptography` to that
list or confirm the check is superseded by this task's chosen
architecture.

## Consequences

- Both services need exactly one new dependency (`cryptography`, already
  pinned) rather than two (a KEM library plus a separate crypto library for
  the KDF/AEAD), simplifying `requirements-crypto.txt` and the resulting
  image.
- The gateway and cloud packages duplicate a small `wire.py` module
  (framing constants, HKDF/AEAD/MAC helpers) because they build into
  separate images and cannot import each other; keeping the two copies
  identical is a manual discipline documented in both files' headers and
  checked by `tests/crypto/test_kem_primitives.py::test_wire_module_is_byte_for_byte_identical_between_services`.
- Sessions amortize handshake cost but introduce lifecycle complexity
  (expiry, counter tracking, transparent re-handshake) that a per-message
  design would not have needed; this is judged worthwhile given the
  measured handshake cost (see design doc, "Measured overhead").
- Authentication is opt-in (`ML_KEM_PSK`): deployments that do not set it
  get confidentiality/integrity of the *data* against a passive eavesdropper
  and quantum-harvest-now-decrypt-later, but remain open to an active
  machine-in-the-middle impersonating either endpoint. This is a residual
  risk recorded in the design doc, not a claim of full protection.

## Verification

- `./.venv/bin/python -m pytest tests/crypto -q`: 106 passed (48 from this
  task; 58 from the concurrently-written suite described above).
- `./.venv/bin/python -m py_compile` on every file created by this task
  (both crypto packages and the test suite): no errors.
- ML-KEM-768 round trip and FIPS 203 sizes confirmed directly against the
  chosen library (`cryptography.hazmat.primitives.asymmetric.mlkem`):
  encapsulation key 1184 B, ciphertext 1088 B, shared secret 32 B; DER/PKCS8
  private-key persistence round trip confirmed; implicit-rejection
  behaviour on a content-tampered (but correct-length) ciphertext confirmed
  (no exception, silently wrong shared secret) and cross-checked against
  `kyber-py` showing the same behaviour.
- HKDF and AESGCM usage checked against Context7 documentation for
  `/pyca/cryptography` (see Sources).
- Measured overhead (method and caveats in
  `tests/crypto/test_timing.py` and the design doc): keygen median 0.44 ms,
  encaps median 0.13 ms, decaps median 0.19 ms (n=100 each, this machine,
  Python 3.13.12); full handshake via FastAPI TestClient (in-process ASGI,
  no real network) median 2.10 ms, p95 2.90 ms (n=20); AES-256-GCM
  encrypt/decrypt post-HKDF median 0.0025 ms each (n=1000). Not
  benchmark-grade; see the design doc for caveats.
- `kyber-py`'s own PyPI package metadata was read locally
  (`.venv/lib/python3.13/site-packages/kyber_py-1.2.0.dist-info/METADATA`)
  to obtain its verbatim production-readiness disclaimer, since Context7
  has no entry for `kyber-py` (checked via `resolve-library-id`; only
  unrelated libraries were returned).
- Docker-based container verification was **not run**: the Docker daemon is
  unavailable in this environment. The `cryptography==50.0.1` pin's
  resolvability against the containers' actual Python 3.12 base image is
  therefore unverified here and is called out as a residual risk / rollout
  step in the design doc.

## Sources

- [NIST FIPS 203: ML-KEM standard](https://csrc.nist.gov/pubs/fips/203/final)
  (already linked from the project README).
- Context7 `/pyca/cryptography` documentation, queried for ML-KEM
  (`MLKEM768PrivateKey`/`MLKEM768PublicKey`, `encapsulate`/`decapsulate`,
  `public_bytes`/`private_bytes`/`from_public_bytes`), HKDF, and AESGCM /
  ChaCha20Poly1305 usage -- source: `github.com/pyca/cryptography` docs,
  High source reputation, benchmark score 88.94 at time of query.
- Context7 `resolve-library-id` for "kyber-py": returned no matching
  library (unrelated results only); Context7 is therefore recorded as
  **thin/unavailable for this specific library**, and `kyber-py`'s own
  PyPI package metadata (its README, embedded in the wheel's `METADATA`
  file) was used instead, per AGENTS.md's fallback instruction.
- Local verification commands and their output (this session): `pip show
  cryptography kyber-py`; direct exercise of
  `cryptography.hazmat.primitives.asymmetric.mlkem`,
  `cryptography.hazmat.primitives.kdf.hkdf.HKDF`, and
  `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- `liboqs` / Open Quantum Safe project documentation (general knowledge of
  its long-standing "not for production" framing and native build
  requirements); not installed or exercised in this environment, so this
  entry is a documented limitation, not a hands-on finding.
