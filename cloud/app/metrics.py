"""Prometheus metric definitions and exposition app for the cloud service.

The cloud currently exposes no metrics at all. This module defines the
full set for it and does not increment or observe any of them itself
(only ``GATEWAY_BUILD_INFO``'s cloud counterpart, ``CLOUD_BUILD_INFO``,
is set here, once, at import time). Wiring instructions for the rest:

Mounting (new integration point -- cloud has no ``/metrics`` route yet):

- In ``cloud/app/main.py``, mirror the gateway's pattern:
  ``from app.metrics import metrics_app`` then
  ``app.mount("/metrics", metrics_app)``. As with the gateway, a GET to
  the bare ``/metrics`` path will receive a 307 redirect to
  ``/metrics/`` (Starlette's ``Mount`` behaviour) -- the scrape config
  in ``monitoring/prometheus.yml`` already points at ``/metrics/``.

Storage and delivery (``cloud/app/storage.py`` and ``cloud/app/main.py``,
touched by the incoming bounded-storage and validation work):

- ``CLOUD_READINGS_STORED_TOTAL`` -- increment in ``storage.py`` (or
  ``main.py`` right after a successful ``save_sensor_data`` call) once
  per reading that is actually stored.
- ``CLOUD_READINGS_REJECTED_TOTAL`` -- increment in ``main.py``, in the
  handler or a request-validation-error handler, once per reading the
  cloud refuses, labelled with the closest ``reason`` below.
- ``CLOUD_STORAGE_EVICTIONS_TOTAL`` -- increment in ``storage.py``
  whenever the bounded-retention change drops an existing reading to
  stay within its capacity limit (once per evicted reading, not once
  per insertion that triggers eviction, if more than one can be evicted
  at a time).
- ``CLOUD_STORED_READINGS`` -- set (with ``.set(...)``, not
  ``.inc()``/``.dec()``) in ``storage.py`` to the current number of
  readings held, after every store and every eviction, so the gauge
  never drifts from the real list length.
- ``CLOUD_REQUEST_DURATION_SECONDS`` -- observe in ``main.py`` around
  the body of the ``POST /data`` handler and its validation-error
  handler, labelled with the final ``outcome`` and the active
  ``security_mode``.

Cryptography (cloud side of the ML-KEM link, under
``cloud/app/crypto/``, wired into the handshake endpoint and the AEAD
receive/respond path):

- ``CLOUD_HANDSHAKE_STARTED_TOTAL`` / ``CLOUD_HANDSHAKE_SUCCEEDED_TOTAL``
  -- increment when the cloud receives a handshake request and when it
  completes it successfully, respectively.
- ``CLOUD_HANDSHAKE_FAILED_TOTAL`` -- increment on a failed handshake,
  labelled with one of the fixed ``reason`` values below.
- ``CLOUD_HANDSHAKE_DURATION_SECONDS`` -- observe the wall-clock time
  the cloud spends processing one handshake request, start to success
  or failure, labelled by ``outcome``.
- ``CLOUD_CRYPTO_DECRYPT_FAILURES_TOTAL`` -- increment wherever the
  AEAD open call raises while unwrapping an inbound payload from the
  gateway (covers tampering and session-key mismatches).
- ``CLOUD_CRYPTO_ENCRYPT_FAILURES_TOTAL`` -- increment wherever the
  AEAD seal call raises while protecting an outbound response to the
  gateway.
- ``CLOUD_SECURITY_MODE`` -- call ``.state(mode)`` once at startup with
  the configured mode, and again every time the mode changes at
  runtime.
- ``CLOUD_BUILD_INFO`` -- set once, at import time, below. Override
  with the ``CLOUD_BUILD_VERSION`` / ``CLOUD_BUILD_COMMIT`` environment
  variables.

Label values are fixed and deliberately few -- no per-device or
per-session label is used anywhere in this module:

- ``outcome`` (request handling): ``stored``, ``rejected``
- ``outcome`` (handshake): ``success``, ``failure``
- ``security_mode``: ``off``, ``enabled``, ``required``
- ``reason`` (reading rejected): ``invalid_device_id``,
  ``invalid_temperature``, ``other``
- ``reason`` (handshake failure): ``timeout``, ``decode_error``,
  ``verification_failed``, ``other``
"""

import os
import platform

from prometheus_client import Counter, Enum, Gauge, Histogram, Info, make_asgi_app

# Same rationale as the gateway's buckets (see gateway/app/metrics.py):
# loopback/Compose-network hops are normally sub-10ms; the range is
# stretched to also resolve a slow pure-Python ML-KEM handshake without
# an unbounded tail.
_REQUEST_BUCKETS = (
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
)
_HANDSHAKE_BUCKETS = (
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
)


# --- Storage and delivery ----------------------------------------------

CLOUD_READINGS_STORED_TOTAL = Counter(
    "cloud_readings_stored_total",
    "Total sensor readings successfully stored by the cloud service.",
)

CLOUD_READINGS_REJECTED_TOTAL = Counter(
    "cloud_readings_rejected_total",
    "Total readings rejected by cloud-side validation, by reason.",
    labelnames=("reason",),
)

CLOUD_STORAGE_EVICTIONS_TOTAL = Counter(
    "cloud_storage_evictions_total",
    "Total stored readings evicted to enforce the bounded in-memory "
    "retention limit.",
)

CLOUD_STORED_READINGS = Gauge(
    "cloud_stored_readings",
    "Current number of sensor readings held in cloud in-memory "
    "storage.",
)

CLOUD_REQUEST_DURATION_SECONDS = Histogram(
    "cloud_request_duration_seconds",
    "End-to-end time to handle one POST /data request in the cloud "
    "service, from receipt to the response returned to the caller.",
    labelnames=("outcome", "security_mode"),
    buckets=_REQUEST_BUCKETS,
)


# --- Cryptography (cloud side of the ML-KEM link) -----------------------

CLOUD_HANDSHAKE_STARTED_TOTAL = Counter(
    "cloud_handshake_started_total",
    "Total ML-KEM handshake requests received by the cloud from the "
    "gateway.",
)

CLOUD_HANDSHAKE_SUCCEEDED_TOTAL = Counter(
    "cloud_handshake_succeeded_total",
    "Total ML-KEM handshakes the cloud completed successfully.",
)

CLOUD_HANDSHAKE_FAILED_TOTAL = Counter(
    "cloud_handshake_failed_total",
    "Total ML-KEM handshakes that failed on the cloud side, by reason.",
    labelnames=("reason",),
)

CLOUD_HANDSHAKE_DURATION_SECONDS = Histogram(
    "cloud_handshake_duration_seconds",
    "Duration of one ML-KEM handshake request as processed by the "
    "cloud, start to success or failure.",
    labelnames=("outcome",),
    buckets=_HANDSHAKE_BUCKETS,
)

CLOUD_CRYPTO_DECRYPT_FAILURES_TOTAL = Counter(
    "cloud_crypto_decrypt_failures_total",
    "Total AEAD decryption/authentication failures on the cloud when "
    "unwrapping a payload from the gateway.",
)

CLOUD_CRYPTO_ENCRYPT_FAILURES_TOTAL = Counter(
    "cloud_crypto_encrypt_failures_total",
    "Total AEAD encryption failures on the cloud when protecting an "
    "outbound response to the gateway.",
)

CLOUD_SECURITY_MODE = Enum(
    "cloud_security_mode",
    "Active cloud crypto security mode for the gateway-to-cloud link.",
    states=["off", "enabled", "required"],
)


# --- Build/version info --------------------------------------------------

CLOUD_BUILD_INFO = Info(
    "cloud_build",
    "Cloud service build and runtime metadata.",
)
CLOUD_BUILD_INFO.info({
    "version": os.getenv("CLOUD_BUILD_VERSION", "dev"),
    "commit": os.getenv("CLOUD_BUILD_COMMIT", "unknown"),
    "python_version": platform.python_version(),
})


# --- Ready-to-mount exposition app ---------------------------------------
# Mirrors the gateway's pattern (see gateway/app/main.py). Import and
# mount directly: `from app.metrics import metrics_app` then
# `app.mount("/metrics", metrics_app)`.

metrics_app = make_asgi_app()
