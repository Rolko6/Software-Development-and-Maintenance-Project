# Observability guide

Work Package 5 ("Monitor and evaluate"). Scope: every Prometheus metric
exposed by the gateway and cloud services, how to scrape and query them,
what they do and do not make observable, alerting suggestions, and the
caveats that apply to all of it.

Source of truth for names, types, help strings, and exact instrumentation
points is the code itself: [`gateway/app/metrics.py`](../../gateway/app/metrics.py)
and [`cloud/app/metrics.py`](../../cloud/app/metrics.py) — both carry a
module docstring listing, metric by metric, which file and function is
responsible for incrementing or observing it. This document is a reference
built from that source; if the two ever disagree, the code wins.

## How to scrape and query

See [`monitoring/README.md`](../../monitoring/README.md) for how to run
Prometheus (and optionally Grafana) against these services, why the
gateway's (and cloud's) metrics path is `/metrics/` with a trailing
slash, and a set of ready-to-use PromQL queries. In short:

```sh
docker compose -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml up --build -d
# Prometheus: http://localhost:9090   Grafana: http://localhost:3000
```

Manual, no-Prometheus inspection (as already documented in the project
[README](../../README.md)):

```sh
curl -fsS http://localhost:8000/metrics/   # gateway
curl -fsS http://localhost:8001/metrics/   # cloud, once the main agent mounts app.metrics.metrics_app there
```

## Metric inventory

Label values are fixed, small enumerations everywhere in this project —
**no metric here carries a `device_id`, session id, or any other
per-entity label.** That is a deliberate cardinality bound: the exposed
series count does not grow with fleet size, session count, or reading
volume.

### Gateway (`gateway/app/metrics.py`)

| Metric | Type | Labels | Meaning | Emitted where |
| --- | --- | --- | --- | --- |
| `device_messages_total` | Counter | — | Validated device readings received (existing metric, unchanged) | `gateway/app/main.py`, `receive_device_data`, before forwarding |
| `cloud_forward_failures_total` | Counter | — | Requests whose forwarding to the cloud ultimately failed — once per request, at the point retries (if any) are exhausted (existing metric; cadence preserved, see caveat below) | `gateway/app/cloud_client.py`, once per request when it gives up |
| `gateway_request_duration_seconds` | Histogram | `outcome`, `security_mode` | Time to handle one `POST /device-data`, receipt to response, including any retries | `gateway/app/main.py`, `receive_device_data` and its validation-error handler |
| `gateway_cloud_request_duration_seconds` | Histogram | `outcome`, `security_mode` | Duration of one gateway→cloud HTTP attempt (per attempt, not per request) | `gateway/app/cloud_client.py`, around each attempt |
| `gateway_delivery_outcome_total` | Counter | `outcome` | Requests by final delivery outcome | `gateway/app/main.py`, once per request |
| `gateway_cloud_retry_attempts_total` | Counter | — | Retry attempts issued (excludes each request's first attempt) | `gateway/app/cloud_client.py`, per retry |
| `gateway_cloud_retries_exhausted_total` | Counter | — | Requests whose retry budget was exhausted with no success | `gateway/app/cloud_client.py`, when giving up |
| `gateway_handshake_started_total` | Counter | — | ML-KEM handshakes initiated by the gateway | `gateway/app/crypto/*` |
| `gateway_handshake_succeeded_total` | Counter | — | ML-KEM handshakes that established a session | `gateway/app/crypto/*` |
| `gateway_handshake_failed_total` | Counter | `reason` | Failed handshakes, by reason | `gateway/app/crypto/*` |
| `gateway_handshake_duration_seconds` | Histogram | `outcome` | Duration of one full handshake attempt | `gateway/app/crypto/*` |
| `gateway_session_rekeys_total` | Counter | `reason` | Existing sessions replaced by a new handshake (excludes the first handshake with a peer) | `gateway/app/crypto/*` session manager |
| `gateway_crypto_encrypt_failures_total` | Counter | — | AEAD seal failures protecting an outbound payload to the cloud | `gateway/app/crypto/*` (or `cloud_client.py`) |
| `gateway_crypto_decrypt_failures_total` | Counter | — | AEAD open failures unwrapping a cloud response | `gateway/app/crypto/*` (or `cloud_client.py`) |
| `gateway_security_mode` | Enum (gauge family) | implicit `gateway_security_mode` label = state | Active gateway crypto mode: `off` / `enabled` / `required` | gateway startup and on every mode change |
| `gateway_build_info` | Info (gauge) | `version`, `commit`, `python_version` | Build/runtime metadata | Set once at import, in `metrics.py` itself |

**Caveat on `cloud_forward_failures_total`'s cadence:** its existing
meaning (one increment per request whose forwarding to the cloud
fails) is preserved deliberately, even though the retry-with-backoff
feature now makes multiple attempts per request. This keeps
`scripts/baseline/run_baseline.sh`'s existing assertion of exactly
`cloud_forward_failures_total 1.0` after one outage request valid.
Per-attempt failure counts (which do change per retry) are available
instead from `gateway_cloud_request_duration_seconds_count{outcome="failure"}`.
As a result, `cloud_forward_failures_total` and
`gateway_cloud_retries_exhausted_total` fire at the same event once
retries land (both "once per request, when the gateway gives up") —
that overlap is intentional: they are independent bookkeeping in two
different subsystems (the pre-existing top-level failure counter vs.
the new retry-specific counter), not a duplicate to be merged.

`outcome` values: delivery histograms/counters use `forwarded`,
`rejected_validation`, `failed_after_retries`; the cloud-attempt
histogram and handshake histogram use `success`, `failure`.
`security_mode` values: `off`, `enabled`, `required`. `reason` (handshake
failure): `timeout`, `peer_unavailable`, `decode_error`,
`verification_failed`, `other`. `reason` (rekey): `expired`, `forced`.

### Cloud (`cloud/app/metrics.py`)

| Metric | Type | Labels | Meaning | Emitted where |
| --- | --- | --- | --- | --- |
| `cloud_readings_stored_total` | Counter | — | Readings successfully stored | `cloud/app/storage.py` |
| `cloud_readings_rejected_total` | Counter | `reason` | Readings rejected by cloud-side validation | `cloud/app/main.py` |
| `cloud_storage_evictions_total` | Counter | — | Readings evicted to enforce bounded retention | `cloud/app/storage.py` |
| `cloud_stored_readings` | Gauge | — | Current number of readings held in memory | `cloud/app/storage.py`, set after every store/eviction |
| `cloud_request_duration_seconds` | Histogram | `outcome`, `security_mode` | Time to handle one `POST /data`, receipt to response | `cloud/app/main.py` |
| `cloud_handshake_started_total` | Counter | — | Handshake requests received from the gateway | `cloud/app/crypto/*` |
| `cloud_handshake_succeeded_total` | Counter | — | Handshakes the cloud completed successfully | `cloud/app/crypto/*` |
| `cloud_handshake_failed_total` | Counter | `reason` | Failed handshakes, by reason | `cloud/app/crypto/*` |
| `cloud_handshake_duration_seconds` | Histogram | `outcome` | Duration of one handshake request as processed by the cloud | `cloud/app/crypto/*` |
| `cloud_crypto_decrypt_failures_total` | Counter | — | AEAD open failures unwrapping a gateway payload | `cloud/app/crypto/*` |
| `cloud_crypto_encrypt_failures_total` | Counter | — | AEAD seal failures protecting a response to the gateway | `cloud/app/crypto/*` |
| `cloud_security_mode` | Enum (gauge family) | implicit `cloud_security_mode` label = state | Active cloud crypto mode: `off` / `enabled` / `required` | cloud startup and on every mode change |
| `cloud_build_info` | Info (gauge) | `version`, `commit`, `python_version` | Build/runtime metadata | Set once at import, in `metrics.py` itself |

`reason` values (readings rejected): `invalid_device_id`,
`invalid_temperature`, `other`. `metrics_app` (in `cloud/app/metrics.py`)
is a ready-to-mount ASGI app, not a metric; `cloud/app/main.py` mounts it
at `/metrics`.

Both services also expose the Python client's default process/platform
collectors (`python_gc_objects_collected_total`, `python_info`, and
similar) — standard `prometheus_client` output, not specific to this
project, and not listed above.

## What is observable

- Whether readings are being delivered, rejected, or ultimately
  failing, and at what rate, split by cause (validation vs.
  retries-exhausted).
- End-to-end and gateway→cloud latency distributions (percentiles via
  `histogram_quantile`), including a `security_mode` split for
  comparing plaintext and secured traffic when both were scraped.
- Retry activity: how often a retry is issued, and how often retries
  are exhausted without success.
- Handshake activity: attempt volume, success/failure split with
  reasons, and how long handshakes take.
- Raw counts of AEAD encrypt/decrypt failures on both sides — a signal
  that *something* went wrong cryptographically (bad session, garbled
  payload, or possible tampering), though not which.
- Which security mode each service currently believes is active.
- The cloud's current in-memory reading count and how often bounded
  retention evicts old readings.

## What is not observable

- **Per-device behaviour.** No metric carries a `device_id` label by
  design (see "Metric inventory" above); you cannot tell from these
  metrics whether one specific device is failing more than another.
- **The device→gateway leg.** Nothing here instruments the device
  simulator (`device/app/`); only the gateway→cloud leg and each
  service's own request handling are covered.
- **History beyond Prometheus's own retention.** Every counter,
  histogram, and gauge lives in an in-process `prometheus_client`
  registry with no persistence — it resets to zero the moment the
  gateway or cloud process restarts. Prometheus is the only place
  history survives, for as long as its own retention window keeps it
  (not configured by this work package; the default in
  `monitoring/prometheus.yml` sets scrape/evaluation intervals only).
- **Per-request tracing.** There is no request/trace ID correlating one
  gateway histogram observation with the specific cloud-side
  observation for that same request, or with a specific retry attempt.
- **Which request a given retry or failure belonged to**, beyond the
  aggregate attempt/exhaustion counts.
- **The specific cause of one failed request.** These are metrics, not
  per-request logs — use the existing application logging
  (`logger.exception` / `logger.info` calls in `main.py`) for that.
- **Tampering distinguished from a bug.** `*_crypto_decrypt_failures_total`
  counts both an authentication failure caused by an attacker and one
  caused by a session/key mismatch bug identically.
- **Resource cost.** No CPU, memory, or process-level cost of the
  ML-KEM handshake or AEAD operations is measured beyond wall-clock
  duration; a slow handshake and a CPU-starved handshake look the same
  here.
- **Behaviour under sustained or concurrent load.** All latency
  histograms measure single in-flight requests processed by this
  prototype's default (effectively single-worker) uvicorn processes;
  they say nothing about throughput limits, queuing, or contention
  under concurrent traffic, because none of the harnesses in this
  repository generate any.

## Alerting suggestions

Thresholds below are starting points sized for this prototype's actual
traffic (one simulated device, one reading roughly every 5 seconds — see
the device simulator under `device/app/`) and its measured loopback
latencies (low single-digit milliseconds per the existing baseline
work, see `scripts/baseline/`). Revisit them if traffic volume, network
path, or deployment target changes.

| Alert | Condition | Rationale |
| --- | --- | --- |
| Delivery failures (warning) | `sum(rate(gateway_delivery_outcome_total{outcome="failed_after_retries"}[5m])) / sum(rate(gateway_delivery_outcome_total[5m])) > 0.05` for 5m | A single cloud hiccup is absorbed by retries; a sustained >5% failure rate means retries are not enough. |
| Delivery failures (critical) | same query `> 0.2` for 5m | One in five (or worse) readings never arriving is a functional outage, not noise. |
| Retries being exhausted at all | `rate(gateway_cloud_retries_exhausted_total[5m]) > 0` for 5m | At this traffic volume (~12 requests/min), any sustained exhaustion is already a real, visible problem worth a look — there is no "background noise" level to filter out. |
| End-to-end latency (warning) | `histogram_quantile(0.95, sum(rate(gateway_request_duration_seconds_bucket[5m])) by (le)) > 0.25` for 5m | Observed loopback p95s are single-digit milliseconds; 250ms is ~2 orders of magnitude above that — generous enough to avoid noise, tight enough to catch real degradation (retry storms, GC pauses, resource starvation) before it is user-visible. |
| Handshake failures (warning) | `sum(rate(gateway_handshake_failed_total[15m])) / sum(rate(gateway_handshake_started_total[15m])) > 0.1` | Occasional handshake failure (peer restart, transient network blip) is expected; >10% sustained is not. |
| Handshake failures (critical) | same ratio `>= 1.0` for 5m | The secure link is completely down — in `required` mode this also means all delivery has stopped. |
| Any AEAD failure | `rate(gateway_crypto_decrypt_failures_total[5m]) > 0` or the `cloud_crypto_decrypt_failures_total` / `*_encrypt_failures_total` equivalents | Never expected in normal operation with a healthy, current session; worth immediate attention (bug or tampering) even at low absolute counts, because there is no legitimate reason for authenticated decryption to fail. |
| Storage evictions (info) | `rate(cloud_storage_evictions_total[15m]) > 0` | Expected behaviour of bounded retention, not a failure — but the operator should know old readings are being discarded, in case retention needs raising or real persistence is now warranted. |
| Unexpected mode downgrade (warning) | `changes(gateway_security_mode{gateway_security_mode="off"}[1h]) > 0` while a prior scrape showed `enabled`/`required` at 1 | Should only happen from a deliberate configuration change; an unplanned downgrade to `off` may indicate misconfiguration or rollback. |
| Target down | standard `up{job=~"gateway|cloud"} == 0` | A service that cannot be scraped cannot be monitored at all — treat as its own, independent, always-on alert. |

## Cardinality and retention caveats

- **Counters and histograms reset on restart.** Every metric in
  `gateway/app/metrics.py` and `cloud/app/metrics.py` lives in the
  default in-process `prometheus_client` `CollectorRegistry`. There is
  no cross-restart persistence anywhere in this project — a
  `docker compose restart gateway` (or a crash) zeroes every counter
  and clears every histogram bucket. Only Prometheus's own storage
  (outside this repository's scope beyond the scrape config) retains
  history across a target's restart.
- **No cross-service or cross-request correlation.** Prometheus's
  `job`/`service` labels (set in `monitoring/prometheus.yml`) tell you
  *which service* a series came from, not which request it belonged to.
- **Label sets are fixed, small enumerations everywhere**: `outcome`
  (2–3 values), `security_mode` (3 values), `reason` (3–5 values per
  metric). No label here is unbounded or grows with runtime state (no
  device id, session id, or timestamp-derived label), so total exposed
  series count for this project stays in the low hundreds regardless of
  how long the system runs or how many devices/readings/sessions exist.
- **`security_mode` on latency histograms assumes the mode is visible
  in-band.** If the ML-KEM integration only supports changing mode via
  a restart (not a live runtime toggle), then within any single process
  lifetime almost all observations will carry one `security_mode`
  value — Prometheus alone cannot then reconstruct a clean "before vs.
  after" comparison from one continuously-running process. Use
  [`scripts/evaluation/compare_latency.py`](../../scripts/evaluation/compare_latency.py)
  for a controlled, single-run comparison instead (see
  [`docs/validation/2026-09-15-measurement-method.md`](../validation/2026-09-15-measurement-method.md)).
- **`_created` gauges.** `prometheus_client` automatically adds a
  `<name>_created` gauge alongside every Counter once it is first used
  with a given label combination (OpenMetrics compatibility). These are
  not separately instrumented and are not listed in the inventory above.
- **Enum and Info metrics are exposed as ordinary gauges on the wire.**
  `gateway_security_mode`/`cloud_security_mode` expose one time series
  per possible state (value `1` for the active state, `0` for the
  others); `gateway_build_info`/`cloud_build_info` expose a single
  series with value `1` and the metadata as labels. This is standard
  `prometheus_client` behaviour for `Enum`/`Info`, confirmed directly
  against this project's dependency-pinned version (see the WP5
  verification transcript for the exact `generate_latest` output).
- **`gateway_security_mode`/`cloud_security_mode` default to `off`
  (the first state listed) at import, before anything calls
  `.state(...)`.** Confirmed empirically: a fresh import shows
  `gateway_security_mode{gateway_security_mode="off"} 1.0` with no
  other code involved. If the crypto integration never calls
  `GATEWAY_SECURITY_MODE.state(mode)` (and its cloud-side equivalent)
  at startup and on every mode change, this metric will silently keep
  reporting `off` even while the service is actually configured and
  running as `enabled` or `required` — a metric that quietly lies is
  worse than no metric at all here, so wiring this call is not
  optional cosmetic instrumentation.
