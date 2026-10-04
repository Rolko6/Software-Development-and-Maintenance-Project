> Historical pre-v3 documentation, recovered from [82599b2](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/validation/2026-09-29-ci-effectiveness.md). Its commands, findings and results apply to that source implementation; they do not establish v3 behaviour. See the [version comparison and recovery record](../recovery/2026-10-05-documentation-recovery.md). Original wording is retained below; navigation links and whitespace were repaired.

# Test and CI effectiveness, v2.2.0 — 2026-09-29

Metric from [issue #4](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/issues/4) ("Test and CI effectiveness", owners Tiago and Tom): *introduce a small, documented set of meaningful defects in an isolated checkout; record which tests detect them and whether CI executes those tests and fails.* This is item C3 in [pending-tasks.md](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/ai/notes/pending-tasks.md). Recorded as prompt [P012](../ai/prompts/2026-09-29-yyy-tom.md#p012-issue-4-test-and-ci-effectiveness-and-deployment-reproducibility). It repeats the method of the [2026-09-24 CI evaluation](2026-09-24-ci-evaluation.md), which measured v2.0.0, against the released v2.2.0.

## Setup

| Item | Value |
| --- | --- |
| Code under test | `origin/develop` at `0f309bd`. Its tree is identical to tag `v2.2.0` (`b0ca4ef`, `git diff --stat v2.2.0 0f309bd` is empty). |
| CI under test | `.github/workflows/ci.yml` and `docs-check.yml` as released in v2.2.0: jobs `lint` (compileall, ruff 0.14.5, `wire.py` identity), `test` (cloud / gateway / device unit suites), `test-root` (one pytest process over `tests/crypto tests/reliability tests/protected_path`), `compose-validate`, `build`, `smoke`, and `docs-check`. `tests/tooling` is not run by any job. |
| Isolation | A detached `git worktree` of `0f309bd` outside the repository. Each fault was applied alone, the checks were run, and the tree was restored with `git checkout -- .`; a script asserted a clean `git status` after every fault. |
| Local runner | macOS (arm64), Python 3.12.13; one fresh venv per CI job, installed from the same requirement file the job uses; ruff 0.14.5. The Docker `build` and `smoke` jobs were not run locally. |
| Remote runner | GitHub Actions on a throwaway draft pull request (#12), see [Remote CI](#remote-ci). |

Baseline, unmodified: every job passed. cloud 23 passed; gateway 31 passed; device 78 passed; `test-root` 195 passed, 1 skipped (the module-level skip in `tests/protected_path/test_protected_path_contract.py`); ruff, compile, `wire.py` identity, `docker compose config --quiet` and `check_docs.py` clean. `tests/tooling` (not in CI) 3 passed.

## Faults and results

"Local" is the set of CI jobs that failed when the job's commands were run locally. "GitHub" is the result of a real Actions run where the fault was pushed.

| ID | Fault (one change) | Tests that detected it | CI jobs that fail (local) | GitHub |
| --- | --- | --- | --- | --- |
| F1a | Cloud accepts an empty `device_id` (`cloud/app/models.py` `min_length=1` → `0`) | cloud unit `test_post_data_with_empty_device_id_is_rejected`; reliability `test_empty_device_id_rejected` | `test` (cloud), `test-root` | not pushed |
| F1b | Gateway accepts 1000 °C (`gateway/app/models.py` `MAX_TEMPERATURE_C` 60 → 1000) | reliability `test_temperature_out_of_range_rejected[60.1]`, `[500]`; on GitHub also gateway unit `test_validation_rejection_is_counted_as_rejected_validation[ds18b20_power_on_reset]` (see note 1) | `test-root` | detected, by `test` (gateway) only (note 2) |
| F2 | Gateway `/ready` reports ready with the cloud down (`if check_cloud_health():` → `if check_cloud_health() or True:`, import kept so ruff stays quiet) | reliability `test_ready_when_cloud_unreachable` | `test-root` | not pushed |
| F3 | Cloud accepts replayed ML-KEM counters (`cloud/app/crypto/sessions.py`, both counter checks disabled) | crypto `test_replayed_nonce_rejected`, `test_out_of_order_lower_counter_rejected_after_higher_one_seen` | `test-root` | not pushed |
| F4 | Trailing whitespace in `docs/README.md` | `check_docs.py` (3 violations, exit 1) | `docs-check` | detected |
| F5 | One byte of a NIST ML-KEM known-answer vector changed (`tests/vectors/ml_kem_acvp.json`) | crypto `test_key_generation_matches_nist_vectors[ML-KEM-512-tc1]` | `test-root` | not pushed |
| F6 | A whole test module silently skipped (`pytestmark = pytest.mark.skip` appended to `tests/reliability/test_gateway.py`) | **none** — `test-root` reports 166 passed, 30 skipped and exits 0 | **none** | **green** (153 passed, 30 skipped, together with F12) |
| F7 | Cloud's NaN fix reverted: the validation error for `NaN`/`Infinity` is no longer JSON-safe, so the cloud answers 500 instead of 422 | cloud unit `test_post_data_non_finite_temperature_returns_422_not_500[NaN / Infinity / -Infinity]` | `test` (cloud) | detected |
| F8 | Same revert in the gateway | gateway unit `test_non_finite_temperature_is_rejected_with_422_not_500[…]` ×3 and `test_validation_rejection_is_counted_as_rejected_validation[failed_read_nan]` | `test` (gateway) | not pushed |
| F9 | Gateway stops counting rejected readings (`.inc()` → `.inc(0)` on `rejected_validation`) | gateway unit `test_validation_rejection_is_counted_as_rejected_validation` ×3 | `test` (gateway) | not pushed |
| F10 | Device accepts `FAULT_*` rates that add up to more than 1 | device unit `test_fault_rates_summing_above_one_raise_value_error` | `test` (device) | detected |
| F11 | Gateway's copy of `wire.py` derives keys with a different HKDF label (`\|session\|` → `\|sess\|`) | lint's `wire.py` diff; crypto `test_wire_module_is_byte_for_byte_identical_between_services` and 7 handshake / secure-data tests | `lint`, `test-root` | detected, by `lint` and `test-root` |
| F12 | A test file no longer collected (`tests/crypto/test_secure_data.py` renamed so pytest ignores it) | **none** — `test-root` drops from 195 to 182 passed and exits 0 | **none** | **green** (with F6) |

Latent defect, not injected: **S1** in [pending-tasks.md](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/blob/82599b23ba46c71811f405c50310acb859862ed8/docs/ai/notes/pending-tasks.md) (the gateway's AES-GCM counter is committed only after a successful response, `gateway/app/crypto/client.py` lines 229–254 at `0f309bd`, so a lost response leads to nonce reuse). It is present in the code under test and every suite passes, so no current test detects it. This is the one real, known defect in the set, and CI does not catch it.

**Score for v2.2.0 CI:** 11 of the 13 injected faults fail at least one CI job; 2 (F6, F12) pass every job. Counting S1, 11 of 14 meaningful defects are detected. Every fault that was detected was detected by a job CI actually runs; no fault was caught only by `tests/tooling`.

Notes:

1. **F1b depends on the machine.** Gateway unit tests run with the default `CLOUD_URL=http://localhost:8001/data`. With the fault, the 85 °C "power-on reset" reading passes the gateway's validation and is really forwarded. Locally, an unrelated Compose stack was listening on port 8001, its cloud rejected the reading with 422, the gateway passed that 422 through, and the test passed. On GitHub nothing listens there, the forward fails, the gateway answers 502 and the test fails. So the gateway unit suite reaches the network when validation is broken, and whether it catches this fault depends on what is running on the host.
2. **F6 hid F1b on GitHub.** In the red run F6 (from the first commit) was still in place, so the reliability tests that catch F1b were among the 30 skipped. A silent skip removed the detection of a real defect in the same run.
3. F7 and F8 were first written as `if False:`, which ruff reported as an unused `math` import — the same accidental detection the 2026-09-24 record saw for `/ready`. They were rewritten so ruff stays quiet and only behaviour tests can catch them; the table shows the rewritten form.

## Remote CI

Draft pull request [#12](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/pull/12) (`tmp/ci-fault-injection-2026-09-29` → `develop`), opened with the user's approval, closed and its branch deleted after the runs:

| Commit | Faults | Run | Result |
| --- | --- | --- | --- |
| `5fd733e` | F6, F12 | CI [36499952282](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/actions/runs/36499952282), Docs check 36499952279 | **All 10 CI jobs and Docs check passed.** `test-root`: 153 passed, 30 skipped (baseline 195 passed, 1 skipped). |
| `b25e1e0` | + F1b, F4, F7, F10, F11 | CI [36500333452](https://github.com/Rolko6/Software-Development-and-Maintenance-Project/actions/runs/36500333452), Docs check 36500333469 | Failed: `lint` (wire.py diverged), `test-root` (3 failed, 150 passed, 30 skipped), `test` cloud (3 failed), device (1 failed), gateway (1 failed), `docs-check`. `build` and `smoke` were skipped because the jobs they need failed. |

## After porting PR #6

This branch merges `develop` into draft PR #6's CI work (merge commit `1f5bcd2`). The single `test-root` job is replaced by a `root-tests` matrix: one job and one pytest process each for `tests/crypto`, `tests/reliability`, `tests/protected_path` and `tests/tooling`, each with a skip and xfail budget checked by `.github/scripts/junit_summary.py` (all 0, except 1 skip for protected_path and 1 xfail for crypto, each tied to a named group decision). While merging, requirement g2 of the protected-path contract (a failed handshake is counted) was ported too, because v2.1.0 started incrementing `gateway_handshake_failed_total`.

The same 13 faults were re-run locally against `1f5bcd2` in a fresh worktree and venvs. Baseline: every job passed; crypto 116 passed, 1 xfailed; reliability 57; protected_path 35 passed, 1 skipped; tooling 12; cloud 23, gateway 31, device 78.

| ID | CI jobs that fail, v2.2.0 CI | CI jobs that fail, after the port |
| --- | --- | --- |
| F1a | `test` (cloud), `test-root` | `test` (cloud), `root-tests` (reliability) |
| F1b | `test-root` | `root-tests` (reliability) |
| F2 | `test-root` | `root-tests` (reliability) |
| F3 | `test-root` | `root-tests` (crypto) |
| F4 | `docs-check` | `docs-check` |
| F5 | `test-root` | `root-tests` (crypto) |
| **F6** | **none** | **`root-tests` (reliability): "Budget exceeded: 29 skipped, at most 0 allowed"** |
| F7 | `test` (cloud) | `test` (cloud) |
| F8 | `test` (gateway) | `test` (gateway) |
| F9 | `test` (gateway) | `test` (gateway) |
| F10 | `test` (device) | `test` (device) |
| F11 | `lint`, `test-root` | `lint`, `root-tests` (crypto) |
| **F12** | **none** | **none** — crypto drops from 116 to 103 passed and still passes |

After the port 12 of 13 faults are detected, and each failure names the suite, which the single `test-root` job did not. F12 is still missed: budgets count skips, not tests that are no longer collected. A per-suite minimum test count would close that; it is not part of this change. S1 is still undetected.

These post-port results are local runs; GitHub runs this branch's CI on its pull request.

## What this shows

- **Strong:** input validation, the NaN fixes, metrics wiring, device configuration, `wire.py` drift, the NIST vectors and replay protection each have a test that fails, and CI runs it. The v2.1.0 `test-root` job closes the gap the 2026-09-24 evaluation found (F1b, F2, F3, F5 were not detected by v2.0.0 CI).
- **Weak:** CI treats "fewer tests ran" as success. A skipped module (F6) or an uncollected file (F12) removes 13–42 tests and stays green, and F6 masked a real fault in the same run. The skip budgets and `tests/tooling` from draft PR #6 were never merged; see [After porting PR #6](#after-porting-pr-6), which catches F6 but not F12.
- **Environment-dependent tests:** gateway unit tests can reach `localhost:8001` (note 1).
- **Not caught:** S1, the lost-response nonce reuse.

## Limits of this measurement

- 13 faults chosen by the author of the CI changes; they are not a random sample. They were chosen to hit each CI job and each area changed in v2.1.0 and v2.2.0.
- Only 7 of the 13 were pushed to GitHub, in two combined runs, not one run per fault. The others are local runs of the same commands.
- Docker `build` and `smoke` were not run locally; on GitHub they were skipped in the red run and passed in the green one.
- Human review of this record: not recorded.
