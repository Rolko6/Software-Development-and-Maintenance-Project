#!/usr/bin/env python3
"""Measure end-to-end HTTP latency for the device -> gateway -> cloud baseline.

What is timed
-------------
Wall-clock latency observed by this script, from just before an HTTP POST is
sent (``time.perf_counter()``) to just after the response body has been
fully read. Each request is issued with a bare ``requests.post(...)`` call
(no ``requests.Session``, so no connection pooling / keep-alive reuse across
requests) -- this deliberately mirrors how ``device/app/`` and
``gateway/app/cloud_client.py`` make requests in the real application, so
the measured overhead includes a fresh TCP connection per request, just as
production traffic would.

Two request shapes are measured
--------------------------------
1. ``device_data``: ``POST {gateway}/device-data`` -- the full path a real
   reading takes: device -> gateway (validates) -> cloud (stores),
   synchronously, before the gateway responds.
2. ``cloud_data``: ``POST {cloud}/data`` -- sent by *this script* directly
   to the cloud service, bypassing the gateway, to isolate the cost of the
   gateway -> cloud leg that is embedded inside (1).

Caveat: ``cloud_data`` is measured from this script acting as the client,
not from inside the running gateway process. ``device_data - cloud_data``
is therefore only an *approximation* of "gateway-added overhead + one extra
hop" -- the two measurements do not share a client process, and the
gateway's own outbound request to the cloud may behave slightly differently
under its own event loop / connection setup than this script's.

Method
------
For each request shape: ``--warmup`` requests are sent first and discarded
(letting CPython, the OS TCP stack, and any lazy imports settle), then
``--samples`` requests are sent sequentially -- one in flight at a time, no
concurrency -- and timed individually. A request that raises a
``requests.exceptions.RequestException`` (timeout, connection error, etc.)
counts as a *failure* and is excluded from the latency statistics; a
non-2xx HTTP response is NOT a failure here -- it is still a fully timed,
valid observation of the server's response latency.

Reported statistics, in milliseconds: count of successful samples, min,
mean, median, p95 (nearest-rank method), max, plus the failure count.

Excluded from scope (see the validation record for the full list)
-------------------------------------------------------------------
- Concurrent or sustained load -- this is strictly sequential, single
  in-flight request at a time.
- Any network path other than loopback (127.0.0.1) -- no real network,
  no container networking.
- Server cold start -- servers are assumed to already be running and past
  their first request before measurement begins.
- Growth of the cloud's in-memory list over the run (every sample and
  warm-up call adds one more stored reading; later GETs of /data would be
  proportionally slower, but /data retrieval itself is not measured here).

Exit status
-----------
Exits 1 (after printing and writing results) if any target had zero
successful samples, or if any target recorded one or more transport-level
failures. On loopback against a healthy local server, a transport failure
is anomalous, not expected noise, so it is treated as a check failure
rather than silently tolerated.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_JSON_OUT = Path(__file__).resolve().parent / "last-baseline.json"


def env_default(name: str, default, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure baseline latency of POST /device-data and POST /data.",
    )
    parser.add_argument(
        "--gateway-host",
        default=env_default("GATEWAY_HOST", "127.0.0.1"),
        help="Gateway host (env GATEWAY_HOST, default 127.0.0.1)",
    )
    parser.add_argument(
        "--gateway-port",
        type=int,
        default=env_default("GATEWAY_PORT", 18000, int),
        help="Gateway port (env GATEWAY_PORT, default 18000)",
    )
    parser.add_argument(
        "--cloud-host",
        default=env_default("CLOUD_HOST", "127.0.0.1"),
        help="Cloud host (env CLOUD_HOST, default 127.0.0.1)",
    )
    parser.add_argument(
        "--cloud-port",
        type=int,
        default=env_default("CLOUD_PORT", 18001, int),
        help="Cloud port (env CLOUD_PORT, default 18001)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=env_default("BASELINE_SAMPLES", 50, int),
        help="Number of timed samples per target (env BASELINE_SAMPLES, default 50)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=env_default("BASELINE_WARMUP", 5, int),
        help="Number of untimed warm-up requests per target (env BASELINE_WARMUP, default 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_default("BASELINE_TIMEOUT", 5.0, float),
        help="Per-request timeout in seconds (env BASELINE_TIMEOUT, default 5.0)",
    )
    parser.add_argument(
        "--device-id",
        default=env_default("BASELINE_DEVICE_ID", "latency-baseline-001"),
        help="device_id used in synthetic readings (default latency-baseline-001)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help=f"Path to write machine-readable JSON results (default {DEFAULT_JSON_OUT})",
    )
    return parser.parse_args(argv)


def percentile(ordered_values, pct: float):
    n = len(ordered_values)
    if n == 0:
        return None
    if n == 1:
        return ordered_values[0]
    rank = math.ceil(pct / 100.0 * n)
    rank = min(max(rank, 1), n)
    return ordered_values[rank - 1]


def compute_stats(latencies_ms):
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
    }


def make_reading(device_id: str) -> dict:
    # Fixed shape matching SensorData in both services; temperature varies
    # only to avoid sending byte-identical payloads on every call.
    import random

    return {
        "device_id": device_id,
        "temperature": round(random.uniform(15.0, 30.0), 2),
    }


def run_target(url: str, device_id: str, count: int, timeout: float):
    latencies = []
    failures = 0
    for _ in range(count):
        body = make_reading(device_id)
        start = time.perf_counter()
        try:
            response = requests.post(url, json=body, timeout=timeout)
            _ = response.content  # force full body read before stopping the clock
        except requests.exceptions.RequestException:
            failures += 1
            continue
        latencies.append((time.perf_counter() - start) * 1000.0)
    return latencies, failures


def format_table(rows) -> str:
    header = f"{'target':<14}{'count':>7}{'min_ms':>10}{'mean_ms':>10}{'median_ms':>11}{'p95_ms':>10}{'max_ms':>10}{'failures':>10}"
    lines = [header, "-" * len(header)]
    for row in rows:
        stats = row["stats"] or {}
        lines.append(
            f"{row['name']:<14}"
            f"{stats.get('count', 0):>7}"
            f"{stats.get('min_ms', float('nan')):>10.3f}"
            f"{stats.get('mean_ms', float('nan')):>10.3f}"
            f"{stats.get('median_ms', float('nan')):>11.3f}"
            f"{stats.get('p95_ms', float('nan')):>10.3f}"
            f"{stats.get('max_ms', float('nan')):>10.3f}"
            f"{row['failures']:>10}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)

    gateway_url = f"http://{args.gateway_host}:{args.gateway_port}/device-data"
    cloud_url = f"http://{args.cloud_host}:{args.cloud_port}/data"

    print(
        "Baseline latency measurement\n"
        f"  gateway target: POST {gateway_url}\n"
        f"  cloud target:   POST {cloud_url}\n"
        f"  warmup={args.warmup} samples={args.samples} timeout={args.timeout}s\n"
    )

    targets = [
        ("device_data", gateway_url),
        ("cloud_data", cloud_url),
    ]

    results = {}
    rows = []
    any_zero_success = False
    any_failures = False

    for name, url in targets:
        if args.warmup > 0:
            run_target(url, f"{args.device_id}-warmup", args.warmup, args.timeout)

        latencies, failures = run_target(url, args.device_id, args.samples, args.timeout)
        stats = compute_stats(latencies)

        if stats is None:
            any_zero_success = True
        if failures > 0:
            any_failures = True

        results[name] = {
            "url": url,
            "samples_requested": args.samples,
            "warmup": args.warmup,
            "failures": failures,
            "stats_ms": stats,
        }
        rows.append({"name": name, "stats": stats, "failures": failures})

    print(format_table(rows))
    print()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "config": {
            "gateway_url": gateway_url,
            "cloud_url": cloud_url,
            "samples": args.samples,
            "warmup": args.warmup,
            "timeout_s": args.timeout,
            "device_id": args.device_id,
        },
        "results": results,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote JSON results to {args.json_out}")

    if any_zero_success:
        print("FAIL: at least one target had zero successful samples.", file=sys.stderr)
        return 1
    if any_failures:
        print(
            "FAIL: at least one target recorded transport-level failures on loopback.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
