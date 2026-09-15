# Reliability validation — 2026-09-15

> **Superseded in part.** The Docker daemon was unavailable while this record was produced and was started later the same day, so the container checks listed here as not run were executed. See the [integration record](2026-09-15-integration.md).

Scope: work package 2, "Test and improve reliability" (see the
[project plan](../project-plan.md)). This record covers the
`tests/reliability/` suite added for this task, the five README
"Known limitations" fixes it proves, and the environment variables the
fixes introduced. It does not cover the ML-KEM/crypto suite
(`tests/crypto/`, `tests/protected_path/`), `tests/integration/`, the
per-service suites (`gateway/tests/`, `cloud/tests/`, `device/tests/`), the
`device/app/` restructuring, CI/CD, or monitoring — those are other
sessions' work with their own validation records (see the
[documentation index](../README.md)).

## Concurrent-editing note

This task ran while several other sessions were actively editing the same
working tree — a baseline session, an ML-KEM/crypto session, a device
restructuring session, and a CI/tests session, at minimum (visible in
`git status` and in `docs/validation/2026-09-15-tests-and-ci.md` and
`docs/validation/2026-09-15-device-modularization.md`). Two effects on this
work:

1. **`device/device.py` no longer exists.** It was replaced, by a concurrent
   session, with the `device/app/` package and `device/tests/` (see
   [device-modularization validation](2026-09-15-device-modularization.md)).
   That package's `device/app/gateway_client.py` and `device/app/runner.py`
   already distinguish a delivered (2xx) reading from a rejected (non-2xx)
   or errored (connection failure) one and log each case differently —
   README gap 1 ("device reporting") is already fixed there. Nothing under
   `device/app/` is in this task's file-ownership grant, so this record
   verifies that fix by reading the code and by the device-modularization
   record's own manual end-to-end evidence, rather than by a test added
   here.
2. **Shared root-level files.** `pytest.ini`, `requirements-dev.txt`, and
   `tests/conftest.py` / `tests/support.py` already existed, built by the
   ML-KEM session for `tests/crypto/`, `tests/protected_path/`,
   `tests/integration/`, and `tests/vectors/`. This task's suite lives in a
   new `tests/reliability/` subdirectory with its own `conftest.py`, so it
   never had to edit those files' content — the one exception is
   `requirements-dev.txt`, to which `httpx` and `respx` were appended (see
   [New environment variables and dependencies](#new-environment-variables)
   below); `httpx` had to be re-added after a concurrent edit removed it,
   since `tests/reliability/` needs it for `fastapi.testclient.TestClient`.

## What the suite covers

`tests/reliability/` (49 tests) exercises the gateway and cloud FastAPI
apps in-process, via `fastapi.testclient.TestClient` (an httpx ASGI
transport), with no Docker and no real network calls:

- **`test_gateway.py`** (28 tests) — `/health`, `/ready` (cloud reachable
  and unreachable), the OpenAPI schema (regression guard for the
  `sys.modules` import-aliasing trick described below), valid-reading
  forwarding, device ID validation (empty, 100-char boundary, 101-char
  rejection), missing fields, non-numeric temperature, temperature range
  boundaries and rejections, legacy numeric coercion (`int`, `float`,
  numeric string), the `DEVICE_MESSAGES_TOTAL` counter (incremented only
  on valid readings, not on 422s), cloud failure (502 + exact documented
  body + `CLOUD_FORWARD_FAILURES_TOTAL`), and the retry/backoff/deadline
  behaviour (recovers after transient errors, retries a 5xx, never retries
  a 4xx, gives up after the attempt budget, and never starts a new attempt
  once the time budget is spent).
- **`test_cloud.py`** (14 tests) — `/health`, `/ready`, the OpenAPI schema,
  `POST /data` storing and `GET /data` retrieving, the same device ID and
  temperature validation rejections as the gateway, storage isolation
  between tests, and the bounded-retention eviction behaviour (oldest
  readings dropped first once the configured limit is reached).
- **`test_reliability_end_to_end.py`** (3 tests) — a device-shaped payload
  through the gateway to the *real* cloud app (`requests.post` is
  monkeypatched to call `TestClient(cloud_app)`, so cloud's own validation
  and storage run for real): a reading lands in cloud storage; a full
  outage returns the documented 502 and the reading is never stored; a
  transient outage that clears within the retry budget still delivers.

**Import collision handled:** `gateway/app/` and `cloud/app/` each define
a top-level package literally named `app` (matching how their Dockerfiles
run `uvicorn app.main:app`). `tests/reliability/conftest.py` imports each
service exactly once per session and renames its modules from `app.*` to
a private alias (`gateway_app.*` / `cloud_app.*`) in `sys.modules`
immediately afterwards, so both can be imported in the same process. Any
bare `app` module another suite already left in `sys.modules` (observed
in practice: `tests/protected_path/test_protected_path_contract.py`
inserts the gateway root onto `sys.path` for its own `import app.kem`,
which is skipped because `gateway/app/kem.py` does not exist yet, but
still leaves `app` imported) is temporarily detached and restored
afterwards, rather than treated as an error. Gateway also registers
Prometheus counters in the global registry at import time, so importing
it more than once per process would raise "Duplicate timeseries" — the
single-import-per-session design avoids that too.

### How to run it

```bash
# This work package's suite only (fast, deterministic, no Docker/network):
./.venv/bin/python -m pytest tests/reliability -q

# The full repository suite (includes the ML-KEM, protected-path, and
# integration suites owned by other sessions):
./.venv/bin/python -m pytest -q
```

Dependencies: `pip install -r gateway/requirements.txt -r cloud/requirements.txt -r device/requirements.txt -r requirements-dev.txt` (already satisfied in the shared `.venv`).

## Problem → fix → regression test

| README "Known limitations" gap | Fix | Regression test(s) |
| --- | --- | --- |
| **Device reporting** — simulator printed "Sent data" even on HTTP error responses | Fixed by a concurrent session's `device/app/` restructuring (`device/app/gateway_client.py`'s `DeliveryResult` distinguishes delivered/rejected/error; `device/app/runner.py` logs each case differently). Not this task's source change. | Verified by reading `device/app/gateway_client.py` and `device/app/runner.py`, and by the manual end-to-end evidence in [2026-09-15-device-modularization.md](2026-09-15-device-modularization.md) (outage logs `Failed to deliver`, never a success line). No test added under this task, since `device/tests/` is outside this task's file-ownership grant. |
| **Inconsistent validation** — cloud accepted device IDs the gateway rejected; no temperature range check anywhere | `cloud/app/models.py` now enforces the same `device_id` length (1–100 chars) as `gateway/app/models.py`. Both models add `temperature: float = Field(ge=-40.0, le=60.0)` — a documented ambient-sensor range (see [Temperature range rationale](#temperature-range-rationale)). Device simulator's 15–30°C output range is unchanged. | `test_gateway.py::test_empty_device_id_rejected`, `::test_device_id_too_long_rejected`, `::test_device_id_max_length_accepted`, `::test_non_numeric_temperature_rejected`, `::test_temperature_out_of_range_rejected[...]`, `::test_temperature_boundary_values_accepted[...]`, `::test_temperature_accepts_int_float_and_numeric_string[...]`; `test_cloud.py::test_empty_device_id_rejected`, `::test_device_id_too_long_rejected`, `::test_non_numeric_temperature_rejected`, `::test_temperature_out_of_range_rejected[...]` |
| **Failed-reading loss** — a transient cloud failure discarded the reading with no retry | `gateway/app/cloud_client.py::send_to_cloud` retries connection errors and 5xx responses (never a 4xx) up to `CLOUD_FORWARD_MAX_ATTEMPTS` times with exponential backoff, bounded by a total wall-clock `CLOUD_FORWARD_TOTAL_BUDGET_SECONDS` deadline so it cannot outlast the caller. `gateway/app/main.py` maps a persistent failure to the same documented 502, and a cloud-side rejection (4xx) to a new 422. | `test_gateway.py::test_retry_recovers_after_transient_connection_errors`, `::test_retry_on_cloud_5xx_then_success`, `::test_retry_exhausted_after_max_attempts`, `::test_no_retry_on_4xx_cloud_rejection`, `::test_retry_stops_when_time_budget_exhausted`, `::test_cloud_failure_returns_502_and_increments_failure_counter`; `test_reliability_end_to_end.py::test_cloud_outage_returns_502_and_reading_is_lost`, `::test_cloud_recovers_after_transient_outage` |
| **Fixed health responses** — `/health` never checked anything, no readiness endpoint | `GET /health` unchanged on both services (liveness, legacy compatible). New `GET /ready` on the gateway calls `check_cloud_health()` (a real, short-timeout HTTP call to the cloud's `/health`) and returns 503 if unreachable. New `GET /ready` on the cloud returns 200 (it has no external dependency to check). | `test_gateway.py::test_health`, `::test_ready_when_cloud_reachable`, `::test_ready_when_cloud_unreachable`; `test_cloud.py::test_health`, `::test_ready` |
| **Unbounded storage** — the cloud's in-memory list grew forever | `cloud/app/storage.py` uses `collections.deque(maxlen=CLOUD_MAX_STORED_READINGS)` (default 1000); the oldest reading is evicted as new ones arrive. `GET /data` still returns a plain JSON array (`list(stored_data)`). | `test_cloud.py::test_storage_bounded_retention`, `::test_get_data_still_returns_a_plain_list`, `::test_get_data_returns_stored_reading` |

Two more behaviour changes, both direct consequences of the fixes above and
called out explicitly per AGENTS.md's contract-change requirement:

- **Cloud-side 4xx now surfaces as gateway 422, not 502.** Previously any
  exception from `send_to_cloud` (including an `HTTPError` from a 4xx) was
  reported as 502 "Cloud service unavailable". Now only connection
  errors/5xx/retry-exhaustion produce that 502 (byte-identical body,
  verified by `test_cloud_failure_returns_502_and_increments_failure_counter`
  and `test_reliability_end_to_end.py::test_cloud_outage_returns_502_and_reading_is_lost`);
  a 4xx from the cloud now raises `CloudRejected`, mapped to a 422 with a
  `"Cloud rejected reading: ..."` detail. In practice this path should be
  rare now that cloud and gateway validation match, but it is exercised in
  `test_no_retry_on_4xx_cloud_rejection` as a defensive case.
- **Per-attempt cloud-request timeout lowered from 5s (hardcoded) to a
  configurable `CLOUD_REQUEST_TIMEOUT_SECONDS` (default 1s).** Needed so
  the retry budget in the point above cannot exceed the simulated device's
  own fixed 5-second client timeout; see
  [Retry budget arithmetic](#retry-budget-arithmetic).

### Temperature range rationale

`-40.0`–`60.0`°C. Earth's recorded surface ambient extremes are roughly
-89.2°C (Vostok, Antarctica) and +56.7°C (Death Valley); -40..60
comfortably covers normal and extreme ambient deployments for a
general-purpose sensor while rejecting clearly invalid values (e.g. -273
or 1000). It does not change the simulator's 15–30°C output range. Defined
once in `gateway/app/models.py` and duplicated (with a cross-reference
comment) in `cloud/app/models.py`, since the two services do not share a
Python package.

### Retry budget arithmetic

Defaults: `CLOUD_FORWARD_MAX_ATTEMPTS=3`, `CLOUD_REQUEST_TIMEOUT_SECONDS=1`,
`CLOUD_FORWARD_BACKOFF_SECONDS=0.2` (exponential: 0.2s, then 0.4s),
`CLOUD_FORWARD_TOTAL_BUDGET_SECONDS=4`. `send_to_cloud` computes a single
deadline (`time.monotonic() + budget`) up front; before every attempt and
every backoff sleep it checks the remaining time and never starts one that
would not fit, so the whole retry sequence is capped at the configured
budget (default 4s), leaving roughly a second of headroom under the
simulated device's fixed 5-second client timeout (`device/app/config.py`)
before the device would experience its own timeout instead of a clean 502.

**Caveat, stated honestly:** `requests`' `timeout` parameter applies
separately to the connect and read phases of a single call, so one
pathological attempt (connects almost instantly, then hangs on the read
almost to the timeout) could in theory take up to roughly twice its
allotted per-attempt slice. The deadline check bounds how much time the
loop is willing to *schedule* across attempts and backoff; it is not a
hard kill switch on a single in-flight socket call (Python's `requests`
has no such mechanism without a separate thread/future). In practice this
only matters for a slow-reading, not-yet-failed connection — a refused
connection or a 5xx response (the cases this retry targets) fail
immediately, well inside the per-attempt timeout.

## Real pytest output

Run on 2026-09-15 from the repository root, `.venv` active:

```
$ ./.venv/bin/python -m pytest tests/reliability -q
.................................................                        [100%]
49 passed, 1 warning in 0.16s
```

The one warning is `starlette.testclient`'s own `anyio.abc.BlockingPortal`
deprecation notice, unrelated to this suite's code.

```
$ ./.venv/bin/python -m pytest -q
...
SKIPPED [1] tests/protected_path/test_protected_path_contract.py:57: gateway/app/kem.py does not exist yet: ML-KEM integration is project plan work package 3. These tests define what it has to satisfy.
ERROR tests/integration/test_end_to_end.py::test_gateway_health_returns_ok
ERROR tests/integration/test_end_to_end.py::test_cloud_health_returns_ok
ERROR tests/integration/test_end_to_end.py::test_post_device_data_is_forwarded_to_cloud
ERROR tests/integration/test_end_to_end.py::test_forwarded_reading_appears_in_cloud_data
ERROR tests/integration/test_end_to_end.py::test_post_device_data_with_empty_device_id_is_rejected
ERROR tests/integration/test_end_to_end.py::test_metrics_endpoint_exposes_counters_and_increments_on_valid_post
ERROR tests/integration/test_end_to_end.py::test_simulated_device_reaches_cloud_end_to_end
187 passed, 1 skipped, 1 warning, 7 errors in 61.90s (0:01:01)
```

The 7 errors are all in `tests/integration/test_end_to_end.py` (owned by
the ML-KEM session), which polls `http://localhost:8000/health` and
`http://localhost:8001/health` for 60s and fails with an explicit message
("Is `docker compose up --build -d` running?") when no Compose stack is
up — expected in this environment, per the task's own environment facts
(Docker daemon unavailable, do not start it). This task's 49 tests are
included in and pass within the 187.

For completeness, the concurrently-developed per-service suites (not owned
by this task) were also run read-only against the fixed `gateway/app` and
`cloud/app` source, from inside each service directory (required because
`gateway/app`, `cloud/app`, and `device/app` all use the package name
`app`):

```
$ (cd gateway && ../.venv/bin/python -m pytest -q)
24 passed, 1 warning in 0.04s

$ (cd cloud && ../.venv/bin/python -m pytest -q)
20 passed, 1 warning in 0.04s

$ (cd device && ../.venv/bin/python -m pytest -q)
43 passed in 0.07s
```

Earlier in this task, `docs/validation/2026-09-15-tests-and-ci.md` recorded
2 gateway and 2 cloud failures in these same suites, caused by this task's
in-progress source changes (a `Mock` without a real integer
`status_code` colliding with the new numeric status-code comparisons in
the retry logic; a test asserting `GET /data`'s old accept-empty-device-id
behaviour; a test asserting `get_all_data()` returned the live list object
rather than a copy, incompatible with the `deque`-based bounded retention).
Those suites are owned by other sessions; they were updated by their
owners and pass as shown above at the time of this writing. This record
does not take credit for those fixes.

## Executed vs. not run

| Check | Result |
| --- | --- |
| `./.venv/bin/python -m pytest tests/reliability -q` | Executed. `49 passed, 1 warning`. |
| `./.venv/bin/python -m pytest -q` (full repo) | Executed. `187 passed, 1 skipped, 1 warning, 7 errors` — errors are the Docker-dependent integration suite, not this task's tests. |
| `./.venv/bin/python -m py_compile` on every file this task changed | Executed. All compiled cleanly (`gateway/app/{models,cloud_client,main}.py`, `cloud/app/{models,storage,main}.py`, `tests/reliability/{conftest,test_gateway,test_cloud,test_reliability_end_to_end}.py`). |
| `docker compose config --quiet` | Executed. Exit 0 (parses cleanly; does not prove image builds or runtime behaviour). |
| `cd gateway/cloud/device && ../.venv/bin/python -m pytest -q` | Executed, read-only, for cross-suite confirmation (see above). Not this task's suites; not edited here. |
| Container build, `docker compose up`, and any in-container runtime check | Not run — Docker daemon unavailable in this environment, and the task instructions say not to try to start it. |
| Load/soak testing | Not run — out of scope for this work package. |
| `git diff --check` | Not run by this task on its own changes: several of this task's files (`docs/validation/2026-09-15-reliability.md`, all of `tests/reliability/`) are untracked, and `git diff --check` does not inspect untracked files. Checked instead with `grep -n ' $' docs/validation/2026-09-15-reliability.md` (no trailing whitespace) and by visual inspection of the fenced code blocks above (balanced). |

## New environment variables

| Name | Service | Default | Effect |
| --- | --- | --- | --- |
| `CLOUD_HEALTH_URL` | Gateway | Derived from `CLOUD_URL`: the `/data` suffix replaced with `/health` (e.g. `CLOUD_URL=http://cloud:8001/data` → `http://cloud:8001/health`); explicit setting overrides. | URL the gateway's `GET /ready` calls to check the cloud dependency. No Compose change is required for the default to resolve correctly inside the Compose network, since it derives from the already-configured `CLOUD_URL`. |
| `CLOUD_REQUEST_TIMEOUT_SECONDS` | Gateway | `1` (previously hardcoded to `5`, not configurable) | Per-attempt network timeout for the gateway→cloud forward call. Lowered from the old hardcoded value so the retry budget below cannot exceed the simulated device's fixed 5-second client timeout. |
| `CLOUD_READINESS_TIMEOUT_SECONDS` | Gateway | `2` | Timeout for the single-attempt cloud health check behind `GET /ready`. Independent of the forward retry budget below. |
| `CLOUD_FORWARD_MAX_ATTEMPTS` | Gateway | `3` | Maximum attempts (initial + retries) for one forwarded reading. Connection errors and 5xx responses are retried; a 4xx is never retried. |
| `CLOUD_FORWARD_BACKOFF_SECONDS` | Gateway | `0.2` | Base backoff between attempts, doubled each retry (0.2s, 0.4s, ...), capped by the remaining time budget below. |
| `CLOUD_FORWARD_TOTAL_BUDGET_SECONDS` | Gateway | `4` | Wall-clock ceiling across every attempt and backoff sleep combined for one forwarded reading. No further attempt starts once this elapses, bounding worst-case gateway latency below the device's client timeout. |
| `CLOUD_MAX_STORED_READINGS` | Cloud | `1000` | Maximum readings kept in memory (`collections.deque(maxlen=...)`); the oldest reading is evicted as new ones arrive. Readings are still lost entirely on process restart — this only bounds memory growth while running. |

All have safe defaults; none require a `docker-compose.yml` change to
function. An operator wanting to *tune* these under Compose (e.g. a
slower network needing a larger `CLOUD_REQUEST_TIMEOUT_SECONDS`) would add
them to the gateway/cloud `environment:` blocks — an optional
integration step, not a required one, since this task could not edit
`docker-compose.yml` (outside its file-ownership grant) and did not need
to.

## Residual risks

- **This is a retry, not a durable queue.** A reading that still fails
  after `CLOUD_FORWARD_MAX_ATTEMPTS` attempts and the total time budget is
  discarded exactly as before this task, with no persistence, no
  re-delivery once the gateway process moves on to the next request, and
  no de-duplication if a reading *did* reach the cloud but the gateway
  never saw the response (e.g. the response itself was lost after the
  cloud stored the reading) — such a reading could in principle be stored
  twice if a caller above the gateway retried independently. Proven lost
  (not queued) by `test_reliability_end_to_end.py::test_cloud_outage_returns_502_and_reading_is_lost`.
- **The retry cannot cover a slow-but-not-yet-failed connection exceeding
  its per-attempt timeout by roughly 2x**, per the caveat in
  [Retry budget arithmetic](#retry-budget-arithmetic) — `requests`'
  connect/read timeout split means the total budget is a scheduling
  ceiling, not a hard per-call kill switch.
- **Bounded storage drops the oldest readings first**, silently, once
  `CLOUD_MAX_STORED_READINGS` is reached — there is no archival, alerting,
  or backpressure signal to the gateway or device when eviction starts.
  `GET /data` never reflects evicted readings.
- **Gateway readiness only checks the cloud's `/health`,** not whether the
  cloud can actually accept and store a reading (e.g. the cloud process
  could be up and healthy while its own storage layer — currently
  in-memory, so not applicable today, but relevant if it is ever swapped
  for a real database — is failing). Cloud readiness is process-level
  only (it has no dependency to check today).
- **Two behaviour changes** (cloud-rejection now 422 instead of 502; the
  per-attempt timeout default lowered from an implicit 5s to 1s) are
  documented above and in the environment-variable table; both are
  intentional consequences of this work package, not accidents.
- **Not covered by this task at all:** the plaintext HTTP link (no
  authentication, authorization, or ML-KEM — work package 3), CI/CD
  (work package 4), and monitoring/alerting beyond the two pre-existing
  counters (work package 5).
