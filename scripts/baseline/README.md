# Baseline scripts

Local (non-Docker) baseline for the device → gateway → cloud prototype. See
[docs/validation/2026-09-15-baseline.md](../../docs/validation/2026-09-15-baseline.md)
for the recorded run, exact environment, and caveats.

## `run_baseline.sh`

Starts `cloud` and `gateway` locally with uvicorn from the repo's `.venv`,
on ports **18001** (cloud) and **18000** (gateway) — deliberately not
8000/8001, so it never collides with the Compose deployment or another
concurrent run. It then runs the functional checks from the README's manual
checks section (health, a known reading, `GET /data`, invalid device id,
cloud-down/recovery), runs `measure_latency.py`, and always tears its
processes down on exit (including on failure or Ctrl-C).

```sh
scripts/baseline/run_baseline.sh
```

Extra arguments are forwarded to `measure_latency.py`, e.g.:

```sh
scripts/baseline/run_baseline.sh --samples 200 --warmup 10
```

Exit code is non-zero if any functional check or the latency measurement
fails. Safe to re-run repeatedly; each run starts and tears down its own
processes and does not depend on state left by a previous run (other than
overwriting `last-baseline.json`).

Requirements: the shared `.venv/` at the repo root (already provisioned),
`curl`, and a POSIX shell. Does not require Docker.

## `measure_latency.py`

Measures request latency, in milliseconds, of:

- `POST /device-data` on the gateway (full device → gateway → cloud path), and
- `POST /data` on the cloud directly (isolates the gateway → cloud leg).

Run standalone against already-running services:

```sh
.venv/bin/python scripts/baseline/measure_latency.py \
  --gateway-host 127.0.0.1 --gateway-port 18000 \
  --cloud-host 127.0.0.1 --cloud-port 18001 \
  --samples 50 --warmup 5
```

All options also accept environment variables (`GATEWAY_HOST`,
`GATEWAY_PORT`, `CLOUD_HOST`, `CLOUD_PORT`, `BASELINE_SAMPLES`,
`BASELINE_WARMUP`, `BASELINE_TIMEOUT`, `BASELINE_DEVICE_ID`). Prints a
plain-text table (count, min, mean, median, p95, max, failures) and writes
machine-readable JSON to `--json-out` (default: `last-baseline.json` next to
this script). See the module docstring for exactly what is timed, sample
counts, warm-up handling, and what is excluded (loopback only, sequential,
no container/network overhead, cold start excluded).

`last-baseline.json` is overwritten on every run; it is not hand-maintained.
