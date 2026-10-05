#!/usr/bin/env python3
"""Verify persistence, security, sensor state and real monitoring in an isolated stack.

Creates its own project, free loopback ports and session-only volumes. Never
interrupts an existing deployment. The real two-minute outage alert is exercised.
"""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import uuid

import requests

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait_for(probe, message, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except (requests.RequestException, ValueError, KeyError):
            pass
        time.sleep(2)
    raise RuntimeError(message)


def get(url):
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.json()


def post(url, payload):
    return requests.post(url, json=payload, timeout=10)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    project = "reliability-eval-" + uuid.uuid4().hex[:12]
    evidence = {"project": project, "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
                "checks": {}}
    code = 1
    env = dict(os.environ, GRAFANA_ADMIN_PASSWORD=secrets.token_urlsafe(24), GRAFANA_ADMIN_USER="admin",
               CLOUD_ALLOW_LEGACY_INGESTION="false")
    with tempfile.TemporaryDirectory(prefix="reliability-eval-") as directory:
        config = json.loads(subprocess.check_output(
            ["docker", "compose", "-p", project, "-f", str(ROOT / "docker-compose.yml"),
             "-f", str(ROOT / "docker-compose.monitoring.yml"), "config", "--format", "json"],
            cwd=ROOT, env=env, text=True))
        config["services"].pop("device")
        # Resolve each local port once so stop/start keeps the observation URLs.
        urls = {}
        sockets = []
        for service, target in [("gateway", 8000), ("cloud", 8001), ("prometheus", 9090),
                                ("grafana", 3000), ("alertmanager", 9093), ("alert-inbox", 8080)]:
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            sockets.append(listener)
            port = listener.getsockname()[1]
            config["services"][service]["ports"] = [
                {"target": target, "published": str(port), "host_ip": "127.0.0.1", "protocol": "tcp"}]
            urls[service] = "http://127.0.0.1:" + str(port)
            config["services"][service]["restart"] = "no"
        for listener in sockets:
            listener.close()
        # Compose config expands named volumes to project-specific names already.
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps(config))
        compose = ["docker", "compose", "-p", project, "-f", str(path)]
        require(not subprocess.check_output(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project],
            text=True).strip(), "isolated project already exists")
        evidence["urls"] = urls
        checks = evidence["checks"]
        try:
            subprocess.run(compose + ["up", "-d", "--build"], check=True)
            for service in ("gateway", "cloud", "alert-inbox"):
                wait_for(lambda s=service: get(urls[s] + "/health").get("status") == "healthy",
                         service + " did not become healthy")
            query_url = urls["prometheus"] + "/api/v1/query"

            def query(expression):
                response = requests.get(query_url, params={"query": expression}, timeout=5)
                response.raise_for_status()
                payload = response.json()
                require(payload["status"] == "success", "PromQL query failed")
                return payload["data"]["result"]

            def targets_healthy():
                targets = get(urls["prometheus"] + "/api/v1/targets")["data"]["activeTargets"]
                return len(targets) == 2 and all(t["health"] == "up" for t in targets)

            wait_for(targets_healthy, "both scrape targets did not become healthy")
            checks["scrape_targets_healthy"] = True
            wait_for(lambda: get(urls["grafana"] + "/api/health").get("database") == "ok",
                     "Grafana did not become healthy")
            dashboard = requests.get(urls["grafana"] + "/api/dashboards/uid/edge-cloud-operations",
                                     auth=("admin", env["GRAFANA_ADMIN_PASSWORD"]), timeout=5)
            require(dashboard.status_code == 200, "Grafana dashboard was not provisioned")
            checks["dashboard_panels"] = len(dashboard.json()["dashboard"]["panels"])

            reading = {"device_id": "persistence-marker", "temperature": 21.75}
            require(post(urls["gateway"] + "/device-data", reading).status_code == 200,
                    "encrypted gateway delivery failed")
            require(reading in get(urls["cloud"] + "/data"), "exact reading was not stored")
            rejected = post(urls["cloud"] + "/data", {"device_id": "plaintext-bypass", "temperature": 20})
            require(rejected.status_code == 403, "plaintext bypass was not rejected")
            require(all(r["device_id"] != "plaintext-bypass" for r in get(urls["cloud"] + "/data")),
                    "rejected plaintext was stored")
            checks["plaintext_default_status"] = rejected.status_code

            subprocess.run(compose + ["restart", "cloud"], check=True)
            wait_for(lambda: get(urls["cloud"] + "/health").get("status") == "healthy",
                     "cloud process restart failed")
            require(reading in get(urls["cloud"] + "/data"), "reading lost after process restart")
            subprocess.run(compose + ["up", "-d", "--no-deps", "--force-recreate", "cloud"], check=True)
            wait_for(lambda: get(urls["cloud"] + "/health").get("status") == "healthy",
                     "cloud recreation failed")
            require(reading in get(urls["cloud"] + "/data"), "reading lost after container recreation")
            checks["secure_reading_survives_restart_and_recreation"] = reading

            # Explicit compatibility mode still writes durably; it is never default.
            config["services"]["cloud"]["environment"]["CLOUD_ALLOW_LEGACY_INGESTION"] = "true"
            path.write_text(json.dumps(config))
            subprocess.run(compose + ["up", "-d", "--no-deps", "--force-recreate", "cloud"], check=True)
            wait_for(lambda: get(urls["cloud"] + "/health").get("status") == "healthy", "legacy cloud failed")
            legacy = {"device_id": "explicit-legacy-marker", "temperature": 19.25}
            require(post(urls["cloud"] + "/data", legacy).status_code == 200, "explicit opt-in failed")
            config["services"]["cloud"]["environment"]["CLOUD_ALLOW_LEGACY_INGESTION"] = "false"
            path.write_text(json.dumps(config))
            subprocess.run(compose + ["up", "-d", "--no-deps", "--force-recreate", "cloud"], check=True)
            wait_for(lambda: get(urls["cloud"] + "/health").get("status") == "healthy", "secured cloud failed")
            require(legacy in get(urls["cloud"] + "/data"), "legacy reading lost after recreation")
            checks["explicit_legacy_reading_survives_recreation"] = legacy

            require(post(urls["gateway"] + "/device-status",
                         {"device_id": "sensor-probe", "status": "disconnected"}).status_code == 200,
                    "disconnected status rejected")
            require(not any(r["device_id"] == "sensor-probe" for r in get(urls["cloud"] + "/data")),
                    "status fabricated a cloud reading")
            wait_for(lambda: query('sensor_disconnected_devices{job="gateway"}') and
                     float(query('sensor_disconnected_devices{job="gateway"}')[0]["value"][1]) == 1,
                     "disconnected sensor gauge not scraped")
            require(float(query('sensor_read_failures_total{job="gateway"}')[0]["value"][1]) == 1,
                    "disconnect failure counter not scraped")
            for _ in range(3):
                require(post(urls["gateway"] + "/device-data",
                             {"device_id": "sensor-probe", "temperature": 22}).status_code == 200,
                        "sensor reading failed")
            wait_for(lambda: query('sensor_suspected_stuck_devices{job="gateway"}') and
                     float(query('sensor_suspected_stuck_devices{job="gateway"}')[0]["value"][1]) == 1,
                     "suspected stuck metric missing")
            require(post(urls["gateway"] + "/device-data",
                         {"device_id": "sensor-probe", "temperature": 23}).status_code == 200,
                    "sensor recovery failed")
            wait_for(lambda: query('sensor_suspected_stuck_devices{job="gateway"}') and
                     float(query('sensor_suspected_stuck_devices{job="gateway"}')[0]["value"][1]) == 0,
                     "suspected stuck metric did not clear")
            wait_for(lambda: query('sensor_silent_devices{job="gateway"}') and
                     float(query('sensor_silent_devices{job="gateway"}')[0]["value"][1]) > 0,
                     "silent device not observed")
            checks["sensor_status_stuck_recovery_and_silence"] = True

            wait_for(lambda: query('secure_data_received_total{job="cloud"}') and
                     float(query('secure_data_received_total{job="cloud"}')[0]["value"][1]) > 0,
                     "stored reading counter not scraped")
            historical_time = time.time()
            before = requests.get(query_url, params={"query": 'secure_data_received_total{job="cloud"}',
                                  "time": historical_time}, timeout=5).json()["data"]["result"][0]["value"]
            subprocess.run(compose + ["up", "-d", "--no-deps", "--force-recreate", "prometheus", "grafana", "alert-inbox"], check=True)
            wait_for(targets_healthy, "monitoring did not recover after recreation")
            historical = requests.get(query_url, params={"query": 'secure_data_received_total{job="cloud"}',
                                      "time": historical_time}, timeout=5).json()["data"]["result"]
            require(historical and historical[0]["value"][1] == before[1], "Prometheus history lost")
            checks["prometheus_history_survives_recreation"] = True

            start = time.monotonic()
            subprocess.run(compose + ["stop", "cloud"], check=True)

            def notification(status):
                return any(a.get("labels", {}).get("alertname") == "ServiceUnavailable" and
                           a.get("labels", {}).get("job") == "cloud" and a.get("status") == status
                           for row in get(urls["alert-inbox"] + "/alerts")
                           for a in row["notification"].get("alerts", []))

            wait_for(lambda: notification("firing"), "cloud outage notification did not arrive", 210)
            outage_seconds = time.monotonic() - start
            require(outage_seconds >= 120, "service outage alert fired before its two-minute hold-down")
            checks["outage_notification_seconds"] = round(outage_seconds, 2)
            subprocess.run(compose + ["start", "cloud"], check=True)
            wait_for(lambda: notification("resolved"), "cloud recovery notification did not arrive", 90)
            checks["recovery_notification"] = True
            subprocess.run(compose + ["up", "-d", "--no-deps", "--force-recreate", "alert-inbox"], check=True)
            wait_for(lambda: notification("resolved"), "alert inbox lost notifications after recreation")
            checks["notifications_survive_recreation"] = True
            require(post(urls["gateway"] + "/device-data", {"device_id": "final-probe", "temperature": 24}).status_code == 200,
                    "encrypted delivery failed after outage recovery")
            evidence["outcome"] = "passed"
            code = 0
        except (RuntimeError, requests.RequestException, subprocess.SubprocessError, ValueError, KeyError) as error:
            evidence["outcome"], evidence["error"] = "failed", str(error)
        finally:
            # These volumes were created by this invocation and contain only test data.
            cleanup = subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], capture_output=True, text=True)
            evidence["cleanup"] = "passed" if cleanup.returncode == 0 else "failed"
            code = code or int(cleanup.returncode != 0)
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"outcome": evidence.get("outcome"), "error": evidence.get("error"), "evidence": str(args.json_out)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
