# Evaluation method: plaintext vs. secured latency — 2026-09-15

> **Superseded in part.** The Docker daemon was unavailable while this record was produced and was started later the same day, so the container checks listed here as not run were executed. See the [integration record](2026-09-15-integration.md).

Scope: Work Package 5's comparison requirement ("baseline and secured
measurements use comparable conditions"). This record defines the
method and states, explicitly, what has and has not actually been run.
It does not report a plaintext-vs-secured result — see "Not yet
executed" below for why, and the exact commands that will produce one
once the prerequisites land.

Tooling: [`scripts/evaluation/compare_latency.py`](../../scripts/evaluation/compare_latency.py),
authored under this work package. A related but distinct tool,
[`scripts/baseline/measure_latency.py`](../../scripts/baseline/measure_latency.py),
belongs to the baseline/testing work package and measures the
*current* (plaintext-only) system once; `compare_latency.py` measures
two or more named modes *against each other* in one invocation and
reports the delta directly.

## How comparability is achieved

`compare_latency.py` applies identical measurement logic to every mode
it measures in a single invocation, so the following are held fixed by
construction across phases:

- **Same host.** All phases run from the same machine, in the same
  process, in the same script invocation.
- **Same sample count and warm-up.** `--samples` and `--warmup` apply
  identically to every mode; there is no way to give one mode more
  samples than another in one run.
- **Same payload shape.** Every request uses `make_reading()`: a fixed
  `device_id` prefix and a `temperature` drawn from the same `[15, 30]`
  range the real device simulator uses (see `device/app/`) — the
  value differs per request (to avoid sending byte-identical payloads),
  but its shape and range never differ between modes.
- **Same Python, same timing method.** One interpreter process runs
  the entire comparison; every phase is timed the same way (bare
  `requests.post(...)`, `time.perf_counter()` around send-to-response,
  no connection reuse across samples — deliberately mirroring
  `scripts/baseline/measure_latency.py`'s method, and how the device
  simulator (`device/app/`) / `gateway/app/cloud_client.py` make
  requests in the real application).
- **Exactly one variable changed, if the operator follows the
  single-URL path.** With `--url` (one URL reused across phases), the
  only thing that is supposed to differ between phases is the target's
  security mode — the script pauses (`--interactive`, on by default)
  and asks the operator to confirm the switch before continuing, so the
  measured phases do not silently blur together.

**What the harness cannot enforce by itself:** if the operator instead
uses the `--target mode=url` dual-instance path (two already-running
targets, one per mode, so no restart/pause is needed), the harness has
no way to confirm those two target processes are otherwise identical.
Before trusting that comparison, the operator must confirm both targets
are: the same code revision, the same Python interpreter, the same host,
started the same way (both bare `uvicorn` from `.venv`, or both the same
Compose image), and differ *only* in configured security mode. Record
whichever path was used, and how, in `--mode-switch-method` — it is
carried into the JSON output for exactly this reason.

## Remaining confounds (present even when the method above is followed correctly)

1. **Pure-Python ML-KEM.** The selected library (`kyber-py`, per
   `.venv`'s pinned dependencies) is a pure-Python implementation, not a
   native/optimized one. Any measured "cost of security" here is the
   cost of *this* implementation choice, not of ML-KEM in general — a
   native implementation would very likely show a smaller gap. This
   confound cannot be removed by measurement method; only reported.
2. **Loopback only.** All measurement in this repository — baseline and
   this harness alike — runs over `127.0.0.1`, never a real network.
   Loopback affects both a plaintext and a secured run equally, so it
   should not *bias* a same-conditions delta, but it does mean neither
   run's absolute numbers generalize to a real deployment with real
   network latency and packet loss.
3. **Local uvicorn vs. containerized deployment.** This sandbox has no
   running Docker daemon (see "Not yet executed"), so any measurement
   actually taken here runs services locally with bare `uvicorn` from
   `.venv` (as `scripts/baseline/run_baseline.sh` already does, on
   ports 18000/18001), not inside the Compose containers the project
   actually ships. Container networking (even loopback-adjacent, on one
   host) adds overhead bare loopback does not have. **Both modes being
   compared must use the same deployment shape** — comparing a
   locally-run "off" phase against a containerized "enabled" phase (or
   vice versa) would confound the deployment-shape difference with the
   security-mode difference and produce a meaningless delta.
4. **Python 3.13 (local `.venv`) vs. Python 3.12 (container images).**
   `gateway/Dockerfile` and `cloud/Dockerfile` both pin
   `python:3.12-slim`; the shared `.venv` at the repo root runs
   3.13.12. A comparison run locally (the only kind possible in this
   sandbox) is implicitly a Python-3.13 result and should be labelled
   as such — it is not necessarily representative of the Python-3.12
   containers this project actually deploys.
5. **No sustained or concurrent load.** Every measurement tool in this
   repository (`scripts/baseline/measure_latency.py` and
   `scripts/evaluation/compare_latency.py` alike) sends one request at
   a time, sequentially. Neither tells us how the *marginal* cost of a
   handshake or AEAD seal/open behaves under concurrent connections or
   sustained throughput — plausibly where a pure-Python crypto
   implementation's cost matters most (CPU contention with other
   in-flight requests), and exactly what is not measured here.

## How many samples are needed

- **Mean/median:** loopback latencies observed so far in this project
  are low-variance (the existing plaintext baseline shows a sub-3ms
  spread across 50 samples — see "Reference data" below), so 30–50
  samples is normally enough for a stable mean/median estimate of a
  single mode under those conditions.
- **p95:** the nearest-rank p95 used by both harnesses here picks the
  `ceil(0.95 * n)`-th smallest sample. At `n=20` that is the 19th of 20
  values — one sample away from the maximum, and highly sensitive to a
  single slow outlier. At `n=50` (both harnesses' default) it is the
  48th of 50 — still fairly close to the tail. **A minimum of 100
  samples per mode is recommended** before treating a p95 delta as
  meaningful (`--samples 100`); more (200+) gives a visibly steadier
  p95 run-to-run, at the cost of a longer measurement window.
- **Effect size matters more than sample count here.** A pure-Python
  ML-KEM handshake is very likely to add latency far larger than this
  system's plaintext-baseline noise floor (low single-digit
  milliseconds, see "Reference data"). If the true effect is that
  large, even 30–50 samples per mode will show it unambiguously; the
  100+ recommendation is for defensibly reporting *how much* slower,
  not for detecting *whether* it is slower at all.
- **Repeat the run.** A single invocation of `compare_latency.py`, even
  at 100+ samples, is still one run on one machine at one moment. For a
  claim intended for the final report, run the comparison at least
  twice (ideally on different occasions) and check the two deltas agree
  in direction and rough magnitude before citing a single number.

## Reference data (already recorded, by a different work package — not a plaintext-vs-secured comparison)

[`scripts/baseline/last-baseline.json`](../../scripts/baseline/last-baseline.json),
authored and owned by the baseline/testing work package, records a
plaintext-only run of `POST /device-data` (`n=50`, `warmup=5`, local
`.venv` Python 3.13.12, macOS, loopback, `uvicorn` on ports
18000/18001): mean ≈2.38ms, median ≈2.34ms, p95 ≈2.73ms, max ≈3.62ms,
zero failures, generated 2026-09-15. This is cited here only as context
for "how many samples are needed" above (it shows the actual noise
floor this project's loopback measurements currently have) — it is
**not** a plaintext-vs-secured comparison, was not produced by this
work package's tooling, and may be superseded by a later run; do not
treat it as authoritative without checking that file's current content
and its own validation record.

## Not yet executed

The actual plaintext-vs-secured comparison this document exists to
define has **not been run**, for two independent reasons, both
structural rather than incidental:

1. **No secured mode to measure yet.** At the time of writing, the
   ML-KEM integration (`gateway/app/crypto/`, `cloud/app/crypto/`, the
   handshake endpoint, and the mode switch) was still being implemented
   by a concurrent work package. There is no `enabled`/`required` mode
   to point `compare_latency.py` at until that work lands, and no
   documented mechanism yet for how an operator actually switches the
   mode between phases (`--mode-switch-method` exists specifically to
   record whatever that mechanism turns out to be).
2. **No Docker daemon in this environment.** A container-based
   comparison (matching the project's actual Python 3.12 / Compose
   deployment shape, confound 3 above) cannot be attempted here: **not
   run, reason: Docker daemon unavailable.**

What *was* run, for the avoidance of doubt, was a smoke test of the
harness's own mechanics — argument parsing, the interactive-pause and
dual-target code paths, statistics computation, and JSON output —
against two throwaway local HTTP servers standing in for a gateway (one
with an artificial 5ms delay to produce a nonzero, checkable delta).
That confirmed the tool works; it is not a measurement of this system
and none of its numbers describe gateway or ML-KEM behaviour.

### Exact commands to fill in the placeholders, once available

Local (bare `uvicorn`, matching this sandbox's only available
deployment shape — see confound 3, label results accordingly):

```sh
# Same target, mode switched between phases (uses whatever mechanism
# the crypto work package documents — fill in --mode-switch-method):
.venv/bin/python scripts/evaluation/compare_latency.py \
  --url http://127.0.0.1:18000/device-data \
  --modes off enabled \
  --samples 100 --warmup 10 \
  --mode-switch-method "<describe the actual mechanism here>" \
  --json-out scripts/evaluation/last-comparison.json
```

```sh
# All three modes, if two extra already-running instances are easier
# to arrange than switching one instance three times:
.venv/bin/python scripts/evaluation/compare_latency.py \
  --target off=http://127.0.0.1:18000/device-data \
  --target enabled=http://127.0.0.1:18002/device-data \
  --target required=http://127.0.0.1:18003/device-data \
  --modes off enabled required \
  --samples 100 --warmup 10 --no-interactive \
  --mode-switch-method "three separate uvicorn instances, one per mode, otherwise identical" \
  --json-out scripts/evaluation/last-comparison.json
```

Containerized (once Docker is available — matches the actual deployment
shape, removes confound 3 but not confounds 1, 2, 4, or 5):

```sh
docker compose up --build -d
.venv/bin/python scripts/evaluation/compare_latency.py \
  --url http://localhost:8000/device-data \
  --modes off enabled \
  --samples 100 --warmup 10 \
  --mode-switch-method "<describe the actual mechanism here>" \
  --json-out scripts/evaluation/last-comparison.json
```

**PLACEHOLDER — result table (fill in from the JSON `results`/`deltas_vs_reference`
produced by whichever command above is actually run; do not hand-type
numbers here that the tool did not produce):**

| Mode | count | min (ms) | mean (ms) | median (ms) | p95 (ms) | max (ms) | Δ mean vs. `off` | Δ p95 vs. `off` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| off | — | — | — | — | — | — | — | — |
| enabled | — | — | — | — | — | — | — | — |
| required *(optional)* | — | — | — | — | — | — | — | — |

## Not run (this document)

- The plaintext-vs-secured comparison itself (see "Not yet executed").
- Any container-based measurement (Docker daemon unavailable in this
  environment).
- Any measurement under concurrent/sustained load (no such harness
  exists in this repository — see confound 5).
- A live Prometheus/Grafana-based cross-check of the same comparison
  (would additionally require the mode to change while a single
  Prometheus instance keeps scraping — see
  [`docs/operations/monitoring.md`](../operations/monitoring.md),
  "Cardinality and retention caveats").
