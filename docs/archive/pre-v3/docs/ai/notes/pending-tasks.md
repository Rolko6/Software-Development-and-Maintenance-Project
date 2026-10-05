> Historical pre-v3 documentation, recovered from [4f2b22d](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/ai/notes/pending-tasks.md). Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../../../../../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Pending tasks before the final submission

From a whole-project review at the end of v2.1.0, measured against the course brief (`docs/project-description.pdf`) and the work allocation in GitHub issue #4. The review was done by Claude Code (Opus 5.5) at Stanley's request; it was an analysis, so it has no prompt record of its own, and the prompt behind each item is recorded in the version file of the release that fixes it. This is a working list, not a record of completed work. Tick items off, or move them to the [project plan](../../project-plan.md), as they are done. v2.1.0 is released as it stands; the open items below are for v2.2.0 and later.

Ownership as agreed in the team: Roland owns the device and storage work, Tiago and Francisca focus mainly on the report, Tom's CI/release allocation is done, and the remaining technical work sits with Stanley.

Status legend: **Confirmed** = reproduced by a test or command; **Source** = found by reading the code, not yet executed.

Key dates: peer-review submission Sun 11 Oct, presentations Thu 15 – Fri 16 Oct, final deadline Sun 25 Oct.

## Gaps against the course brief

- [ ] **Deployment to a test environment** — the brief requires it; [deployment.md](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/4f2b22d761ca7d7bbb631732c6189790b7aabe99/docs/operations/deployment.md) says no shared environment has been provisioned.
- [ ] **Outage detection** — Prometheus has no alert rules; the alerting table in [monitoring.md](../../operations/monitoring.md) is only a suggestion.
- [ ] **Final evaluation** — no measured 2.0.0 vs 2.1.0 comparison exists yet.
- [x] **Critical LLM evaluation (Stanley's records)** — [v1.0.0.md](../prompts/v1.0.0.md) and [v2.1.0.md](../prompts/v2.1.0.md) now record decision, check, limits of the check and remaining risk for each entry, following the [AI docs guide](ai-docs-guide.md). Keep this format for v2.2.0.
- [ ] **Report perspective** — choose one of the three (the security work points to "Information security and organizational cybersecurity").
- [ ] **Individual reflections** — 400–500 words each, every team member.

## Stanley — ML-KEM, gateway security, and remaining technical work

### Security findings

- [ ] **S1. AES-GCM nonce reuse and stuck session after a lost response** (Confirmed).
  `gateway/app/crypto/client.py`, `_send_locked`, only advances `session.counter` after a successful response. When the cloud stores a reading but the reply is lost (timeout), the gateway sends the next, *different* reading under the same key with the same nonce. GCM nonce reuse leaks the XOR of plaintexts and enables forgery. The cloud then answers `409` to every reading until the gateway's proactive rekey (session TTL 300 s minus 15 s skew ≈ 285 s outage), and the "failed" reading was in fact stored.
  In-process reproduction against the real cloud router (temporary test, since removed):
  `sent (nonce, status): [(…AAAA,200), (…AAAB,200), (…AAAB,409), (…AAAB,409), (…AAAB,409)]`, `stored: [20.0, 21.0]`.
  Fix direction: reserve the counter before sending so a nonce is never reused; on `409` or an unknown outcome discard the session and re-handshake. Add a regression test.
- [ ] **S2. ML-KEM path can be bypassed** (Source). Compose runs the cloud in `enabled` with port 8001 published to the host, so anyone can `POST /data` in plaintext. `GET /data` is unauthenticated. The device→gateway hop is plaintext with no device authentication, so any `device_id` can be injected through the gateway. Decide: stop publishing the cloud port, default to `required`, add at least a token for `GET /data` and device ingestion; document what stays exposed.
- [ ] **S3. Placeholder PSK accepted silently** (Source). `dev-only-insecure-psk-change-me` is committed; an empty PSK only logs a warning. In `required` mode refuse to start without a PSK, with the placeholder, or with a too-short PSK.
- [ ] **S4. Mode typos fail silently** (Source). `GATEWAY_ML_KEM_MODE=enabeld` → `cloud_client` treats any non-`off` value as secure while the metric reports `off`. The same typo on the cloud mounts the secure router, but `get_cloud_mode()` returns `off`, so every `/secure/*` call is `403`. Reject unknown values at startup.
- [ ] **S5. Secure path ignores the gateway's timeout and retry policy** (Source). `_send_secure` does not receive `attempt_timeout`; the client uses 5 s per call and a new handshake takes up to three calls, exceeding the 4 s budget and the device's 5 s timeout. Secure-path 5xx is not retried (plaintext 5xx is). `401` (wrong PSK), `409` (replay), `400` (tampering) all reach the device as the same `502 "Cloud service unavailable"`, and failed secure attempts are not observed in `gateway_cloud_request_duration_seconds`.
- [ ] **S6. Residual risks for the threat model** (Source). Unauthenticated handshake flooding grows the session table without a cap or rate limit; replayed handshakes mint sessions (already documented); `key_id` is a constant (`cloud-mlkem768-1`), so rotated keys share an ID; private key is unencrypted in the Docker volume; no key rotation; the gateway's `POST /device-data` has no rate limit either.
- [ ] **S8. Cloud replies to `/secure/data` are not authenticated** (Source). The reading is AES-GCM protected, but the reply `{"status": "stored"}` is plain JSON with no MAC. An attacker between gateway and cloud can drop the encrypted reading and answer `200 stored` itself; gateway and device then report a delivery that never happened. Fix direction: the cloud authenticates its reply with the session key, bound to the request's counter, and the gateway verifies it (a wire-format change on both sides). A gateway decrypt-failure counter belongs with that change. Found while deciding M2; not in v2.3.0.
- [ ] **S7. Security evidence for the report.** Expected vs actual for: wrong PSK, tampered ciphertext, replayed message, expired session, forbidden plaintext in `required`, and the S1 scenario — including whether anything was wrongly stored. Handshake and message latency: median and p95, new-session vs reused-session requests separately.

### Metrics and monitoring correctness

- [ ] **M1. Retry counter counts every attempt** (Source). `gateway_cloud_retry_attempts_total` is documented as "retries only, excluding the first attempt", but `cloud_client.send_to_cloud` increments it before every attempt, including the first.
- [ ] **M2. Crypto failure counters never incremented** (Source). `gateway_crypto_encrypt_failures_total`, `gateway_crypto_decrypt_failures_total` and `cloud_crypto_encrypt_failures_total` have no `.inc()` anywhere. The gateway never decrypts a cloud response (responses are plaintext JSON), so its decrypt counter cannot move. Wire them or remove them and their dashboard panels.
- [ ] **M3. Cloud secure-data rejections not counted** (Source). Only AEAD tag failures are counted; `404`/`410`/`409`/payload-validation `400` on `/secure/data` have no metric, so replay attempts are invisible in Grafana.
- [ ] **M4. Alert rules** — add Prometheus rules: target down, handshake failures, decrypt failures, no readings stored for N minutes, forward failures.
- [ ] **M5. Compose healthchecks** — `healthcheck:` entries and `depends_on: condition: service_healthy`.
- [ ] **M6. `_reusing` metrics helper** in `gateway/app/metrics.py` and `cloud/app/metrics.py` relies on the private `REGISTRY._names_to_collectors`; a `prometheus_client` upgrade could break it at import time. It exists so the test harness can import both services' metrics in one process.

### CI, deployment and reliability (remaining from other allocations)

- [ ] **C1.** Merge draft PR #6 and confirm the `test-root` job passes on GitHub.
- [ ] **C2.** Add security/static analysis to CI (for example `bandit`, `pip-audit`); lint currently runs only `ruff`.
- [ ] **C3.** Deliberate-defect run: introduce a small documented set of defects in an isolated checkout, record which tests catch them and whether CI fails. S1 makes a good one once its regression test exists.
- [ ] **C4.** Python version drift: root tests run locally on 3.14; containers and CI use 3.12.
- [ ] **C5.** Provision the shared test environment and have a teammate redeploy from the docs (record time and undocumented steps).
- [ ] **C6.** Reliability experiment: delivery / loss / duplication with gateway retries active (retries can create duplicates; S1 hides stored readings as failures), recovery time after a cloud restart, 2.0.0 vs 2.1.0 with one procedure.
- [ ] **C7.** Release v2.1.0 (merge `develop` to `main`, tag, GitHub Release from `local/v2.1.0-release.md`).

### Documentation and AI records

- [x] **D1.** Rewrite the [v2.1.0.md](../prompts/v2.1.0.md) dispositions with real review decisions.
- [x] **D2.** Stanley's recording rules are in the [AI docs guide](ai-docs-guide.md) (opt-in; `AGENTS.md` unchanged).
- [ ] **D3. v2.1.0 README fix** (separate commit on `main` after the release merge): add the v2.1.0 row to the Versions table, and remove the three statements that are no longer true: "no Prometheus instance has been run", "the handshake and encrypt/decrypt counters in the crypto packages still read zero", "A Prometheus server and dashboard are not included".
- [ ] **D4. README restructure (v2.2.0)** — keep only content that rarely changes (purpose, architecture, quick start with basic checks, Versions table, links). Move per-release content (known limitations → version files; configuration table, manual failure checks, secure-channel checks → `docs/operations/`; test counts → removed). After that, a release only adds a Versions row. Tell Tom first, since he wrote most of the README. The repository tree also lacks `crypto/` and `monitoring/`.

## Roland — device simulation and storage

- [ ] **R1. Repeatable failure scenarios** in the device (seeded, selectable by configuration): stuck value, spikes, NaN, out-of-range values, missed readings, device silent / crash / reboot, network outage, bursts, clock drift. Today the device only sends a random value every 5 s.
- [ ] **R2. Local buffering and retry** on the device; failed readings are currently discarded.
- [ ] **R3. Sequence number and timestamp in the payload** — `recorded_at` never leaves the device, so the cloud cannot detect duplicates or know measurement time. Needs a backward-compatible gateway/cloud contract change.
- [ ] **R4. Several devices** in Compose.
- [ ] **R5. SQLite persistence** replacing the in-memory `deque`: retention policy, Compose volume, behaviour when the disk is full or the database is locked.
- [ ] **R6. Cloud `/ready` checks storage** — it currently always returns ready.
- [ ] **R7.** Stale comment in `cloud/app/storage.py` ("I recommend not doing that immediately"); `GET /data` returns everything without paging; README architecture still says "Store in memory".
- [ ] **R8.** Document the changes for 2.1.0/2.2.0; evidence on reading validity, persistence after restart, storage failure, legacy compatibility.

## Tiago and Francisca — report

- [ ] **P1.** Report structure (max. 5 pages) around the chosen perspective.
- [ ] **P2.** Organizational risk register and incident/response procedure (who handles incidents, who accepts unresolved risks), using the findings above.
- [ ] **P3.** Collect evidence from S7, C3, C5, C6, R8 into the report's evaluation section.
  Strengths to report (verify each against the code before using it):
  - Counter-poisoning defence: `cloud/app/crypto/sessions.py` checks the counter before decryption and commits it only after the ciphertext authenticates, so a forged message cannot block later valid ones.
  - The ML-KEM handshake is authenticated in both directions by the PSK MAC, and the gateway can pin the cloud key's fingerprint.
  - Breadth of testing: per-service unit suites plus ML-KEM known-answer, property, replay and protected-path tests, all run in CI.
  - Limit: the design's nonce argument (a restart always gets a fresh key) holds for restarts, but not for lost responses within a session (S1).
- [ ] **P4.** Presentation for 15–16 Oct and peer-review submission by 11 Oct.

## Tom

- Allocation (2.0.0 release, CI evaluation) is complete. Remaining CI follow-ups are listed under C1–C4.
