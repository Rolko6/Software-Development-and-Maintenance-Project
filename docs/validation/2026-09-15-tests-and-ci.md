# Tests and CI/CD validation — 2026-09-15

Scope: the per-service `pytest` suites (`gateway/tests/`, `cloud/tests/`, `device/tests/`), the root `tests/integration/` HTTP suite, the helper scripts (`scripts/run-unit-tests.sh`, `scripts/smoke-test.sh`), and the two GitHub Actions workflows (`.github/workflows/ci.yml`, `.github/workflows/publish.yml`) added for [P006](../ai/prompts/2026-09-15.md). It does not cover the ML-KEM/crypto test suite, `tests/vectors/`, `scripts/baseline/`, or the device module restructuring — those have their own validation records (see the [documentation index](../README.md)).

This record was written while several other Claude Code sessions were actively editing the same working tree (see [Remaining uncertainty](#remaining-uncertainty)). It separates what this session actually executed from what the coordinating session reported as already verified before those concurrent edits landed.

## Executed by this session (2026-09-15)

| Check | Result |
| --- | --- |
| `cd gateway && python -m pytest -q` (run twice) | `2 failed, 20 passed, 1 warning`, both runs. Failures: `tests/test_gateway_cloud_client.py::test_send_to_cloud_posts_payload_and_returns_json` and `::test_send_to_cloud_propagates_raise_for_status_exception`, both raising `TypeError: '<' not supported between instances of 'MagicMock' and 'int'` inside `app/cloud_client.py`, which now contains retry/timeout logic (`CLOUD_FORWARD_MAX_ATTEMPTS`, `attempt_timeout`, `RETRYABLE_EXCEPTIONS`) that predates these tests' mocks. `gateway/app/cloud_client.py` and `gateway/app/metrics.py` showed as modified, uncommitted (`M`) in `git status` at the time of this check. |
| `cd cloud && python -m pytest -q` (run twice) | `2 failed, 13 passed, 1 warning`, both runs. Failures: `tests/test_cloud_data_api.py::test_post_data_with_empty_device_id_is_accepted` and `tests/test_cloud_storage.py::test_get_all_data_returns_the_live_internal_list_not_a_copy`. `cloud/app/main.py`, `cloud/app/models.py`, and `cloud/app/storage.py` all showed as modified, uncommitted (`M`) at the time of this check. |
| `PYTHON=python3 ./scripts/run-unit-tests.sh` | Exit 1. Combined summary: gateway 2 failed / 20 passed, cloud 2 failed / 13 passed, device 43 passed. The script itself worked as designed — it ran every suite, printed a correct combined summary, and exited non-zero because gateway and cloud failed. |
| `python -m pytest tests/integration -m integration --collect-only -q` | `7 tests collected`, all from `tests/integration/test_end_to_end.py` (module-level `pytestmark = pytest.mark.integration`). Matches the suite as built; full execution was not attempted (see [Not run](#not-run)). |
| `docker compose config --quiet` | Exit 0. |
| `bash -n scripts/run-unit-tests.sh` and `bash -n scripts/smoke-test.sh` | Exit 0 for both. |
| YAML parse of `.github/workflows/ci.yml` and `.github/workflows/publish.yml` | Both parse. `ci.yml`'s job names changed twice while this record was being written, as a concurrent session actively rewrote it (see [Remaining uncertainty](#remaining-uncertainty)). |
| `git diff --check` | Exit 0. |

## Reported by the coordinating session, not reproduced here

The task that requested this documentation stated the following had already run and passed, before the source edits observed above landed:

- `cd gateway && python -m pytest -q` → `22 passed, 1 warning`, on two consecutive runs.
- `cd cloud && python -m pytest -q` → `15 passed, 1 warning`, on two consecutive runs.
- `./scripts/run-unit-tests.sh` → exit 0; gateway 22, cloud 15, device 41, all passed.
- `./scripts/smoke-test.sh` → exit 0; images built, both services healthy, `7 passed` integration tests against the live stack, stack torn down cleanly; run twice.
- `docker compose config --quiet` also passed inside the smoke script.

This session did not reproduce the gateway/cloud pass counts or the smoke test. The gateway and cloud counts above no longer hold against the current `gateway/app` and `cloud/app` source, as shown in [Executed by this session](#executed-by-this-session-2026-09-15).

## Not run

- `./scripts/smoke-test.sh` — not (re-)executed by this session. Its `EXIT` trap unconditionally runs `docker compose down -v --remove-orphans`; other sessions on this machine may be using the Compose stack for concurrent baseline or latency work, and tearing it down without coordination would be unsafe. Its earlier passing run is recorded above as coordinator-reported, not reproduced.
- The `tests/integration` suite end-to-end (only `--collect-only` was run) — it needs the same running stack as the smoke test, for the same reason.
- The GitHub Actions workflows themselves — they cannot run outside GitHub Actions. Validated here only by YAML parsing and by reading each file against its documented steps.
- The GHCR image push in `publish.yml` — requires a push to `main` or a version tag and repository package permissions.
- Local unit-test runs used Python 3.13 (the repository's `.venv`); CI targets Python 3.12, matching the containers. That combination itself was not exercised locally.

## Remaining uncertainty

Several Claude Code sessions were modifying this working tree concurrently while this record was written. Observed directly during this task:

- `gateway/app/cloud_client.py` / `metrics.py` and `cloud/app/main.py` / `models.py` / `storage.py` changed under the gateway and cloud test suites, producing the two failures per service recorded above. These files are owned by other sessions; this record does not attempt to fix them or the tests.
- `.github/workflows/ci.yml` was rewritten by a concurrent session during this task: job names changed from `unit-tests` / `compose-validate` / `integration` to `lint` / `test` / `compose-validate` / `build` / `smoke`, and it gained a `ruff` lint step and references to `docs/operations/ci.md`. The README's "Continuous integration" section describes the workflows by behaviour rather than by exact job name for this reason.
- Root `pytest.ini` and `requirements-dev.txt` were extended by the concurrent ML-KEM verification work to also cover `tests/crypto/`, and `tests/integration/` gained two additional files for that work. The original 7-test suite (`test_end_to_end.py`) still collects cleanly and unchanged, as verified above.
- `device/tests/` now collects 43 tests (verified via `run-unit-tests.sh` above), not the 41 originally reported to this session; that is the device-modularization session's work, not this task's, and is not described further here.

This record covers the test suites, helper scripts, and CI/CD workflows only. It does not cover the other in-flight changes visible in `git status` at the time of writing.
