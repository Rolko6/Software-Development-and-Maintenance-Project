#!/usr/bin/env python3
"""Build an isolated v3 stack and exercise PR #6/#13/#14's useful checks.

Only the generated Compose project is started/stopped. No device simulator,
shared ports, or production project is used. Save results before cleaning up.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import requests

from measure_v3 import Stack, MeasurementError, latency, delivery, recovery, detection

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MeasurementError(message)


def published_url(container: str, target: int) -> str:
    data = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    bindings = data["NetworkSettings"]["Ports"][f"{target}/tcp"]
    require(len(bindings) == 1, "expected one loopback port binding")
    require(bindings[0]["HostIp"] == "127.0.0.1", "port is not restricted to loopback")
    return "http://127.0.0.1:" + bindings[0]["HostPort"]


def run(stack: Stack, count: int, output: dict) -> None:
    stack.wait_healthy("cloud")
    stack.wait_healthy("gateway")
    stack.verify_control_target()
    gateway_before = stack.metrics("gateway", "cloud_forward_failures_total", "sensor_fault_readings_total")
    cloud_before = stack.metrics("cloud", "secure_data_rejected_total", "secure_data_received_total")
    time.sleep(0.25)
    gateway_after = stack.metrics("gateway", "cloud_forward_failures_total", "sensor_fault_readings_total")
    cloud_after = stack.metrics("cloud", "secure_data_rejected_total", "secure_data_received_total")
    require(gateway_before == gateway_after and cloud_before == cloud_after,
            "unexpected traffic during isolated no-fault observation")
    output["baseline"] = {"seconds": 0.25, "fault_counter_increases": 0,
                          "limit": "short direct-poll observation, not an alert false-positive rate study"}

    invalid = requests.post(stack.gateway + "/device-data",
                            json={"device_id": ""}, timeout=stack.timeout)
    require(invalid.status_code == 422, "gateway accepted a malformed reading")
    output["checks"].append({"invalid_reading_status": invalid.status_code})

    results = output["results"]
    result = latency(stack, count)
    results.append(result)
    require(result["summary"]["successful"] == count and not result["summary"]["failures"],
            "not every latency reading reached secure cloud ingestion")

    result = delivery(stack, count)
    results.append(result)
    require(result["summary"]["missing_final"] == 0 and
            result["summary"]["duplicate_records_final"] == 0 and
            result["summary"]["not_acknowledged"] == 0,
            "normal delivery lost, duplicated or rejected a reading")

    result = delivery(stack, count, outage=True)
    results.append(result)
    summary = result["summary"]
    require(summary["not_acknowledged"] > 0 and summary["never_observed"] > 0,
            "outage did not exercise failed deliveries")
    require(summary["acknowledged_never_observed"] == 0 and
            summary["duplicate_records_final"] == 0 and
            summary["failed_but_observed"] == 0,
            "delivery acknowledgements disagree with storage snapshots")
    require(all(r["status"] in [200, 502] for r in result["records"]),
            "outage returned an unexpected failure")

    results.append(recovery(stack))
    require(not results[-1]["operator_intervention_needed"], "cloud did not recover within ceiling")
    require(results[-1]["marker_retained"], "committed reading disappeared across cloud restart")
    for fault in ["sensor-sentinel", "invalid-envelope", "cloud-outage", "gateway-outage"]:
        results.append(detection(stack, fault))

    # The restored stack must still deliver through the protected path.
    results.append(latency(stack, 3))
    require(results[-1]["summary"]["successful"] == 3, "stack did not recover after fault checks")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", type=int, default=30)
    p.add_argument("--json-out", type=Path, required=True)
    args = p.parse_args(argv)
    if args.samples < 3:
        p.error("samples must be at least 3")
    project = "v3-eval-" + uuid.uuid4().hex[:12]
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "project": project,
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
              "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
              "samples_per_batch": args.samples, "checks": [], "results": []}
    code = 0
    with tempfile.TemporaryDirectory(prefix="v3-evaluation-") as directory:
        config = json.loads(subprocess.check_output(
            ["docker", "compose", "-p", project, "-f", str(ROOT / "docker-compose.yml"),
             "config", "--format", "json"], cwd=ROOT,
            env=dict(os.environ, CLOUD_ALLOW_LEGACY_INGESTION="false"), text=True))
        config["services"] = {s: config["services"][s] for s in ["gateway", "cloud"]}
        # Select free loopback ports once. A Docker-assigned port (published=0)
        # can change on stop/start, invalidating the measurement's endpoint.
        with socket.socket() as gateway_socket, socket.socket() as cloud_socket:
            gateway_socket.bind(("127.0.0.1", 0))
            cloud_socket.bind(("127.0.0.1", 0))
            ports = {"gateway": gateway_socket.getsockname()[1], "cloud": cloud_socket.getsockname()[1]}
        for service, target in [("gateway", 8000), ("cloud", 8001)]:
            config["services"][service]["ports"] = [
                {"target": target, "published": str(ports[service]), "host_ip": "127.0.0.1", "protocol": "tcp"}]
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps(config))
        compose = ["docker", "compose", "-p", project, "-f", str(path)]
        require(not subprocess.check_output(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project],
            text=True).strip(), "generated project already exists")
        try:
            subprocess.run(compose + ["config", "--quiet"], check=True)
            subprocess.run(compose + ["up", "-d", "--build", "cloud", "gateway"], check=True)
            ids = {s: subprocess.check_output(compose + ["ps", "-q", s], text=True).strip()
                   for s in ["cloud", "gateway"]}
            stack = Stack(published_url(ids["gateway"], 8000), published_url(ids["cloud"], 8001),
                          project=project, files=[str(path)])
            output["urls"] = {"gateway": stack.gateway, "cloud": stack.cloud}
            run(stack, args.samples, output)
            output["outcome"] = "passed"
        except (MeasurementError, requests.exceptions.RequestException,
                subprocess.SubprocessError, ValueError, KeyError) as error:
            output["outcome"], output["error"] = "failed", str(error)
            code = 1
        finally:
            # Keep results even if cleanup fails; never print resolved config/key material.
            # All volumes belong to this invocation and contain session-only test data.
            cleanup = subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], capture_output=True, text=True)
            output["cleanup"] = "passed" if cleanup.returncode == 0 else "failed"
            if cleanup.returncode:
                output["cleanup_error"] = cleanup.stderr
                code = 1
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"outcome": output.get("outcome"), "cleanup": output.get("cleanup"),
                      "error": output.get("error"), "results": str(args.json_out)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
