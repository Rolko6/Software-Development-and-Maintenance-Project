#!/usr/bin/env python3
"""V3 equivalents of PR #14's latency, delivery, recovery and detection runs.

V3 encapsulates every reading; there are no reusable ML-KEM sessions. Metrics
are validated before measurement, and raw samples identify failures explicitly.
Outage scenarios require a named, local Compose stack and an interruption flag.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from urllib.parse import urlparse
import uuid

import requests
from prometheus_client.parser import text_string_to_metric_families


class MeasurementError(RuntimeError):
    pass


def metric_values(text: str, required: tuple[str, ...]) -> dict[str, float]:
    """Aggregate labelled counters; an uninitialized labelled family is zero."""
    values: dict[str, float] = {}
    try:
        for family in text_string_to_metric_families(text):
            if family.type == "counter":
                name = family.name + "_total"
                values[name] = sum(s.value for s in family.samples if s.name == name)
    except (ValueError, TypeError) as error:
        raise MeasurementError("response is not valid Prometheus counter data") from error
    missing = set(required) - values.keys()
    if missing:
        raise MeasurementError(f"required v3 counters absent: {sorted(missing)}")
    if any(not math.isfinite(v) or v < 0 for v in values.values()):
        raise MeasurementError("counter value is negative or non-finite")
    return {name: values[name] for name in required}


def increase(before: dict, after: dict, name: str) -> float:
    if name not in before or name not in after:
        raise MeasurementError(f"missing counter {name}")
    change = after[name] - before[name]
    if change < 0:
        raise MeasurementError(f"{name} reset during measurement")
    return change


def latency_summary(records: list[dict]) -> dict:
    ok = sorted(r["latency_ms"] for r in records if r["status"] == 200)
    failures = Counter(str(r["status"]) if r["status"] is not None else r["error"]
                       for r in records if r["status"] != 200)
    return {
        "successful": len(ok), "failures": dict(failures),
        "median_ms": statistics.median(ok) if ok else None,
        "p95_ms": ok[math.ceil(0.95 * len(ok)) - 1] if ok else None,
        "min_ms": min(ok) if ok else None, "max_ms": max(ok) if ok else None,
    }


def delivery_counts(records: list[dict], final: Counter, before_stop: Counter) -> dict:
    sent = {r["device_id"] for r in records}
    acked = {r["device_id"] for r in records if r["status"] == 200}
    failed = sent - acked
    final = Counter({k: v for k, v in final.items() if k in sent})
    before_stop = Counter({k: v for k, v in before_stop.items() if k in sent})
    observed = set(final) | set(before_stop)
    return {
        "sent": len(records), "acknowledged": len(acked), "not_acknowledged": len(failed),
        "stored_final_unique": len(final), "stored_observed_unique": len(observed),
        "missing_final": len(sent - set(final)), "never_observed": len(sent - observed),
        "lost_across_restart": len(set(before_stop) - set(final)),
        "duplicate_records_final": sum(max(v - 1, 0) for v in final.values()),
        "duplicate_records_before_stop": sum(max(v - 1, 0) for v in before_stop.values()),
        "acknowledged_never_observed": len(acked - observed),
        "failed_but_observed": len(failed & observed),
    }


class Stack:
    def __init__(self, gateway: str, cloud: str, timeout: float = 5,
                 project: str | None = None, files: list[str] | None = None):
        self.gateway, self.cloud = gateway.rstrip("/"), cloud.rstrip("/")
        self.timeout, self.project = timeout, project
        self.files = files or [str(Path(__file__).resolve().parents[2] / "docker-compose.yml")]

    def metrics(self, service: str, *required: str) -> dict:
        url = self.gateway if service == "gateway" else self.cloud
        response = requests.get(url + "/metrics/", timeout=self.timeout)
        response.raise_for_status()
        return metric_values(response.text, required)

    def send(self, device_id: str, temperature: float = 20.0) -> dict:
        start = time.monotonic()
        try:
            response = requests.post(self.gateway + "/device-data",
                                     json={"device_id": device_id, "temperature": temperature},
                                     timeout=self.timeout)
            status, error = response.status_code, None
        except requests.exceptions.RequestException as exc:
            status, error = None, type(exc).__name__
        return {"device_id": device_id, "status": status, "error": error,
                "latency_ms": (time.monotonic() - start) * 1000,
                "sent_at": datetime.now(timezone.utc).isoformat()}

    def stored(self) -> Counter:
        response = requests.get(self.cloud + "/data", timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or any(not isinstance(r, dict) or
                not isinstance(r.get("device_id"), str) for r in data):
            raise MeasurementError("cloud /data is not a list of readings")
        return Counter(r["device_id"] for r in data)

    def healthy(self, service: str) -> bool:
        url = self.gateway if service == "gateway" else self.cloud
        try:
            response = requests.get(url + "/health", timeout=min(self.timeout, 0.5))
            return response.status_code == 200 and response.json() == {"status": "healthy"}
        except (requests.exceptions.RequestException, ValueError):
            return False

    def wait_healthy(self, service: str, ceiling: float = 30) -> None:
        deadline = time.monotonic() + ceiling
        while time.monotonic() < deadline:
            if self.healthy(service):
                return
            time.sleep(0.1)
        raise MeasurementError(f"{service} did not become healthy within {ceiling}s")

    def compose(self, *args: str) -> list[str]:
        if not self.project:
            raise MeasurementError("interruption requires --project")
        cmd = ["docker", "compose", "-p", self.project]
        for path in self.files:
            cmd.extend(["-f", path])
        return cmd + list(args)

    def verify_control_target(self) -> None:
        """Ensure URL ports belong to this project before stopping any container."""
        for service, url in [("gateway", self.gateway), ("cloud", self.cloud)]:
            parsed = urlparse(url)
            if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
                raise MeasurementError("interruption only supports local HTTP URLs")
            ids = subprocess.check_output(self.compose("ps", "-q", service), text=True).split()
            if len(ids) != 1:
                raise MeasurementError(f"expected one running {service} in project {self.project}")
            info = json.loads(subprocess.check_output(["docker", "inspect", ids[0]], text=True))[0]
            if info["Config"]["Labels"].get("com.docker.compose.project") != self.project:
                raise MeasurementError("container project label mismatch")
            port = "8000/tcp" if service == "gateway" else "8001/tcp"
            bindings = info["NetworkSettings"]["Ports"].get(port) or []
            if str(parsed.port or 80) not in {b["HostPort"] for b in bindings}:
                raise MeasurementError(f"{service} URL does not match project port bindings")

    def control(self, action: str, service: str) -> None:
        subprocess.run(self.compose(action, service), check=True, capture_output=True, timeout=60)


def latency(stack: Stack, count: int) -> dict:
    records = []
    prefix = "v3-latency-" + uuid.uuid4().hex
    for n in range(count):
        before = stack.metrics("cloud", "secure_data_received_total")
        record = stack.send(f"{prefix}-{n}")
        after = stack.metrics("cloud", "secure_data_received_total")
        change = increase(before, after, "secure_data_received_total")
        record["secure_receipts"] = change
        record["path"] = "mlkem_per_reading" if record["status"] == 200 else "failed"
        if record["status"] == 200 and change != 1:
            raise MeasurementError("secure receipt delta is not one; isolate traffic/check v3 path")
        records.append(record)
    return {"scenario": "latency", "records": records, "summary": latency_summary(records),
            "timing": "gateway request-to-response; metric scrapes excluded; fresh HTTP connection",
            "security_model": "per-reading encapsulation, no reusable sessions"}


def delivery(stack: Stack, count: int, outage: bool = False, observe: float = 0.2) -> dict:
    records, before_stop = [], Counter()
    prefix = "v3-delivery-" + uuid.uuid4().hex
    stopped = False
    stop_at, start_at = count // 3, 2 * count // 3
    outage_times = {}
    try:
        for n in range(count):
            if outage and n == stop_at:
                before_stop = stack.stored()
                outage_times["stop_issued_at"] = datetime.now(timezone.utc).isoformat()
                stopped = True
                stack.control("stop", "cloud")
            if outage and n == start_at:
                outage_times["start_issued_at"] = datetime.now(timezone.utc).isoformat()
                stack.control("start", "cloud")
                stopped = False
                stack.wait_healthy("cloud")
            records.append(stack.send(f"{prefix}-{n}"))
    finally:
        if stopped:
            stack.control("start", "cloud")
            stack.wait_healthy("cloud")
    time.sleep(observe)
    return {"scenario": "outage-delivery" if outage else "delivery", "records": records,
            "summary": delivery_counts(records, stack.stored(), before_stop),
            "outage": outage_times, "observation_seconds": observe,
            "outage_definition": "stop after first third; restart after second third" if outage else None}


def recovery(stack: Stack, ceiling: float = 30) -> dict:
    marker = "v3-recovery-" + uuid.uuid4().hex
    if stack.send(marker)["status"] != 200 or not stack.stored()[marker]:
        raise MeasurementError("pre-restart marker was not stored")
    start = time.monotonic()
    stack.control("restart", "cloud")
    command_seconds = time.monotonic() - start
    deadline = start + ceiling
    records = []
    while time.monotonic() < deadline:
        reading = stack.send(marker + f"-{len(records)}")
        records.append(reading)
        if reading["status"] == 200:
            stored = stack.stored()
            if stored[reading["device_id"]]:
                return {"scenario": "recovery", "recovery_seconds": time.monotonic() - start,
                        "restart_command_seconds": command_seconds, "records": records,
                        "marker_retained": bool(stored[marker]), "operator_intervention_needed": False,
                        "timing": "restart command issued to first observed stored new reading; sends begin after command completes"}
        time.sleep(0.1)
    raise MeasurementError("cloud did not recover within the observation ceiling")


def detection(stack: Stack, kind: str, ceiling: float = 10, poll: float = 0.1) -> dict:
    targets = {"cloud-outage": ("gateway", "cloud_forward_failures_total"),
               "sensor-sentinel": ("gateway", "sensor_fault_readings_total"),
               "invalid-envelope": ("cloud", "secure_data_rejected_total")}
    stopped = None
    if kind != "gateway-outage":
        service, counter = targets[kind]
        before = stack.metrics(service, counter)
    start = time.monotonic()
    record = None
    try:
        if kind == "cloud-outage":
            stopped = "cloud"
            stack.control("stop", "cloud")
            record = stack.send("v3-detection-" + uuid.uuid4().hex)
            if record["status"] != 502:
                raise MeasurementError("cloud outage did not produce expected gateway 502")
        elif kind == "gateway-outage":
            stopped = "gateway"
            stack.control("stop", "gateway")
        elif kind == "sensor-sentinel":
            record = stack.send("v3-sentinel-" + uuid.uuid4().hex, 85.0)
            if record["status"] != 200:
                raise MeasurementError("sentinel reading was not forwarded")
        else:
            response = requests.post(stack.cloud + "/data/secure",
                json={"kem_ciphertext": "AA==", "nonce": "AA==", "ciphertext": "AA=="},
                timeout=stack.timeout)
            if response.status_code != 400:
                raise MeasurementError("invalid envelope did not produce expected cloud 400")
            record = {"status": response.status_code}
        while time.monotonic() - start < ceiling:
            change = None
            if kind == "gateway-outage":
                seen = not stack.healthy("gateway")
            else:
                change = increase(before, stack.metrics(service, counter), counter)
                seen = change >= 1
            if seen:
                return {"scenario": "detection", "fault": kind,
                        "detection_seconds": time.monotonic() - start,
                        "signal": "health_poll" if kind == "gateway-outage" else counter,
                        "counter_increase": change, "injection_response": record,
                        "poll_seconds": poll,
                        "timing": "injection initiated to first direct poll observation; includes command/request time",
                        "alerting": "direct API/metrics polling; no Prometheus alert deployment"}
            time.sleep(poll)
        raise MeasurementError(f"{kind} was not observed within {ceiling}s")
    finally:
        if stopped:
            stack.control("start", stopped)
            stack.wait_healthy(stopped)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("scenario", choices=["latency", "delivery", "outage-delivery", "recovery", "detection"])
    p.add_argument("--gateway-url", required=True)
    p.add_argument("--cloud-url", required=True)
    p.add_argument("--samples", type=int, default=30)
    p.add_argument("--timeout", type=float, default=5)
    p.add_argument("--project")
    p.add_argument("-f", "--compose-file", action="append")
    p.add_argument("--allow-interruption", action="store_true")
    p.add_argument("--fault", choices=["cloud-outage", "gateway-outage", "sensor-sentinel", "invalid-envelope"], default="cloud-outage")
    p.add_argument("--json-out", type=Path, required=True)
    args = p.parse_args(argv)
    if args.samples < 3 or args.timeout <= 0 or not math.isfinite(args.timeout):
        p.error("samples must be at least 3 and timeout must be finite and positive")
    interrupts = args.scenario in ["outage-delivery", "recovery"] or (
        args.scenario == "detection" and args.fault in ["cloud-outage", "gateway-outage"])
    if interrupts and (not args.project or not args.allow_interruption):
        p.error("this scenario requires --project and --allow-interruption")
    stack = Stack(args.gateway_url, args.cloud_url, args.timeout, args.project, args.compose_file)
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "config": vars(args) | {"json_out": str(args.json_out)}}
    try:
        if interrupts:
            stack.verify_control_target()
        stack.wait_healthy("cloud")
        stack.wait_healthy("gateway")
        if args.scenario == "latency":
            result = latency(stack, args.samples)
        elif args.scenario in ["delivery", "outage-delivery"]:
            result = delivery(stack, args.samples, args.scenario == "outage-delivery")
        elif args.scenario == "recovery":
            result = recovery(stack)
        else:
            result = detection(stack, args.fault)
        output["result"] = result
        code = int(bool(result.get("summary", {}).get("failures")))
    except (MeasurementError, requests.exceptions.RequestException, subprocess.SubprocessError, ValueError) as error:
        output["error"] = str(error)
        code = 1
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output.get("result", {"error": output.get("error")})))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
