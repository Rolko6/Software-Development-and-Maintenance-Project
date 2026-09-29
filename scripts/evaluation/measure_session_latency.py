#!/usr/bin/env python3
"""Measure POST /device-data latency, split by ML-KEM session state.

Issue #4 metric "Response latency": median and p95 request-to-acknowledgement
time, with requests that establish a new gateway->cloud session separated from
requests that reuse an existing one, and failures reported separately.

What is timed
-------------
The same quantity as ``scripts/baseline/measure_latency.py`` and
``scripts/evaluation/compare_latency.py``: one bare ``requests.post(...)`` to
``{gateway}/device-data`` (no ``requests.Session``, so a fresh TCP connection
per request), timed with ``time.perf_counter()`` (monotonic) from just before
the call to just after the response body has been read. The acknowledgement is
the gateway's HTTP response, which it returns only after the cloud has answered.

How each request is classified
------------------------------
The gateway's Prometheus endpoint ``{gateway}/metrics/`` is scraped before and
after every timed request, outside the timed window. The deltas of
``gateway_handshake_succeeded_total``, ``gateway_handshake_started_total``,
``gateway_handshake_failed_total`` and ``gateway_session_rekeys_total`` decide
the class:

- ``off``: the gateway reports ``gateway_security_mode`` ``off``;
- ``new_session``: at least one handshake succeeded during the request;
- ``reused_session``: no handshake started during the request;
- ``handshake_failed``: a handshake started but none succeeded.

A request whose status is not 200, or that raised, is a failure. Failures are
kept out of the latency statistics and counted per class and status code.

Forcing new sessions
--------------------
The script does not configure the stack. New sessions come either from the
stack's configuration (a cloud ``CLOUD_ML_KEM_SESSION_TTL_SECONDS`` of 15 or
less makes the gateway rekey before every request, because its rekey skew is
15 s) or from ``--force cloud-restart``, which restarts the Compose project's
cloud container before every timed request with ``docker restart`` and waits
for ``{cloud}/health``. The gateway then learns from a 404 that its session is
unknown and handshakes again, so that path also includes one rejected
``POST /secure/data``.

Statistics are reported in milliseconds: count, min, median, p95
(nearest rank, as in the existing scripts) and max. Raw samples are written to
``--json-out``.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

COUNTER_RE = re.compile(
    r"^(gateway_handshake_started_total|gateway_handshake_succeeded_total"
    r"|gateway_handshake_failed_total|gateway_session_rekeys_total)"
    r"(\{[^}]*\})?\s+([0-9.eE+-]+)$"
)
MODE_RE = re.compile(r'^gateway_security_mode\{gateway_security_mode="(\w+)"\}\s+1\.0$')


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure POST /device-data latency split into new-session, "
        "reused-session and off-mode requests."
    )
    parser.add_argument(
        "--gateway-url", default="http://127.0.0.1:48000", help="Gateway base URL"
    )
    parser.add_argument(
        "--cloud-url", default="http://127.0.0.1:48001", help="Cloud base URL"
    )
    parser.add_argument(
        "--compose-project",
        required=True,
        help="Compose project name of the stack under test; used to find the cloud "
        "container for --force cloud-restart and recorded in the output",
    )
    parser.add_argument(
        "--label", required=True, help="Name of this phase, recorded in the output"
    )
    parser.add_argument(
        "--samples", type=int, default=200, help="Timed requests (default 200)"
    )
    parser.add_argument(
        "--warmup", type=int, default=5, help="Untimed requests first (default 5)"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Per-request timeout, seconds"
    )
    parser.add_argument(
        "--force",
        choices=("none", "cloud-restart"),
        default="none",
        help="cloud-restart: restart the cloud container before every timed request",
    )
    parser.add_argument("--device-id", default="latency-session-001")
    parser.add_argument(
        "--json-out", type=Path, required=True, help="Raw samples and summary (JSON)"
    )
    return parser.parse_args(argv)


def scrape(gateway_url: str, timeout: float) -> tuple[dict, str | None]:
    text = requests.get(f"{gateway_url}/metrics/", timeout=timeout).text
    counters: dict[str, float] = {}
    mode = None
    for line in text.splitlines():
        match = COUNTER_RE.match(line)
        if match:
            counters[match.group(1) + (match.group(2) or "")] = float(match.group(3))
            continue
        match = MODE_RE.match(line)
        if match:
            mode = match.group(1)
    return counters, mode


def deltas(before: dict, after: dict) -> dict:
    keys = set(before) | set(after)
    return {
        k: after.get(k, 0.0) - before.get(k, 0.0)
        for k in sorted(keys)
        if after.get(k, 0.0) != before.get(k, 0.0)
    }


def classify(mode: str | None, delta: dict) -> str:
    if mode == "off":
        return "off"
    succeeded = delta.get("gateway_handshake_succeeded_total", 0.0)
    started = delta.get("gateway_handshake_started_total", 0.0)
    if succeeded >= 1:
        return "new_session"
    if started >= 1:
        return "handshake_failed"
    return "reused_session"


def cloud_container(project: str) -> str:
    out = subprocess.run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=cloud",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if len(out) != 1:
        raise SystemExit(
            f"expected one cloud container in project {project!r}, found {len(out)}"
        )
    return out[0]


def restart_cloud(container: str, cloud_url: str) -> None:
    subprocess.run(["docker", "restart", container], check=True, capture_output=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{cloud_url}/health", timeout=1).status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.2)
    raise SystemExit("cloud did not become healthy within 60 s after restart")


def post_reading(
    url: str, device_id: str, timeout: float
) -> tuple[float, int | None, str | None]:
    body = {"device_id": device_id, "temperature": round(random.uniform(15.0, 30.0), 2)}
    start = time.perf_counter()
    try:
        response = requests.post(url, json=body, timeout=timeout)
        _ = response.content
        status, error = response.status_code, None
    except requests.exceptions.RequestException as exc:
        status, error = None, type(exc).__name__
    return (time.perf_counter() - start) * 1000.0, status, error


def percentile(ordered: list[float], pct: float) -> float:
    rank = min(max(math.ceil(pct / 100.0 * len(ordered)), 1), len(ordered))
    return ordered[rank - 1]


def summarise(samples: list[dict]) -> dict:
    summary: dict[str, dict] = {}
    for cls in sorted({s["class"] for s in samples}):
        members = [s for s in samples if s["class"] == cls]
        ok = sorted(s["ms"] for s in members if s["status"] == 200)
        failed = sorted(s["ms"] for s in members if s["status"] != 200)
        failures: dict[str, int] = {}
        for s in members:
            if s["status"] != 200:
                key = str(s["status"]) if s["status"] is not None else s["error"]
                failures[key] = failures.get(key, 0) + 1
        summary[cls] = {
            "ok": len(ok),
            "failures": failures,
            "failure_median_ms": round(statistics.median(failed), 3)
            if failed
            else None,
            "failure_max_ms": round(failed[-1], 3) if failed else None,
            "min_ms": round(ok[0], 3) if ok else None,
            "median_ms": round(statistics.median(ok), 3) if ok else None,
            "p95_ms": round(percentile(ok, 95), 3) if ok else None,
            "max_ms": round(ok[-1], 3) if ok else None,
        }
    return summary


def main(argv=None) -> int:
    args = parse_args(argv)
    gateway = args.gateway_url.rstrip("/")
    cloud = args.cloud_url.rstrip("/")
    url = f"{gateway}/device-data"
    container = (
        cloud_container(args.compose_project) if args.force == "cloud-restart" else None
    )

    for _ in range(args.warmup):
        post_reading(url, f"{args.device_id}-warmup", args.timeout)

    samples = []
    modes_seen = set()
    for index in range(args.samples):
        if container:
            restart_cloud(container, cloud)
        before, mode_before = scrape(gateway, args.timeout)
        ms, status, error = post_reading(url, args.device_id, args.timeout)
        after, mode_after = scrape(gateway, args.timeout)
        modes_seen.update(m for m in (mode_before, mode_after) if m)
        delta = deltas(before, after)
        samples.append(
            {
                "i": index,
                "ms": round(ms, 3),
                "status": status,
                "error": error,
                "class": classify(mode_after, delta),
                "delta": delta,
            }
        )

    summary = summarise(samples)
    print(
        f"phase={args.label} project={args.compose_project} force={args.force} gateway_mode={sorted(modes_seen)}"
    )
    columns = ("min_ms", "median_ms", "p95_ms", "max_ms")
    print(
        f"{'class':<18}{'ok':>5}" + "".join(f"{c:>11}" for c in columns) + "  failures"
    )
    for cls, row in summary.items():
        values = [row[c] if row[c] is not None else float("nan") for c in columns]
        print(
            f"{cls:<18}{row['ok']:>5}"
            + "".join(f"{v:>11.3f}" for v in values)
            + f"  {row['failures'] or '-'}"
        )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "config": {
            "label": args.label,
            "gateway_url": gateway,
            "cloud_url": cloud,
            "compose_project": args.compose_project,
            "samples": args.samples,
            "warmup": args.warmup,
            "timeout_s": args.timeout,
            "force": args.force,
            "gateway_security_mode": sorted(modes_seen),
        },
        "summary": summary,
        "samples": samples,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=1) + "\n")
    print(f"Wrote {args.json_out}")
    return 0 if samples else 1


if __name__ == "__main__":
    sys.exit(main())
