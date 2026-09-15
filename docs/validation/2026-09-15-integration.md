# Integration validation — 2026-09-15

Scope: wiring work packages 1–5 of the [project plan](../project-plan.md)
together and verifying them against the **real Docker Compose stack**, not only
in process. This record supersedes the "Docker daemon unavailable" statements in
the [baseline](2026-09-15-baseline.md), [reliability](2026-09-15-reliability.md),
[measurement method](2026-09-15-measurement-method.md) and
[tests and CI](2026-09-15-tests-and-ci.md) records: the daemon was unavailable
when those sub-tasks ran and was started afterwards, so the container checks they
list as "not run" were executed here.

## Environment

| Item | Value |
| --- | --- |
| Host | macOS 15.7.5 (Darwin 24.6.0), arm64 |
| Docker Engine | 29.4.3 |
| Docker Compose | v5.1.3 |
| Container Python | 3.12-slim |
| Local `.venv` Python | 3.13.12 |
| ML-KEM | `cryptography` 50.0.1, OpenSSL-backed ML-KEM-768 |
| Plaintext baseline revision | `1c72c3f`, built from a pristine `git archive` export |

## Plaintext baseline, in containers

Taken from a pristine export of `1c72c3f` so that concurrent edits to the
working tree could not contaminate it. 200 samples, 10 warm-up, host → published
ports, zero failures.

| Path | min | mean | median | p95 | max |
| --- | --- | --- | --- | --- | --- |
| end-to-end `POST /device-data` | 2.744 | 3.605 | 3.507 | 4.751 | 6.285 |
| gateway→cloud leg `POST /data` | 1.400 | 1.828 | 1.767 | 2.298 | 5.155 |

All values milliseconds.

## Gaps demonstrated before fixing

These were executed against the pristine stack, so the README's "Known
limitations" are evidenced rather than asserted.

| Probe | Observed |
| --- | --- |
| cloud `POST /data` with `device_id: ""` | HTTP 200 — while the gateway rejected the same input with 422 |
| gateway `POST /device-data` with `temperature: 999` | HTTP 200 — no physical range check |
| gateway `GET /health` with the cloud container stopped | `{"status":"healthy"}` — fixed response, no readiness signal |
| gateway `POST /device-data` with the cloud stopped | HTTP 502, `cloud_forward_failures_total` 0.0 → 1.0 (correct) |

## Defect found by container testing

The readiness endpoint added for work package 2 returned **503 against a
completely healthy cloud**. `_default_cloud_health_url()` appended `"health"`
instead of `"/health"`, so the Compose value `CLOUD_URL=http://cloud:8001/data`
derived `http://cloud:8001health` and `requests` raised `InvalidURL`.

The unit suite could not see this: `tests/reliability/conftest.py` sets
`CLOUD_HEALTH_URL` explicitly, so the default derivation was never exercised.
Fixed, with `tests/reliability/test_cloud_health_url_default.py` covering all
four URL shapes.

| Check | Observed |
| --- | --- |
| gateway `/ready`, cloud up | HTTP 200 `{"status":"ready","cloud":"reachable"}` |
| gateway `/ready`, cloud stopped | HTTP 503 |
| gateway `/health`, cloud stopped | HTTP 200 — liveness unchanged, legacy contract preserved |
| gateway `/ready`, cloud restarted | HTTP 200 |

## ML-KEM verified in containers

| Check | Observed |
| --- | --- |
| Cloud access log over a run | 6× `POST /secure/data`, 2× `GET /secure/handshake`, 1× `POST /secure/handshake`, **0× plaintext `POST /data`** |
| `mode=enabled`, plaintext `POST /data` | HTTP 200, stored |
| `mode=required`, plaintext `POST /data` | HTTP 403, **not** stored |
| `mode=required`, reading via gateway | forwarded and stored — the gateway uses the protected path |
| Cloud container recreated mid-run | next reading succeeded — automatic session recovery |
| `mode=off` **with an unwritable key path** | cloud health 200, plaintext forwarding works — rollback is safe |

The last row is the reason `app.crypto` is imported only when the mode is not
`off`. Importing it eagerly raised `OSError [Errno 30]` with an unwritable
`CLOUD_ML_KEM_KEY_PATH`, which would have crashed the cloud at startup even with
the feature switched off.

## Plaintext vs ML-KEM, comparable conditions

Same host, same containers, same 200 samples with 10 warm-up, same payload
shape, one variable changed.

| Path | plaintext mean | ML-KEM mean | plaintext p95 | ML-KEM p95 |
| --- | --- | --- | --- | --- |
| end-to-end `POST /device-data` | 3.605 | 3.641 | 4.751 | 4.709 |

Mean overhead **+0.036 ms (+1.0%)**, p95 slightly lower — inside run-to-run
noise. This is expected rather than surprising: the ML-KEM-768 handshake
(~2.1 ms, measured in process) happens once per session and is amortised, while
per-message AES-256-GCM costs roughly 0.0025 ms against a ~3.6 ms HTTP round
trip.

**Do not read this as "post-quantum security is free."** It says the steady-state
cost is invisible at this message rate on loopback. It says nothing about
handshake storms, constrained devices, real networks, or native vs. pure-Python
implementations.

## Test suites

| Suite | Result |
| --- | --- |
| root `pytest` (incl. `tests/integration` against the live stack) | 202 passed, 1 skipped |
| `gateway` | 24 passed |
| `cloud` | 20 passed |
| `device` | 43 passed |
| `ruff` 0.14.5, repo-wide | clean |
| `docker compose config --quiet` | exit 0 |
| `docker compose build` | all three images built |

`tests/integration` previously reported 7 errors because no stack was running;
with the stack up it is 7 passed.

## Not run

- The GitHub Actions workflows have never executed; that needs a real push or
  pull request.
- No Prometheus or Grafana instance was started, so no scrape or query has run.
  The metric definitions register but most counters are not yet incremented from
  the service code.
- No shared test environment has been provisioned and no deployment evidence
  exists.
- No sustained or concurrent load testing, no multi-host networking, and no
  measurement of a native-vs-pure-Python KEM comparison.
- One skipped test, `tests/protected_path/test_protected_path_contract.py`,
  expects a `gateway/app/kem.py` built to a different (per-message, sessionless)
  architecture than the session-based one implemented here. That contract
  mismatch is unresolved and needs a human decision.

## Concurrency caveat

Several Claude Code sessions edited this working tree simultaneously on
2026-09-15 (see prompt records P004–P006). Results above were taken from the
tree as committed in this session's work-package commits; suites owned by other
sessions were run read-only and are attributed to them.
