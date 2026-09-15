"""Prometheus metric definitions for the edge gateway.

This module only defines and registers metrics; nothing in this file
increments or observes them. That happens elsewhere in the gateway, as
listed below, so that whoever implements each feature knows exactly
which metric to touch and with which label values.

Existing metrics (name and meaning unchanged so the README and any
existing dashboard stay valid):

- ``DEVICE_MESSAGES_TOTAL`` -- increment in ``gateway/app/main.py``,
  ``receive_device_data``, once for every device reading that passes
  gateway-side validation, before the forwarding attempt is made.
- ``CLOUD_FORWARD_FAILURES_TOTAL`` -- **preserve its current
  once-per-request semantics.** Today it increments exactly once per
  incoming request whose forwarding to the cloud fails (there being
  only one attempt today); keep it that way under the incoming
  retry-with-backoff feature -- increment it once in
  ``gateway/app/cloud_client.py``, at the point all attempts for one
  request have been exhausted and it gives up, not once per individual
  attempt. This matters concretely:
  ``scripts/baseline/run_baseline.sh`` asserts
  ``cloud_forward_failures_total 1.0`` after exactly one outage
  request, and changing this metric's cadence to per-attempt would
  silently break that check the moment retries land. Per-attempt
  failure counts are already available without a new counter: see
  ``GATEWAY_CLOUD_REQUEST_DURATION_SECONDS{outcome="failure"}``'s
  ``_count`` series below, which observes once per attempt by design.

Delivery and latency (incoming retry-with-backoff feature touches
``gateway/app/main.py`` and ``gateway/app/cloud_client.py``):

- ``GATEWAY_REQUEST_DURATION_SECONDS`` -- observe in
  ``gateway/app/main.py``, around the body of ``receive_device_data``
  *and* in the exception handler for request-validation errors, so that
  rejected requests are timed too. Record wall-clock time from receiving
  the request to returning the response, labelled with the final
  ``outcome`` and the ``security_mode`` active for that request.
- ``GATEWAY_CLOUD_REQUEST_DURATION_SECONDS`` -- observe in
  ``gateway/app/cloud_client.py`` around each individual HTTP attempt to
  the cloud (one observation per attempt, so a retried request produces
  several observations), labelled by whether that attempt succeeded.
- ``GATEWAY_DELIVERY_OUTCOME_TOTAL`` -- increment in
  ``gateway/app/main.py`` once per incoming request, at the point the
  final outcome is known: a successful forward, the validation-error
  handler, or the exception handler that returns HTTP 502 after retries
  are exhausted. Use the same ``outcome`` value as the histogram above.

Retries (incoming retry-with-backoff feature in
``gateway/app/cloud_client.py``):

- ``GATEWAY_CLOUD_RETRY_ATTEMPTS_TOTAL`` -- increment once for every
  attempt *after* the first, i.e. once per retry actually issued (not
  once per request).
- ``GATEWAY_CLOUD_RETRIES_EXHAUSTED_TOTAL`` -- increment once when the
  retry budget is exhausted and no attempt succeeded, at the point
  ``cloud_client`` gives up and raises to the caller.

Cryptography (incoming ML-KEM feature under ``gateway/app/crypto/``,
wired into the handshake endpoint and the AEAD send/receive path):

- ``GATEWAY_HANDSHAKE_STARTED_TOTAL`` -- increment when the gateway
  initiates a handshake attempt toward the cloud.
- ``GATEWAY_HANDSHAKE_SUCCEEDED_TOTAL`` -- increment when a handshake
  completes and a session key is established.
- ``GATEWAY_HANDSHAKE_FAILED_TOTAL`` -- increment on a failed handshake,
  labelled with one of the fixed ``reason`` values below (map whatever
  exception occurred to the closest bucket).
- ``GATEWAY_HANDSHAKE_DURATION_SECONDS`` -- observe the wall-clock time
  of one full handshake attempt, start to success or failure, labelled
  by ``outcome``.
- ``GATEWAY_SESSION_REKEYS_TOTAL`` -- increment when an *existing,
  previously-established* session is replaced by a new handshake
  (expired and re-established, or forced). Do not increment this for
  the very first handshake with a peer -- that is only "started" /
  "succeeded".
- ``GATEWAY_CRYPTO_ENCRYPT_FAILURES_TOTAL`` -- increment wherever the
  AEAD seal call raises while protecting an outbound payload to the
  cloud.
- ``GATEWAY_CRYPTO_DECRYPT_FAILURES_TOTAL`` -- increment wherever the
  AEAD open call raises while unwrapping a response from the cloud
  (covers tampering and session-key mismatches).
- ``GATEWAY_SECURITY_MODE`` -- call ``.state(mode)`` once at startup with
  the configured mode, and again every time the mode changes at
  runtime.
- ``GATEWAY_BUILD_INFO`` -- set once, at import time, below. No other
  file needs to touch it; override the reported values with the
  ``GATEWAY_BUILD_VERSION`` / ``GATEWAY_BUILD_COMMIT`` environment
  variables (e.g. from a future CI step).

Label values are fixed and deliberately few -- no per-device or
per-session label is used anywhere in this module, to keep the
exposed series count bounded regardless of fleet size:

- ``outcome`` (request delivery): ``forwarded``, ``rejected_validation``,
  ``failed_after_retries``
- ``outcome`` (single cloud attempt, handshake): ``success``, ``failure``
- ``security_mode``: ``off``, ``enabled``, ``required``
- ``reason`` (handshake failure): ``timeout``, ``peer_unavailable``,
  ``decode_error``, ``verification_failed``, ``other``
- ``reason`` (session rekey): ``expired``, ``forced``
"""

import os
import platform

from prometheus_client import Counter, Enum, Histogram, Info

# Bucket boundaries are seconds. Both services run over loopback (bare
# uvicorn locally, container-to-container on the Compose network), so
# most successful hops are sub-10ms; the upper end is stretched out to
# also give useful resolution for a request that hits retry backoff or
# a slow pure-Python ML-KEM handshake, without an unbounded tail.
_REQUEST_BUCKETS = (
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)
_CLOUD_HOP_BUCKETS = (
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
)
_HANDSHAKE_BUCKETS = (
    0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
)


# --- Existing metrics: names and meanings unchanged ------------------

DEVICE_MESSAGES_TOTAL = Counter(
    "device_messages_total",
    "Total number of messages received from devices"
)


CLOUD_FORWARD_FAILURES_TOTAL = Counter(
    "cloud_forward_failures_total",
    "Total number of failed attempts to forward data to cloud"
)


# --- Delivery and latency ---------------------------------------------

GATEWAY_REQUEST_DURATION_SECONDS = Histogram(
    "gateway_request_duration_seconds",
    "End-to-end time to handle one POST /device-data request, from "
    "receipt to the response returned to the caller, including any "
    "gateway-to-cloud retries.",
    labelnames=("outcome", "security_mode"),
    buckets=_REQUEST_BUCKETS,
)

GATEWAY_CLOUD_REQUEST_DURATION_SECONDS = Histogram(
    "gateway_cloud_request_duration_seconds",
    "Duration of a single gateway-to-cloud forwarding HTTP attempt. "
    "One observation per attempt: a retried request contributes "
    "multiple observations, not one.",
    labelnames=("outcome", "security_mode"),
    buckets=_CLOUD_HOP_BUCKETS,
)

GATEWAY_DELIVERY_OUTCOME_TOTAL = Counter(
    "gateway_delivery_outcome_total",
    "Total device-data requests handled by the gateway, by final "
    "delivery outcome.",
    labelnames=("outcome",),
)


# --- Retries -----------------------------------------------------------

GATEWAY_CLOUD_RETRY_ATTEMPTS_TOTAL = Counter(
    "gateway_cloud_retry_attempts_total",
    "Total retry attempts made when forwarding a reading to the cloud. "
    "Excludes each request's initial attempt; counts only the retries.",
)

GATEWAY_CLOUD_RETRIES_EXHAUSTED_TOTAL = Counter(
    "gateway_cloud_retries_exhausted_total",
    "Total forwarding operations that exhausted all retry attempts "
    "without a successful delivery to the cloud.",
)


# --- Cryptography (gateway side of the ML-KEM link) --------------------

GATEWAY_HANDSHAKE_STARTED_TOTAL = Counter(
    "gateway_handshake_started_total",
    "Total ML-KEM handshakes initiated by the gateway toward the cloud.",
)

GATEWAY_HANDSHAKE_SUCCEEDED_TOTAL = Counter(
    "gateway_handshake_succeeded_total",
    "Total ML-KEM handshakes that completed successfully and "
    "established a session key.",
)

GATEWAY_HANDSHAKE_FAILED_TOTAL = Counter(
    "gateway_handshake_failed_total",
    "Total ML-KEM handshakes that failed, by reason.",
    labelnames=("reason",),
)

GATEWAY_HANDSHAKE_DURATION_SECONDS = Histogram(
    "gateway_handshake_duration_seconds",
    "Duration of one full ML-KEM handshake attempt, start to success "
    "or failure.",
    labelnames=("outcome",),
    buckets=_HANDSHAKE_BUCKETS,
)

GATEWAY_SESSION_REKEYS_TOTAL = Counter(
    "gateway_session_rekeys_total",
    "Total gateway-to-cloud session rekeys, where an existing session "
    "is replaced by a new handshake, by reason. Excludes the first "
    "handshake with a peer.",
    labelnames=("reason",),
)

GATEWAY_CRYPTO_ENCRYPT_FAILURES_TOTAL = Counter(
    "gateway_crypto_encrypt_failures_total",
    "Total AEAD encryption failures on the gateway when protecting an "
    "outbound payload to the cloud.",
)

GATEWAY_CRYPTO_DECRYPT_FAILURES_TOTAL = Counter(
    "gateway_crypto_decrypt_failures_total",
    "Total AEAD decryption/authentication failures on the gateway when "
    "unwrapping a response from the cloud.",
)

GATEWAY_SECURITY_MODE = Enum(
    "gateway_security_mode",
    "Active gateway crypto security mode for the gateway-to-cloud "
    "link.",
    states=["off", "enabled", "required"],
)


# --- Build/version info -------------------------------------------------
# Set once here, from environment variables a future CI/build step can
# supply. Defaults are safe for local runs; no other file needs to set
# this metric.

GATEWAY_BUILD_INFO = Info(
    "gateway_build",
    "Gateway build and runtime metadata.",
)
GATEWAY_BUILD_INFO.info({
    "version": os.getenv("GATEWAY_BUILD_VERSION", "dev"),
    "commit": os.getenv("GATEWAY_BUILD_COMMIT", "unknown"),
    "python_version": platform.python_version(),
})
