#!/usr/bin/env python3
"""Measure cloud recovery time and reading delivery, loss and duplication.

Implements two metrics from issue #4 against a running Compose stack:

* ``restart`` / ``stopstart``: recovery time from a cloud restart (or from the
  ``start`` command after a stop with a gap) to the first reading that the
  gateway acknowledges with HTTP 200 *and* that is present in the cloud's
  ``GET /data``. A marker reading stored before the restart must be absent
  at that point, which proves the in-memory store was really wiped and the
  reading was not accepted by the old process.
* ``normal`` / ``outage``: send a known set of uniquely named readings through
  the gateway, then count unique stored readings, missing readings and extra
  duplicate records. ``outage`` stops the cloud for a fixed window while
  sending continues. Because cloud storage is in memory, a ``GET /data``
  snapshot is taken immediately before the stop (with sending paused), so
  readings wiped by the stop are separated from readings lost in transit.

Each reading has ``device_id = m4-<label>-<trial>-<seq>`` and a fixed
temperature of 20.0, so it is identifiable in ``GET /data``. Stop any device
container first so only these readings reach the cloud, and keep each trial
well below ``CLOUD_MAX_STORED_READINGS`` (every delivery trial starts with a
``restart cloud``, which empties the store).

Run from the repository root, for example:

    python scripts/evaluation/measure_recovery_delivery.py \\
        --gateway-url http://127.0.0.1:38000 --cloud-url http://127.0.0.1:38001 \\
        --project m4deliver -f docker-compose.yml -f /path/to/override.yml \\
        --scenario restart --trials 5 --json-out /tmp/restart.json

Needs only the standard library, ``requests`` and the ``docker compose`` CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import requests

TEMPERATURE = 20.0
ACCESS_LINE_RE = re.compile(r'"(GET|POST) (/\S*) HTTP/1\.1" (\d{3})')
COUNTERS = (
    'gateway_handshake_succeeded_total',
    'gateway_handshake_started_total',
    'gateway_session_rekeys_total{reason="forced"}',
    'gateway_session_rekeys_total{reason="expired"}',
    'gateway_delivery_outcome_total{outcome="forwarded"}',
    'gateway_delivery_outcome_total{outcome="failed_after_retries"}',
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Stack:
    def __init__(self, args: argparse.Namespace) -> None:
        self.gateway = args.gateway_url.rstrip("/")
        self.cloud = args.cloud_url.rstrip("/")
        self.compose = ["docker", "compose", "-p", args.project]
        for path in args.compose_file:
            self.compose += ["-f", path]
        self.http = requests.Session()

    # -- Compose -------------------------------------------------------

    def compose_cmd(self, *cmd: str) -> list[str]:
        return [*self.compose, *cmd]

    def run(self, *cmd: str) -> float:
        started = time.monotonic()
        subprocess.run(self.compose_cmd(*cmd), check=True, capture_output=True)
        return time.monotonic() - started

    def cloud_status_counts(self, since: str) -> dict[str, int]:
        """Count cloud access-log lines per 'METHOD path status' since a time."""
        result = subprocess.run(
            self.compose_cmd("logs", "--no-color", "--since", since, "cloud"),
            check=True,
            capture_output=True,
            text=True,
        )
        counts: Counter[str] = Counter()
        for match in ACCESS_LINE_RE.finditer(result.stdout):
            method, path, status = match.groups()
            if path.startswith(("/data", "/secure/")):
                counts[f"{method} {path} {status}"] += 1
        return dict(sorted(counts.items()))

    # -- HTTP ----------------------------------------------------------

    def send(self, device_id: str, timeout: float = 30.0) -> dict:
        started = time.monotonic()
        record = {"device_id": device_id, "sent_at": utc_now()}
        try:
            response = requests.post(
                f"{self.gateway}/device-data",
                json={"device_id": device_id, "temperature": TEMPERATURE},
                timeout=timeout,
            )
            record["status"] = response.status_code
        except requests.exceptions.RequestException as error:
            record["status"] = f"client-{type(error).__name__}"
        record["latency_s"] = round(time.monotonic() - started, 4)
        record["_mono"] = started
        return record

    def stored_ids(self, timeout: float = 5.0) -> Counter[str] | None:
        try:
            response = self.http.get(f"{self.cloud}/data", timeout=timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            return None
        return Counter(item.get("device_id") for item in response.json())

    def cloud_healthy(self) -> bool:
        try:
            response = requests.get(f"{self.cloud}/health", timeout=0.3)
        except requests.exceptions.RequestException:
            return False
        return response.status_code == 200

    def counters(self) -> dict[str, float]:
        try:
            text = self.http.get(f"{self.gateway}/metrics/", timeout=5).text
        except requests.exceptions.RequestException:
            return {}
        values = {}
        for line in text.splitlines():
            name, _, value = line.rpartition(" ")
            if name in COUNTERS:
                values[name] = float(value)
        return values

    def wait_delivered(self, device_id: str, ceiling: float = 60.0) -> bool:
        deadline = time.monotonic() + ceiling
        while time.monotonic() < deadline:
            if self.send(device_id)["status"] == 200:
                stored = self.stored_ids()
                if stored and stored[device_id]:
                    return True
            time.sleep(0.5)
        return False


def delta(before: dict, after: dict) -> dict:
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in COUNTERS
        if after.get(key, 0) - before.get(key, 0)
    }


def strip(records: list[dict], origin: float) -> list[dict]:
    out = []
    for record in records:
        record = dict(record)
        record["t_rel_s"] = round(record.pop("_mono") - origin, 3)
        out.append(record)
    return out


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


# -- Recovery ------------------------------------------------------------


def recovery_trial(stack: Stack, args: argparse.Namespace, trial: int) -> dict:
    prefix = f"m4-{args.label}-{trial}"
    marker = f"{prefix}-marker"
    if not stack.wait_delivered(marker):
        raise SystemExit(f"trial {trial}: marker reading was not delivered")

    counters_before = stack.counters()
    log_since = utc_now()
    result: dict = {"trial": trial, "scenario": args.scenario, "started_at": log_since}
    records: list[dict] = []
    seq = 0

    def send_one() -> dict:
        nonlocal seq
        seq += 1
        record = stack.send(f"{prefix}-{seq:04d}")
        records.append(record)
        return record

    if args.scenario == "stopstart":
        stop_mono = time.monotonic()
        result["stop_issued_at"] = utc_now()
        result["stop_cmd_s"] = round(stack.run("stop", "cloud"), 3)
        while time.monotonic() - stop_mono < args.gap:
            send_one()
            time.sleep(args.interval)
        command = "start"
    else:
        stop_mono = None
        command = "restart"

    result["command"] = f"docker compose {command} cloud"
    result["cmd_issued_at"] = utc_now()
    t0 = time.monotonic()
    proc = subprocess.Popen(
        stack.compose_cmd(command, "cloud"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if stop_mono is not None:
        result["gap_s"] = round(t0 - stop_mono, 3)

    # Background watchers, so neither the blocking sender nor an early exit
    # from the loop distorts the command duration or the health timeline.
    timeline: dict[str, float] = {}
    finished = threading.Event()

    def wait_command() -> None:
        proc.wait()
        timeline["cmd_done"] = time.monotonic() - t0

    def watch_health() -> None:
        seen_down = command == "start"
        while not finished.is_set():
            healthy = stack.cloud_healthy()
            now = time.monotonic() - t0
            if not healthy and not seen_down:
                seen_down = True
                timeline["health_down"] = now
            elif healthy and seen_down and "health_up" not in timeline:
                timeline["health_up"] = now
            time.sleep(0.05)

    watchers = [
        threading.Thread(target=wait_command, daemon=True),
        threading.Thread(target=watch_health, daemon=True),
    ]
    for watcher in watchers:
        watcher.start()

    recovered = None
    false_early = 0
    next_tick = t0
    while time.monotonic() - t0 < args.ceiling:
        record = send_one()
        if record["status"] == 200:
            stored = stack.stored_ids()
            if stored is not None and stored[record["device_id"]]:
                if stored[marker]:
                    false_early += 1
                else:
                    recovered = time.monotonic() - t0
                    result["first_stored_device_id"] = record["device_id"]
                    result["first_stored_sent_s"] = round(record["_mono"] - t0, 3)
                    result["first_stored_latency_s"] = record["latency_s"]
                    break
        next_tick += args.interval
        time.sleep(max(0.0, next_tick - time.monotonic()))
    watchers[0].join()
    time.sleep(0.5)
    finished.set()
    watchers[1].join()

    time.sleep(1.0)
    result.update(
        {
            "cmd_duration_s": round(timeline["cmd_done"], 3),
            "health_down_s": _round(timeline.get("health_down")),
            "health_up_s": _round(timeline.get("health_up")),
            "recovery_s": None if recovered is None else round(recovered, 3),
            "operator_intervention_needed": recovered is None,
            "acked_but_old_process": false_early,
            "sends": len(records),
            "statuses": dict(Counter(str(r["status"]) for r in records)),
            "gateway_counter_delta": delta(counters_before, stack.counters()),
            "cloud_access_log": stack.cloud_status_counts(log_since),
            "records": strip(records, t0),
        }
    )
    return result


# -- Delivery ------------------------------------------------------------


def delivery_trial(stack: Stack, args: argparse.Namespace, trial: int) -> dict:
    prefix = f"m4-{args.label}-{trial}-"
    stack.run("restart", "cloud")
    if not stack.wait_delivered(f"m4-{args.label}-{trial}warm"):
        raise SystemExit(f"trial {trial}: warm-up reading was not delivered")

    counters_before = stack.counters()
    log_since = utc_now()
    result: dict = {"trial": trial, "scenario": args.scenario, "started_at": log_since}
    records: list[dict] = []
    send_lock = threading.Lock()
    outage: dict = {}
    t0 = time.monotonic()

    def controller() -> None:
        time.sleep(max(0.0, args.outage_at - (time.monotonic() - t0)))
        with send_lock:
            snapshot = stack.stored_ids()
            outage["snapshot_at"] = utc_now()
            outage["stop_issued_s"] = round(time.monotonic() - t0, 3)
            outage["stop_cmd_s"] = round(stack.run("stop", "cloud"), 3)
        outage["snapshot"] = snapshot
        stop_done = time.monotonic()
        time.sleep(max(0.0, args.outage_seconds - (stop_done - t0 - outage["stop_issued_s"])))
        outage["start_issued_s"] = round(time.monotonic() - t0, 3)
        outage["start_cmd_s"] = round(stack.run("start", "cloud"), 3)

    thread = None
    if args.scenario == "outage":
        thread = threading.Thread(target=controller, daemon=True)
        thread.start()

    next_tick = t0
    for seq in range(1, args.count + 1):
        with send_lock:
            records.append(stack.send(f"{prefix}{seq:04d}"))
        next_tick += args.interval
        time.sleep(max(0.0, next_tick - time.monotonic()))
    sending_s = time.monotonic() - t0
    if thread is not None:
        thread.join()

    time.sleep(args.observe_seconds)
    final = stack.stored_ids()
    if final is None:
        raise SystemExit(f"trial {trial}: GET /data failed after the observation period")

    sent = [r["device_id"] for r in records]
    acked = {r["device_id"] for r in records if r["status"] == 200}
    failed = {r["device_id"] for r in records if r["status"] != 200}

    def ours(counter: Counter[str] | None) -> Counter[str]:
        return Counter({k: v for k, v in (counter or {}).items() if k.startswith(prefix)})

    final_ours = ours(final)
    pre_ours = ours(outage.get("snapshot"))
    union = set(final_ours) | set(pre_ours)
    wiped = {d for d in pre_ours if d not in final_ours}

    result.update(
        {
            "sent": len(sent),
            "sending_duration_s": round(sending_s, 2),
            "statuses": dict(Counter(str(r["status"]) for r in records)),
            "acked_200": len(acked),
            "not_acked": len(failed),
            "stored_final_unique": len(final_ours),
            "stored_final_records": sum(final_ours.values()),
            "duplicate_records_final": sum(v - 1 for v in final_ours.values()),
            "stored_pre_outage_unique": len(pre_ours),
            "duplicate_records_pre_outage": sum(v - 1 for v in pre_ours.values()),
            "stored_ever_unique": len(union),
            "wiped_by_stop": len(wiped),
            "missing_final": len(set(sent) - set(final_ours)),
            "missing_ever": len(set(sent) - union),
            "acked_never_stored": len(acked - union),
            "failed_but_stored": len(failed & union),
            "stored_not_sent": len(union - set(sent)),
            "gateway_counter_delta": delta(counters_before, stack.counters()),
            "cloud_access_log": stack.cloud_status_counts(log_since),
            "records": strip(records, t0),
        }
    )
    if outage:
        outage.pop("snapshot")
        result["outage"] = outage
        stop_s, start_s = outage["stop_issued_s"], outage["start_issued_s"]
        in_window = [r for r in result["records"] if stop_s <= r["t_rel_s"] < start_s]
        result["sent_during_outage"] = len(in_window)
        result["acked_during_outage"] = sum(r["status"] == 200 for r in in_window)
    return result


# -- Reporting -----------------------------------------------------------


def summarise(results: list[dict], scenario: str) -> dict:
    if scenario in ("restart", "stopstart"):
        values = [r["recovery_s"] for r in results if r["recovery_s"] is not None]
        summary = {"trials": len(results), "recovered": len(values)}
        if values:
            summary.update(
                median_s=round(statistics.median(values), 3),
                min_s=min(values),
                max_s=max(values),
            )
        return summary
    keys = (
        "sent", "acked_200", "not_acked", "stored_final_unique", "missing_final",
        "missing_ever", "duplicate_records_final", "wiped_by_stop",
        "acked_never_stored", "failed_but_stored",
    )
    return {key: sum(r[key] for r in results) for key in keys}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--cloud-url", required=True)
    parser.add_argument("--project", required=True, help="Compose project name (-p)")
    parser.add_argument(
        "-f", "--compose-file", action="append", default=[],
        help="Compose file, repeatable; defaults to docker-compose.yml",
    )
    parser.add_argument(
        "--scenario", required=True, choices=("restart", "stopstart", "normal", "outage"),
    )
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--label", default=None, help="Reading ID label; defaults to the scenario")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between sends")
    parser.add_argument("--ceiling", type=float, default=60.0, help="Recovery give-up time")
    parser.add_argument("--gap", type=float, default=5.0, help="stopstart: seconds stopped")
    parser.add_argument("--count", type=int, default=200, help="Delivery: readings per trial")
    parser.add_argument("--outage-at", type=float, default=10.0)
    parser.add_argument("--outage-seconds", type=float, default=15.0)
    parser.add_argument("--observe-seconds", type=float, default=5.0)
    parser.add_argument("--json-out", help="Write every trial, with per-send records, here")
    args = parser.parse_args(argv)
    args.compose_file = args.compose_file or ["docker-compose.yml"]
    args.label = args.label or args.scenario

    stack = Stack(args)
    trial_fn = recovery_trial if args.scenario in ("restart", "stopstart") else delivery_trial
    results = []
    for trial in range(1, args.trials + 1):
        result = trial_fn(stack, args, trial)
        results.append(result)
        brief = {k: v for k, v in result.items() if k != "records"}
        print(json.dumps(brief), flush=True)

    summary = summarise(results, args.scenario)
    print(json.dumps({"summary": summary}), flush=True)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump({"args": vars(args), "summary": summary, "trials": results}, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
