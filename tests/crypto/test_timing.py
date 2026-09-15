"""Measured overhead for work package 5's baseline comparison.

Method and caveats (see docs/security/ml-kem-integration.md, "Measured
overhead" for the recorded numbers):

- Measured locally on the machine running this test suite, Python
  ``sys.version`` (printed below) -- typically 3.13 in this dev
  virtualenv vs. 3.12 in the service containers; native code paths
  (cryptography's Rust/OpenSSL-backed ML-KEM, AES-GCM) should be far less
  Python-version-sensitive than a pure-Python implementation would be, but
  the containers were not measured directly (Docker is unavailable in this
  environment -- see the design doc).
- The "full handshake" number goes through FastAPI's TestClient (in-process
  ASGI transport, no real socket/network stack, no TLS) -- it is a lower
  bound; a real HTTP round trip over a Docker bridge network will add
  latency this does not capture.
- Single-threaded, single-process, no other load on the machine. Not a
  benchmark-grade measurement (no warmup isolation from JIT/allocator
  effects, no repeated-run averaging across processes).

This test always passes (it is a measurement, not a correctness check); it
prints a report to stdout, which is why it must be run with `-s`:

    ./.venv/bin/python -m pytest tests/crypto/test_timing.py -q -s
"""

from __future__ import annotations

import json
import statistics
import sys
import time

from cryptography.hazmat.primitives.asymmetric import mlkem

from .conftest import FakeCloudApp, cloud_wire_module, gateway_client_module, make_transport


def _percentile(samples_ms, p):
    ordered = sorted(samples_ms)
    k = (len(ordered) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _report(name, samples_ms):
    median = statistics.median(samples_ms)
    p95 = _percentile(samples_ms, 95)
    print(f"[ml-kem timing] {name}: n={len(samples_ms)} median={median:.4f}ms p95={p95:.4f}ms")
    return median, p95


def test_keygen_encaps_decaps_timing():
    print(f"\n[ml-kem timing] python={sys.version.split()[0]}")

    keygen_ms = []
    for _ in range(100):
        t0 = time.perf_counter()
        mlkem.MLKEM768PrivateKey.generate()
        keygen_ms.append((time.perf_counter() - t0) * 1000)
    _report("keygen", keygen_ms)

    private_key = mlkem.MLKEM768PrivateKey.generate()
    public_key = private_key.public_key()

    encaps_ms = []
    ciphertexts = []
    for _ in range(100):
        t0 = time.perf_counter()
        _, ct = public_key.encapsulate()
        encaps_ms.append((time.perf_counter() - t0) * 1000)
        ciphertexts.append(ct)
    _report("encaps", encaps_ms)

    decaps_ms = []
    for ct in ciphertexts:
        t0 = time.perf_counter()
        private_key.decapsulate(ct)
        decaps_ms.append((time.perf_counter() - t0) * 1000)
    _report("decaps", decaps_ms)


def test_full_handshake_timing_via_testclient(monkeypatch):
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "enabled")
    from fastapi.testclient import TestClient

    fake = FakeCloudApp()
    with TestClient(fake.app) as tc:
        http_get, http_post = make_transport(tc)
        handshake_ms = []
        for _ in range(20):
            client = gateway_client_module.SecureCloudClient(
                base_url="http://cloud:8001", http_get=http_get, http_post=http_post
            )
            t0 = time.perf_counter()
            client._handshake()
            handshake_ms.append((time.perf_counter() - t0) * 1000)
        _report("full handshake (in-process ASGI, no network)", handshake_ms)


def test_per_message_encrypt_decrypt_timing():
    shared_secret = b"x" * 32
    client_nonce = b"y" * 16
    session_key = cloud_wire_module.derive_session_key(shared_secret, client_nonce, "cloud-mlkem768-1")
    reading = json.dumps({"device_id": "sensor-001", "temperature": 21.5}).encode("utf-8")

    encrypt_ms = []
    decrypt_ms = []
    for counter in range(1000):
        nonce = cloud_wire_module.counter_to_nonce(counter)
        aad = cloud_wire_module.build_aad("session-x", "sensor-001", nonce)

        t0 = time.perf_counter()
        ciphertext = cloud_wire_module.aead_encrypt(session_key, nonce, reading, aad)
        encrypt_ms.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        cloud_wire_module.aead_decrypt(session_key, nonce, ciphertext, aad)
        decrypt_ms.append((time.perf_counter() - t0) * 1000)

    _report("AES-256-GCM encrypt (post-HKDF)", encrypt_ms)
    _report("AES-256-GCM decrypt (post-HKDF)", decrypt_ms)
