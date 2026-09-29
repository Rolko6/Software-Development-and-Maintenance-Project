#!/usr/bin/env python3
"""Security evidence for the ML-KEM gateway -> cloud link, against a running cloud.

Runs each negative case over real HTTP against the cloud service and records
the expected and actual outcome, whether anything was wrongly stored, and
which cloud metric moved. Then measures latency for a request that needs a
new session (handshake + data) and one that reuses a session.

The gateway side is the real SecureCloudClient from gateway/app/crypto,
loaded from this checkout. Faults (tampering, a lost response, a forged
reply) are injected in its transport, between the client and the network.

Start the stack so that every case applies: a real PSK, the cloud in
"required" mode, and a session TTL short enough to wait out:

    export ML_KEM_PSK=$(openssl rand -hex 32)
    CLOUD_ML_KEM_MODE=required docker compose -f docker-compose.yml \\
        -f <override setting CLOUD_ML_KEM_SESSION_TTL_SECONDS: "20"> up -d --build
    python scripts/evaluation/security_evidence.py --json evidence.json

Needs requirements-dev.txt. Exits 1 if any case differs from its expectation.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "gateway"))

from app.crypto import wire  # noqa: E402
from app.crypto.client import SecureCloudClient  # noqa: E402


# --- helpers -------------------------------------------------------------

def metrics(cloud: str) -> dict:
    text = requests.get(f"{cloud}/metrics/", timeout=5).text
    values = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.rpartition(" ")
            values[name] = float(value)
    return values


def stored(cloud: str, device_id: str) -> int:
    return sum(1 for r in requests.get(f"{cloud}/data", timeout=5).json() if r["device_id"] == device_id)


def real_get(url, timeout):
    return requests.get(url, timeout=timeout)


def real_post(url, body, timeout):
    return requests.post(url, json=body, timeout=timeout)


def client(cloud, psk, post=real_post):
    return SecureCloudClient(base_url=cloud, psk=psk, rekey_skew_seconds=0,
                             http_get=real_get, http_post=post)


def outcome(fn):
    """Run fn; return its HTTP status, 'ok', or the exception name."""
    try:
        result = fn()
    except requests.exceptions.HTTPError as exc:
        return str(exc.response.status_code)
    except requests.exceptions.RequestException as exc:
        return type(exc).__name__
    if isinstance(result, requests.Response):
        return str(result.status_code)
    return "200"


def device(case):
    return f"ev-{case}-{uuid.uuid4().hex[:6]}"


def reading(device_id, temperature=21.0):
    return {"device_id": device_id, "temperature": temperature}


# --- cases -----------------------------------------------------------------

CASES = []


def case(name, expected, metric=None, stored_expected=0, gap=False):
    """gap=True: the expected outcome is the weakness itself, reported as a gap."""
    def register(fn):
        CASES.append((name, expected, metric, stored_expected, gap, fn))
        return fn
    return register


@case("Wrong PSK on the gateway", "401", 'cloud_handshake_failed_total{reason="verification_failed"}')
def wrong_psk(cloud, psk, dev):
    wrong = bytes(b ^ 0xFF for b in psk)
    return outcome(lambda: client(cloud, wrong).send_secure(reading(dev)))


def _tampering_post(change):
    def post(url, body, timeout):
        if url.endswith("/secure/data"):
            body = dict(body)
            change(body)
        return real_post(url, body, timeout)
    return post


def _flip_ciphertext(body):
    raw = bytearray(base64.b64decode(body["ciphertext"]))
    raw[0] ^= 0x01
    body["ciphertext"] = base64.b64encode(bytes(raw)).decode()


@case("Tampered ciphertext", "400", "cloud_crypto_decrypt_failures_total")
def tampered_ciphertext(cloud, psk, dev):
    return outcome(lambda: client(cloud, psk, _tampering_post(_flip_ciphertext)).send_secure(reading(dev)))


@case("Tampered associated data (device_id relabelled)", "400", "cloud_crypto_decrypt_failures_total")
def tampered_aad(cloud, psk, dev):
    def relabel(body):
        body["device_id"] = dev + "-other"
    return outcome(lambda: client(cloud, psk, _tampering_post(relabel)).send_secure(reading(dev)))


@case("Replayed message", "409", 'cloud_secure_data_rejected_total{reason="replay"}', stored_expected=1)
def replay(cloud, psk, dev):
    captured = {}

    def recording(url, body, timeout):
        if url.endswith("/secure/data"):
            captured["body"] = body
        return real_post(url, body, timeout)

    client(cloud, psk, recording).send_secure(reading(dev))
    return outcome(lambda: requests.post(f"{cloud}/secure/data", json=captured["body"], timeout=5))


@case("Unknown session", "404", 'cloud_secure_data_rejected_total{reason="unknown_session"}')
def unknown_session(cloud, psk, dev):
    body = {"session_id": "never-issued", "device_id": dev,
            "nonce": base64.b64encode(wire.counter_to_nonce(0)).decode(), "ciphertext": "AAAA"}
    return outcome(lambda: requests.post(f"{cloud}/secure/data", json=body, timeout=5))


@case("Expired session", "410", 'cloud_secure_data_rejected_total{reason="expired_session"}', stored_expected=1)
def expired_session(cloud, psk, dev):
    c = client(cloud, psk)
    c.send_secure(reading(dev, 20.0))
    session = c._session
    wait = session.expires_at - time.time() + 1
    if wait > 90:
        return f"not run (session TTL {wait:.0f}s)"
    time.sleep(wait)
    counter = session.counter + 1
    nonce = wire.counter_to_nonce(counter)
    aad = wire.build_aad(session.session_id, dev, nonce)
    ciphertext = wire.aead_encrypt(session.key, nonce, json.dumps(reading(dev, 21.0)).encode(), aad)
    body = {"session_id": session.session_id, "device_id": dev,
            "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ciphertext).decode()}
    return outcome(lambda: requests.post(f"{cloud}/secure/data", json=body, timeout=5))


@case("Plaintext POST /data in required mode", "403")
def plaintext_required(cloud, psk, dev):
    return outcome(lambda: requests.post(f"{cloud}/data", json=reading(dev), timeout=5))


@case("Lost response, then the next reading (S1)", "200", stored_expected=3)
def lost_response(cloud, psk, dev):
    nonces = []

    def losing(url, body, timeout):
        response = real_post(url, body, timeout)
        if url.endswith("/secure/data"):
            nonces.append(body["nonce"])
            if len(nonces) == 2:
                raise requests.exceptions.ReadTimeout("response dropped after delivery")
        return response

    c = client(cloud, psk, losing)
    c.send_secure(reading(dev, 20.0))
    try:
        c.send_secure(reading(dev, 21.0))
    except requests.exceptions.Timeout:
        pass
    result = outcome(lambda: c.send_secure(reading(dev, 22.0)))
    unique = len(set(nonces)) == len(nonces)
    return result if unique else f"{result}, nonce reused"


@case("Forged 200 reply, reading never delivered (S8)", "200", gap=True)
def forged_reply(cloud, psk, dev):
    class Forged:
        status_code = 200

        def json(self):
            return {"status": "stored"}

        def raise_for_status(self):
            pass

    def dropping(url, body, timeout):
        if url.endswith("/secure/data"):
            return Forged()
        return real_post(url, body, timeout)

    return outcome(lambda: client(cloud, psk, dropping).send_secure(reading(dev)))


def run_cases(cloud, psk):
    results = []
    for name, expected, metric, stored_expected, gap, fn in CASES:
        dev = device(fn.__name__)
        before = metrics(cloud)
        actual = fn(cloud, psk, dev)
        after = metrics(cloud)
        delta = None if metric is None else after.get(metric, 0) - before.get(metric, 0)
        count = stored(cloud, dev)
        passed = (actual == expected and count == stored_expected
                  and (metric is None or delta == 1))
        if actual.startswith("not run"):
            passed = None
        elif gap and passed:
            passed = "gap"
        results.append({"case": name, "expected": expected, "actual": actual,
                        "stored": count, "stored_expected": stored_expected,
                        "metric": metric, "metric_delta": delta, "pass": passed})
    return results


# --- latency -------------------------------------------------------------

def summary(samples_ms):
    ordered = sorted(samples_ms)
    return {"n": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
            "p95": ordered[max(0, round(0.95 * len(ordered)) - 1)],
            "mean": statistics.fmean(ordered), "max": ordered[-1]}


def timed(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def measure(cloud, psk, samples, warmup):
    dev = device("latency")
    reused = client(cloud, psk)
    for _ in range(warmup):
        reused.send_secure(reading(dev))
    reused_ms, new_ms, handshake_ms = [], [], []
    for _ in range(samples):
        if reused._session is None or reused._session.expires_at - time.time() < 2:
            reused.send_secure(reading(dev))  # rekey outside the timed sample
        reused_ms.append(timed(lambda: reused.send_secure(reading(dev))))
    for _ in range(samples):
        fresh = client(cloud, psk)
        new_ms.append(timed(lambda: fresh.send_secure(reading(dev))))
        other = client(cloud, psk)
        handshake_ms.append(timed(other._handshake))
    return {"reused_session": summary(reused_ms), "new_session": summary(new_ms),
            "handshake_only": summary(handshake_ms)}


# --- main ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cloud-url", default="http://localhost:8001")
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args()

    psk = os.environ.get("ML_KEM_PSK")
    if not psk:
        parser.error("set ML_KEM_PSK to the value the cloud runs with")
    psk = psk.encode()
    cloud = args.cloud_url.rstrip("/")

    results = run_cases(cloud, psk)
    latency = measure(cloud, psk, args.samples, args.warmup)

    print("| Case | Expected | Actual | Stored (expected) | Metric +1 | Result |")
    print("| --- | --- | --- | --- | --- | --- |")
    for r in results:
        metric = "—" if r["metric"] is None else f"`{r['metric']}` {r['metric_delta']:+g}"
        verdict = {True: "as expected", False: "**differs**", None: "not run",
                   "gap": "known gap confirmed"}[r["pass"]]
        print(f"| {r['case']} | `{r['expected']}` | `{r['actual']}` | {r['stored']} ({r['stored_expected']}) "
              f"| {metric} | {verdict} |")
    print()
    print("| Request | n | min | median | p95 | mean | max |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name, s in latency.items():
        print(f"| {name} | {s['n']} | {s['min']:.2f} | {s['median']:.2f} | {s['p95']:.2f} "
              f"| {s['mean']:.2f} | {s['max']:.2f} |")
    print("\nLatency in milliseconds, host -> published cloud port.")

    if args.json:
        Path(args.json).write_text(json.dumps({"cases": results, "latency_ms": latency}, indent=2) + "\n")

    return 1 if any(r["pass"] is False for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
