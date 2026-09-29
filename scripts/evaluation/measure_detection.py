#!/usr/bin/env python3
"""Measure how fast, and how accurately, Prometheus shows injected faults.

Issue #4 metric "Detection time and accuracy". Against a running Compose
stack that includes the monitoring overlay, this script:

1. watches a quiet baseline period and records any signal (false signals);
2. injects faults with ``docker compose`` and polls Prometheus once per
   second until each signal appears:

   - ``cloud-outage``: ``stop cloud`` for ``--outage-seconds``, then
     ``start cloud``;
   - ``auth-failure``: recreate the gateway with a wrong ``ML_KEM_PSK``
     (``--wrong-psk-file``), keep it for ``--outage-seconds``, stop the
     device, wait ``--settle-seconds`` so the last failure counts are
     scraped before the gateway process is replaced, then recreate the
     gateway with the right key and start the device again;
   - ``gateway-down``: ``stop gateway`` for ``--outage-seconds``, then
     ``start gateway``;

3. after each trial, compares the counter increases stored in Prometheus
   with the events counted in the container logs.

Signals: ``up == 0`` per job, any change of a failure counter since the
injection, and alerts reported by ``/api/v1/alerts`` (only present when
the Prometheus under test loads alert rules; the repository ships none).

The script only runs ``docker compose`` with the ``--project`` and ``-f``
files it is given. It never runs ``up``/``down`` on the whole project.

Usage (see docs/validation/2026-09-29-detection-time.md for the override
files used in the recorded run)::

    python3 scripts/evaluation/measure_detection.py \\
        --project m4detect \\
        -f docker-compose.yml -f monitoring/docker-compose.monitoring.yml \\
        -f /path/to/override.yml --wrong-psk-file /path/to/wrong-psk.yml \\
        --prometheus http://127.0.0.1:29090 \\
        --gateway-url http://127.0.0.1:28000 --cloud-url http://127.0.0.1:28001 \\
        --out /path/to/result.json

Requires Python 3.9+ and ``requests``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time

import requests

COUNTER_NAMES = (
    "cloud_forward_failures_total",
    "gateway_delivery_outcome_total",
    "gateway_cloud_retries_exhausted_total",
    "gateway_handshake_failed_total",
    "gateway_session_rekeys_total",
    "cloud_handshake_failed_total",
    "cloud_crypto_decrypt_failures_total",
    "device_messages_total",
    "cloud_readings_stored_total",
)

# A change in any of these is a "signal" that something is wrong.
FAILURE_SERIES = (
    "cloud_forward_failures_total",
    'gateway_delivery_outcome_total{outcome="failed_after_retries"}',
    'gateway_delivery_outcome_total{outcome="rejected_validation"}',
    "gateway_cloud_retries_exhausted_total",
    "gateway_handshake_failed_total",
    "cloud_handshake_failed_total",
    "cloud_crypto_decrypt_failures_total",
)

SELECTOR = '{__name__=~"up|%s"}' % "|".join(COUNTER_NAMES)

DROP_LABELS = {"__name__", "instance", "service"}


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="milliseconds")


def key_of(metric: dict) -> str:
    labels = ",".join(
        f'{k}="{v}"' for k, v in sorted(metric.items()) if k not in DROP_LABELS
    )
    return f"{metric['__name__']}{{{labels}}}"


def is_failure_key(key: str) -> bool:
    for sel in FAILURE_SERIES:
        name, _, rest = sel.partition("{")
        if not key.startswith(name + "{"):
            continue
        if not rest or rest.rstrip("}") in key:
            return True
    return False


class Prom:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def query(self, expr: str, at: float | None = None):
        params = {"query": expr}
        if at is not None:
            params["time"] = f"{at:.3f}"
        r = requests.get(f"{self.base}/api/v1/query", params=params, timeout=10)
        r.raise_for_status()
        return r.json()["data"]

    def latest(self) -> dict:
        """Latest raw sample (timestamp, value) of every watched series."""
        out = {}
        for s in self.query(f"{SELECTOR}[40s]")["result"]:
            ts, val = s["values"][-1]
            out[key_of(s["metric"])] = (float(ts), float(val))
        return out

    def alerts(self) -> dict:
        r = requests.get(f"{self.base}/api/v1/alerts", timeout=10)
        r.raise_for_status()
        return {
            a["labels"]["alertname"]: (a["state"], a.get("activeAt"))
            for a in r.json()["data"]["alerts"]
        }

    def increases(self, start: float, end: float) -> dict:
        """Counter increase over [start, end] from raw samples, handling resets.

        A series whose first sample lies inside the window counts its first
        value (it did not exist before). No extrapolation, unlike increase().
        """
        # Reach 40 s (more than two scrape intervals) before the window so the
        # last pre-window sample is included as the starting value.
        window = int(end - start) + 41
        out = {}
        for s in self.query(f"{SELECTOR}[{window}s]", at=end)["result"]:
            key = key_of(s["metric"])
            if key.startswith("up{"):
                continue
            vals = [(float(t), float(v)) for t, v in s["values"]]
            before = [v for t, v in vals if t < start]
            inside = [v for t, v in vals if t >= start]
            prev = before[-1] if before else 0.0
            total = 0.0
            for v in inside:
                total += v - prev if v >= prev else v
                prev = v
            out[key] = total
        return out


class Stack:
    def __init__(self, project: str, files: list[str], wrong_psk_file: str):
        self.base = ["docker", "compose", "-p", project]
        for f in files:
            self.base += ["-f", f]
        self.wrong = self.base + ["-f", wrong_psk_file]

    def run(self, *args: str, wrong_psk: bool = False) -> None:
        cmd = (self.wrong if wrong_psk else self.base) + list(args)
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def logs(self, service: str, since: float, until: float) -> list[str]:
        cmd = self.base + [
            "logs", "--no-log-prefix", "--timestamps",
            "--since", iso(since), "--until", iso(until), service,
        ]
        p = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return (p.stdout + p.stderr).splitlines()


def wait_healthy(url: str, limit: float = 60.0) -> float:
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=1).status_code == 200:
                return time.time()
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{url}/health not healthy within {limit}s")


class Watcher:
    """Polls Prometheus and records the first appearance of each signal."""

    def __init__(self, prom: Prom, poll: float):
        self.prom = prom
        self.poll = poll
        self.events: list[dict] = []
        self.state: dict[str, tuple] = {}

    def watch(self, until: float, since: float, ref: dict, tag: str) -> None:
        # State persists across calls with the same tag, so a trial's
        # injection, settle and recovery phases form one timeline.
        seen_up0, seen_counter, alert_state = self.state.setdefault(tag, (set(), set(), {}))
        while time.time() < until:
            t_poll = time.time()
            try:
                latest = self.prom.latest()
                alerts = self.prom.alerts()
            except requests.RequestException as exc:
                self.events.append({"tag": tag, "kind": "prom_error", "t": t_poll, "detail": str(exc)})
                time.sleep(self.poll)
                continue
            for key, (ts, val) in latest.items():
                if ts < since:
                    continue
                if key.startswith("up{"):
                    if val == 0 and key not in seen_up0:
                        seen_up0.add(key)
                        self.events.append({"tag": tag, "kind": "up0", "series": key, "t": t_poll, "sample_ts": ts})
                    elif val == 1 and key in seen_up0:
                        seen_up0.discard(key)
                        self.events.append({"tag": tag, "kind": "up1", "series": key, "t": t_poll, "sample_ts": ts})
                elif is_failure_key(key) and key not in seen_counter:
                    pre = ref.get(key, (0.0, 0.0))[1]
                    if val != pre and val > 0:
                        seen_counter.add(key)
                        self.events.append({"tag": tag, "kind": "counter", "series": key, "t": t_poll,
                                            "sample_ts": ts, "value": val, "pre": pre})
            for name, (state, active_at) in alerts.items():
                if alert_state.get(name) != state:
                    alert_state[name] = state
                    self.events.append({"tag": tag, "kind": f"alert_{state}", "series": name,
                                        "t": t_poll, "active_at": active_at})
            for name in [n for n in alert_state if n not in alerts]:
                del alert_state[name]
                self.events.append({"tag": tag, "kind": "alert_resolved", "series": name, "t": t_poll})
            time.sleep(max(0.0, self.poll - (time.time() - t_poll)))


def count(lines: list[str], pattern: str) -> int:
    rx = re.compile(pattern)
    return sum(1 for line in lines if rx.search(line))


def ground_truth(stack: Stack, start: float, end: float) -> dict:
    dev = stack.logs("device", start, end)
    gw = stack.logs("gateway", start, end)
    cl = stack.logs("cloud", start, end)
    return {
        "device_delivered_200": count(dev, r"Delivered reading .*status_code=200"),
        "device_rejected_502": count(dev, r"Gateway rejected reading .*status_code=502"),
        "device_rejected_other": count(dev, r"Gateway rejected reading .*status_code=(?!502)"),
        "device_failed_to_deliver": count(dev, r"Failed to deliver reading"),
        "gateway_received": count(gw, r"Received data from device"),
        "gateway_forward_errors": count(gw, r"(Failed|Unexpected error) (to forward|forwarding) data to cloud"),
        "cloud_handshake_401": count(cl, r'POST /secure/handshake HTTP/1\.1" 401'),
    }


def trial(kind: str, n: int, stack: Stack, prom: Prom, w: Watcher, a) -> dict:
    tag = f"{kind}-{n}"
    print(f"[{iso(time.time())}] {tag}: start", flush=True)
    ref = prom.latest()
    rec: dict = {"tag": tag, "kind": kind}
    rec["t_cmd"] = time.time()
    if kind == "cloud-outage":
        stack.run("stop", "cloud")
        rec["t_inject"] = time.time()
    elif kind == "gateway-down":
        stack.run("stop", "gateway")
        rec["t_inject"] = time.time()
    elif kind == "auth-failure":
        stack.run("up", "-d", "--no-deps", "gateway", wrong_psk=True)
        rec["t_inject"] = wait_healthy(a.gateway_url)
    t0 = rec["t_inject"]
    w.watch(t0 + a.outage_seconds, rec["t_cmd"], ref, tag)
    if kind == "auth-failure":
        stack.run("stop", "device")
        rec["t_device_stopped"] = time.time()
        w.watch(time.time() + a.settle_seconds, rec["t_cmd"], ref, tag)
    rec["t_restore_cmd"] = time.time()
    if kind == "cloud-outage":
        stack.run("start", "cloud")
        rec["t_recovered"] = wait_healthy(a.cloud_url)
    elif kind == "gateway-down":
        stack.run("start", "gateway")
        rec["t_recovered"] = wait_healthy(a.gateway_url)
    else:
        stack.run("up", "-d", "--no-deps", "gateway")
        rec["t_recovered"] = wait_healthy(a.gateway_url)
        stack.run("start", "device")
    w.watch(rec["t_recovered"] + a.recovery_seconds, rec["t_cmd"], ref, tag)
    rec["t_end"] = time.time()
    injected_end = rec.get("t_device_stopped", rec["t_restore_cmd"])
    rec["truth_injected"] = ground_truth(stack, rec["t_cmd"], injected_end)
    rec["truth_recovery"] = ground_truth(stack, injected_end, rec["t_end"])
    rec["metric_increase"] = {k: v for k, v in prom.increases(rec["t_cmd"], rec["t_end"]).items() if v}
    rec["events"] = [e for e in w.events if e["tag"] == tag]
    for e in rec["events"]:
        e["dt_poll"] = round(e["t"] - t0, 2)
        if "sample_ts" in e:
            e["dt_sample"] = round(e["sample_ts"] - t0, 2)
    print(json.dumps({k: rec[k] for k in ("truth_injected", "metric_increase")}), flush=True)
    return rec


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project", required=True)
    p.add_argument("-f", "--file", action="append", required=True, dest="files")
    p.add_argument("--wrong-psk-file", required=True)
    p.add_argument("--prometheus", default="http://127.0.0.1:29090")
    p.add_argument("--gateway-url", default="http://127.0.0.1:28000")
    p.add_argument("--cloud-url", default="http://127.0.0.1:28001")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--kinds", default="cloud-outage,auth-failure,gateway-down")
    p.add_argument("--baseline-seconds", type=float, default=300)
    p.add_argument("--outage-seconds", type=float, default=90)
    p.add_argument("--settle-seconds", type=float, default=20)
    p.add_argument("--recovery-seconds", type=float, default=150)
    p.add_argument("--poll-seconds", type=float, default=1.0)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    prom = Prom(a.prometheus)
    stack = Stack(a.project, a.files, a.wrong_psk_file)
    w = Watcher(prom, a.poll_seconds)
    t = time.time()
    offset = float(prom.query("time()")["result"][0]) - (t + time.time()) / 2
    result = {"started": iso(t), "prometheus_minus_host_seconds": round(offset, 4),
              "args": vars(a), "trials": []}

    b0 = time.time()
    print(f"[{iso(b0)}] baseline {a.baseline_seconds}s", flush=True)
    ref = prom.latest()
    w.watch(b0 + a.baseline_seconds, b0, ref, "baseline")
    b1 = time.time()
    result["baseline"] = {
        "t_start": b0, "t_end": b1,
        "events": [e for e in w.events if e["tag"] == "baseline"],
        "truth": ground_truth(stack, b0, b1),
        "metric_increase": {k: v for k, v in prom.increases(b0, b1).items() if v},
    }

    for kind in a.kinds.split(","):
        for n in range(1, a.trials + 1):
            result["trials"].append(trial(kind, n, stack, prom, w, a))
            with open(a.out, "w") as fh:
                json.dump(result, fh, indent=1)

    with open(a.out, "w") as fh:
        json.dump(result, fh, indent=1)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
