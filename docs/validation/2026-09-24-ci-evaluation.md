# CI evaluation and improvement — 2026-09-24

Scope: an evaluation of `.github/workflows/ci.yml` as released in v2.0.0, the gaps it had, the changes made on branch `ci/root-suites` for 2.1.0, and the evidence that the changed pipeline detects real faults. Recorded as prompt [P011](../ai/prompts/2026-09-24-yyy-tom.md#p011-evaluate-and-improve-ci-for-210). Everything below is a current observation from 2026-09-24 unless it is marked historical.

## Baseline

| Item | Value |
| --- | --- |
| Evaluated commit | `24bbe31` on `develop` (the `v2.0.0` release commit `9bb782a` plus one docs-only commit, the P009 addendum). No code or workflow differs from `v2.0.0`. |
| Release state | `v2.0.0` tagged and released on 2026-09-24 (GitHub Release "v2.0.0 - ML-KEM Integration"); `v1.0.0` also released. Evaluation branches `release/1.0.0` and `release/2.0.0` exist. |
| Working tree at start | Clean. Changes were made on a new branch, `ci/root-suites`, from `24bbe31`. |
| Local environment | macOS 15.7.5 (Darwin 24.6.0, arm64); Python 3.12.13 in fresh venvs for CI-equivalent runs (the shared `.venv` is Python 3.13.12 and was used only for quick checks); Docker 29.4.3; ruff 0.14.5. |
| CI environment | GitHub-hosted `ubuntu-latest`, Python 3.12 via `actions/setup-python`. |

## Previously observed issues, re-checked

| Observation | Verdict | Current evidence |
| --- | --- | --- |
| CI runs the three service suites and `tests/integration`, but not `tests/crypto`, `tests/reliability`, `tests/protected_path` or `tests/tooling` | **Confirmed**, and worse than stated: those four suites could not even have run from a clean install. `requirements-dev.txt` did not include `fastapi` or `cryptography`, so `tests/crypto` and `tests/reliability` fail at collection (pytest exit 4, `ModuleNotFoundError`) in a fresh Python 3.12 venv. They only ever passed in a shared venv that happened to have the service packages installed. | Fresh-venv runs at `24bbe31`, below. `ci.yml` at `24bbe31` has no step that collects `tests/` outside `tests/integration`. |
| Some documentation said CI had never run, though later records reported successful runs | **Confirmed, partly already fixed.** The README and project plan were corrected in the v2.0.0 release, but then said publishing "first runs on the `v2.0.0` tag", which became false minutes later. `tests/conftest.py` pointed at a non-existent path, and `docs/security/ml-kem-integration.md` still said the crypto packages were "not yet wired into the running services". | GitHub: 17 `CI` runs, all successful, the first on 2026-09-15 (run 34973182312). Stale lines corrected on this branch; historical validation records left as written. |
| A protected-path test is skipped because it expects a sessionless `gateway/app/kem.py` | **Confirmed.** It is a module-level skip, so all seven contract tests were silently absent. A second finding: `test_no_quantum_vulnerable_key_agreement.py` passed vacuously, because its library allowlist omits `cryptography` (the library ADR 0002 chose) and its pin test returned early when `kem.py` was absent. | See [Protected-path contract](#protected-path-contract). |
| Image publishing and shared deployment lacked verified evidence | **Publishing: now verified. Deployment: confirmed missing.** | See [Publishing and deployment](#publishing-and-deployment). |
| `check_docs.py`'s handling of `git diff --check` exit code 2 was fixed, with regression tests | **Confirmed fixed.** A trailing-space fault in `docs/README.md` produced violations and exit 1 in all four modes tried (staged or unstaged, with or without `--diff-ref`); raw `git diff --check` exited 2. `tests/tooling` (3 tests) passes. It was not run by CI before this change; it is now. | Fault F4 below. |

## CI before the change

| Requirement / suite | CI job | Executes? | Evidence produced | Gap |
| --- | --- | --- | --- | --- |
| gateway, cloud, device unit suites | `test` matrix | Yes, each from its own service directory | JUnit artifact and a job summary of counts | Skip reasons only in the log |
| `tests/integration` against the Compose stack | `smoke` via `scripts/smoke-test.sh` | Yes | JUnit artifact (warn if missing), logs | No job summary; covers no `/ready`, temperature-bound or secure-mode assertion |
| `tests/crypto` (ML-KEM KATs, secure channel) | none | **No** | none | Would also fail to import on a clean runner |
| `tests/reliability` | none | **No** | none | Would also fail to import on a clean runner |
| `tests/protected_path` | none | **No** | none | Contract module skipped; scan vacuous |
| `tests/tooling` (docs-checker regressions) | none | **No** | none | |
| ruff, compile check | `lint` | Yes | logs | |
| Compose validation | `compose-validate`, and inside smoke | Yes | logs | |
| Image builds | `build` | Yes, `linux/amd64` only, not pushed | logs | Smoke rebuilds instead of reusing them |
| Docs links and whitespace | `docs-check.yml` | Yes | logs | |
| Image publishing | `publish.yml` on `main` and `v*.*.*` tags | Yes, twice | logs, registry | Not gated on CI; amd64 only |
| Shared deployment | none | **No** | none | No environment exists |

Also checked: failure propagation is sound (default `bash -e`, `set -euo pipefail` in the scripts, `fail-fast: false`, `|| true` only on log dump and teardown); the smoke script always tears the stack down and dumps logs on failure; `tests/tooling` builds its own temporary Git repositories, so it needs no checkout history. `junit_summary.py` reported a suite whose tests were all skipped as `PASSED`.

`tests/crypto` and `tests/reliability` both load `gateway/app` and `cloud/app` under private aliases and change `sys.modules`; `tests/reliability/conftest.py` also sets `os.environ` for the whole process at import. They pass together in one process today, but the result depends on collection order, so they were kept in separate processes rather than combined.

## Acceptance criteria, set before implementing

1. `tests/crypto`, `tests/reliability`, `tests/protected_path` and `tests/tooling` each run in CI on Python 3.12, in their own `python -m pytest` process, from a clean checkout, on every pull request and push to `main` and `develop`.
2. Installing `requirements-dev.txt` alone is enough for those suites; CI checks that `fastapi`, `httpx` and `cryptography`'s `mlkem` import before running them.
3. A failure or collection error in any suite fails the workflow; `fail-fast: false` so every suite still reports; nothing masks pytest's exit code.
4. Each suite uploads a JUnit report and writes a job summary that names every failed, errored and skipped test with its reason. A suite in which nothing passed is not shown as `PASSED`.
5. A new skip cannot pass silently: each suite has a skip budget and the job fails when it is exceeded.
6. `smoke` also writes a job summary and waits for the root suites.
7. The protected-path requirements that fit the implemented design execute; the ones that do not are named with the decision each needs.
8. Current documentation matches the pipeline; historical records are not rewritten.
9. Each deliberate fault below is detected by a suite that CI now runs.

## Changes

| Change | Disposition | Reason |
| --- | --- | --- |
| New `root-tests` matrix job in `ci.yml`, one job and one pytest process per suite, JUnit upload, import check, `smoke` now `needs` it | Accepted | Criteria 1–3, 6. Separate processes keep the `app` package isolation. |
| `requirements-dev.txt` includes `-r gateway/requirements.txt` and `-r cloud/requirements.txt` | Accepted | The suites import both services in-process. No pin conflicts (`pip check` clean). The alternative, extra `-r` flags only in the workflow, would have left local setup broken. |
| `junit_summary.py`: lists failed/errored/skipped tests with reasons, `NO TESTS PASSED` status, optional `--max-skipped` exit code | Accepted | Criteria 4–5. Without `--max-skipped` it still always exits 0, so the unit and smoke jobs behave as before. |
| Skip and xfail budgets: all 0 except 1 skip for protected_path and 1 xfail for crypto | Accepted | Each allowed one names the group decision it waits on. |
| `tests/tooling/test_junit_summary.py` (9 tests) | Accepted | The budget check is what turns a silent skip into a red job, so it needs its own regression tests. |
| Combine all root suites into one pytest run | Rejected | Order- and environment-dependent, as above. |
| Make `smoke` reuse the `build` images | Not done | Worth doing, but outside the gaps this task confirmed. |
| Build arm64 images in `publish.yml` | Not done | A finding for the group, not a CI coverage gap. |
| Other `publish.yml` gaps: not gated on CI passing, older action majors than `ci.yml` (`checkout@v4`, `build-push-action@v6`), unscoped GitHub Actions build cache | Not done | Publishing works (verified below); these are hardening for a later change. |
| Protected-path contract port and scan fix | See below | |
| Stale-documentation corrections: README, project plan, `docs/operations/ci.md`, `docs/security/ml-kem-integration.md`, `docs/testing/ml-kem-verification.md`, `pytest.ini`, `tests/conftest.py`, `tests/integration/conftest.py` | Accepted | Criterion 8. Historical validation and prompt records are unchanged. |

## Protected-path contract

The contract in `tests/protected_path/test_protected_path_contract.py` was written against a proposed sessionless `gateway/app/kem.py`. Work package 3 built a session design instead (one ML-KEM handshake per session, then AES-256-GCM per reading), and both the contract's docstring and ADR 0002 say the contract should be rewritten for such a design. Each requirement was assessed against the implementation:

| Contract requirement | Implementation satisfies it? | Outcome |
| --- | --- | --- |
| a. Parameter set is ML-KEM-768 or -1024 | Yes | Ported; now reads the shipped constants and the handshake response rather than a literal |
| b. Key and ciphertext sizes match the parameter set | Yes (the decapsulation-key size is not observable through `KeyManager`) | Ported without the dk size, which the docstring states; ek and ct already pin the parameter set |
| c. Recorded traffic does not reveal the reading | Temperature and field names: yes. **Device id: no**, it is sent in clear as routing and AEAD associated data | Ported; the device-id assertion kept as a strict `xfail` |
| d. Recorded traffic carries ML-KEM material | Yes, per session | Ported to the session form: handshake ciphertext size, algorithm name, every data body bound to the handshake's session |
| e. The ML-KEM secret determines the session key | Yes | Ported, for both `wire.py` copies |
| f. An empty or classical-only secret is refused | **No**: `derive_session_key` has no length guard; safe in practice only because the client always passes a 32-byte ML-KEM secret | Not ported; needs a production change |
| g1. Failed key establishment sends nothing in plaintext | Yes | Ported: two failure modes, with `requests.post` answering 200 so a plaintext fallback would look like success and be caught |
| g2. The failure increments a counter | **No**: `GATEWAY_HANDSHAKE_FAILED_TOTAL` is defined but never incremented | Not ported |

The ported tests are in `tests/crypto/test_protected_path_session.py` because that suite already loads both services under private aliases. The original file is kept, still skipping as a module, with its reason and docstring updated to point at the port and name the open decisions. No production code was changed.

**Decisions needed from Stanley and Tiago:**

1. Is it acceptable that the device id travels in cleartext in every `/secure/data` body (a metadata leak to anyone recording the gateway→cloud link), or must it move inside the ciphertext?
2. Should `derive_session_key` reject a secret that is not exactly 32 bytes, in both `wire.py` copies, or is "there is no classical path" accepted as meeting requirement f?
3. Must key-establishment failures increment `gateway_handshake_failed_total{reason}` before work package 3 is accepted, or are `cloud_forward_failures_total` and a log line enough?

The source scan `test_no_quantum_vulnerable_key_agreement.py` was also fixed. Its allowlist now includes `cryptography`, counted only when its `mlkem` module is imported. Its pin test now checks, for gateway and cloud, that a service importing ML-KEM pins that library with `==` in its requirements; before, it returned early and asserted nothing. A new test checks that `gateway/app/crypto/client.py` and `cloud/app/crypto/keys.py` import `cryptography`'s `mlkem`.

## Required-suite coverage, before and after

| Suite | Tests (local, Python 3.12, fresh venv) | In CI before | In CI after |
| --- | --- | --- | --- |
| gateway unit | 24 passed | Yes | Yes |
| cloud unit | 20 passed | Yes | Yes |
| device unit | 43 passed | Yes | Yes |
| `tests/integration` | 7 (needs the stack; not run locally, see below) | Yes (smoke) | Yes (smoke) |
| `tests/crypto` | 116 passed, 1 xfailed (106 before the port) | **No** | Yes |
| `tests/reliability` | 57 passed | **No** | Yes |
| `tests/protected_path` | 35 passed, 1 skipped (32 passed, 1 skipped before) | **No** | Yes |
| `tests/tooling` | 12 passed (3 before; 9 new for the summary and budget check) | **No** | Yes |

## Deliberate faults

Each fault was injected alone in a disposable Git worktree of `24bbe31`, every suite was run the way CI runs it (fresh Python 3.12 venv), and the worktree was reverted and finally removed. None of these changes is in the branch.

| Fault | Injected change | Detected by | Detected by CI before? | Detected by CI after? |
| --- | --- | --- | --- | --- |
| F1a broken validation (cloud accepts an empty device ID) | `cloud/app/models.py` `min_length=1` → `0` | cloud unit `test_post_data_with_empty_device_id_is_rejected`; reliability `test_empty_device_id_rejected` | Yes (cloud unit) | Yes |
| F1b broken validation (gateway accepts 1000 °C) | `gateway/app/models.py` `MAX_TEMPERATURE_C` 60 → 1000 | reliability `test_temperature_out_of_range_rejected[60.1]` and `[500]` | **No**: gateway unit and integration have no bound test | Yes |
| F2 incorrect readiness (gateway `/ready` ready with cloud unreachable) | `gateway/app/main.py` `if check_cloud_health():` → `if True:` | reliability `test_ready_when_cloud_unreachable` | Only by accident: ruff flagged the now-unused import. A variant that keeps the call passes every test CI ran. | Yes, behaviourally |
| F3 failing cryptographic assertion (cloud accepts a replayed counter) | `cloud/app/crypto/sessions.py` replay checks → always accept | crypto `test_replayed_nonce_rejected`, `test_out_of_order_lower_counter_rejected_after_higher_one_seen` | **No** | Yes |
| F4 documentation whitespace | trailing spaces on `docs/README.md` line 3 | `check_docs.py`: violations, exit 1, in all four modes | Yes (`docs-check.yml`) | Yes |
| F5 corrupted ML-KEM known-answer vector | first `ek` byte changed in `tests/vectors/ml_kem_acvp.json` | crypto `test_key_generation_matches_nist_vectors[ML-KEM-512-tc1]` | **No** | Yes |
| F6 unexpected skip | a suite reports more skips than its budget | `junit_summary.py --max-skipped` exits 1 (checked against a real protected_path report: budget 0 → exit 1, budget 1 → exit 0, missing report → exit 1) | **No**: skips were passes | Yes |

The new and changed tests were also checked by breaking the code they guard, in the working tree, reverting each change with `git checkout --`:

| Mutation | Result |
| --- | --- |
| gateway `KEM_ALGORITHM` set to `ML-KEM-512` | 4 tests fail (parameter set, sizes ×2, wire copies identical) |
| `derive_session_key` ignores the secret, both copies | both requirement-e tests fail; every existing round-trip test still passed, so only the port catches it |
| `cloud_client` falls back to plaintext when the secure send fails | both fail-closed tests fail |
| the client sends the plaintext payload next to the ciphertext | the reading-hidden test fails |
| cloud handshake response names a different algorithm | the ML-KEM-material test fails |
| `cryptography==` pin removed from `gateway/requirements.txt`; cloud pin changed to `>=` | the pin test fails for that service |
| budget comparison in `junit_summary.py` disabled | 2 of the new `tests/tooling/test_junit_summary.py` tests fail |

The budget check itself caught a real case during this work: the first CI-equivalent run after the port reported crypto as over its skip budget, because pytest records an xfail as a JUnit `<skipped>` element. Expected failures are now counted separately, with their own budget, rather than raising the skip budget.

The fault runs are local executions of CI's commands, not GitHub runs. Remote verification of the final commit is recorded under [Remote CI](#remote-ci).

## Publishing and deployment

- `Publish images` has run twice, both successful: run 35974103248 (push to `main`, tags `main`, `sha-9bb782a`) and run 35974129641 (tag `v2.0.0`, tags `2.0.0`, `2.0`, `latest`, `sha-9bb782a`).
- The three `2.0.0` packages are public: an anonymous manifest request returned HTTP 200, with digests matching the run logs.
- **Pulled and run on 2026-09-24:** `ghcr.io/rolko6/software-development-and-maintenance-project-{cloud,gateway,device}:2.0.0` were pulled (digests `cloud@sha256:394da198…a7ac4`, `gateway@sha256:00a74f02…bd3c5`, `device@sha256:9f267d2d…42f48`) and started on a private Docker network with ML-KEM `enabled` and a test PSK. Gateway and cloud `/health` were healthy, gateway `/ready` reported the cloud reachable, a posted reading returned `forwarded`/`stored`, the device's own readings arrived, and the cloud log showed `POST /secure/handshake` and `POST /secure/data` with no plaintext `POST /data`. The containers and network were removed afterwards.
- **Finding:** the images are `linux/amd64` only. On an arm64 host (Apple Silicon) a plain `docker pull` fails with "no matching manifest for linux/arm64/v8"; the run above used `--platform=linux/amd64` emulation.
- Listing packages through the GitHub API returned 403 (the token lacks `read:packages`); the registry itself was queried instead.
- **Shared deployment: not verified, because none exists.** The repository has no deployments, no environments and no deploy workflow; `publish.yml` states there is no deployment target. This remains a human step in work package 4.

## Pipeline duration

| Run | Commit | Wall time | Slowest job |
| --- | --- | --- | --- |
| CI on PR #5 (`pull_request`, before) | `82535f3` | 75 s | smoke 31 s |
| CI on push to `main` (before) | `9bb782a` | 80 s | smoke 33 s |
| CI on draft PR #6 (after), run 35976176991 | `f275b5e` | 78 s | smoke 35 s; root-tests legs 14–24 s, in parallel with the unit legs |

Durations are GitHub-hosted runs and vary with runner load; a single run on each side is not a controlled comparison. Locally the four root suites take about 0.3–2.3 s each after a ~7 s dependency install.

## Remote CI

Draft pull request [#6](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/6) (`ci/root-suites` → `develop`) was opened so CI could run on the branch, because `ci.yml` triggers only on pull requests and on pushes to `main` and `develop`.

- `CI` run 35976176991 on `f275b5e`: all 13 jobs passed, including the four new `Root tests` legs on GitHub's Python 3.12.14. The dependency import check passed on the clean runner. Counts: crypto 116 passed, 1 xfailed; reliability 57; protected_path 35 passed, 1 skipped; tooling 11; gateway 24, cloud 20, device 43.
- The job summaries rendered as intended: crypto listed its xfail with the Stanley/Tiago reason, and protected_path listed its skip. That run showed the skip reason as a raw tuple with the runner's file path. The final commit fixes that, adds a regression test for it (tooling: 12 tests), and records this section.
- `Docs check` run 35976176919 on `f275b5e`: passed.
- The final commit gets its own `CI` and `Docs check` runs on PR #6. Their result is in the PR's checks, not here, because this record is part of that commit.
- The deliberate faults were not pushed to GitHub. Their detection was shown by running CI's commands locally (above), not by a failing GitHub run.
## Remaining skips and risks

- `tests/protected_path/test_protected_path_contract.py` still skips as a module; its skip reason names the decisions it waits on.
- The Docker smoke test was not run locally: a Compose stack from 8 days earlier was running on ports 8000/8001, and `scripts/smoke-test.sh` ends with `docker compose down -v`, which would have removed it. Smoke evidence comes from GitHub only.
- `publish.yml` does not depend on CI passing and builds amd64 only.
- `smoke` rebuilds images instead of reusing `build`'s, which costs time but not coverage.
- Skip budgets catch new skips, not tests that silently stop being collected; a deleted test file would still pass.
- Human review of these changes is not recorded.
