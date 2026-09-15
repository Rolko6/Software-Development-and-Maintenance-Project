# Initially, this sends data normally.
# Later, this will become the place where ML-KEM is integrated.

import os
import time

import requests

from .metrics import (
    GATEWAY_CLOUD_REQUEST_DURATION_SECONDS,
    GATEWAY_CLOUD_RETRIES_EXHAUSTED_TOTAL,
    GATEWAY_CLOUD_RETRY_ATTEMPTS_TOTAL
)


CLOUD_URL = os.getenv(
    "CLOUD_URL",
    "http://localhost:8001/data"
)


def _default_cloud_health_url(cloud_url: str) -> str:
    if cloud_url.endswith("/data"):
        return cloud_url[: -len("/data")] + "/health"
    return cloud_url.rstrip("/") + "/health"


# Defaults to CLOUD_URL with the /data suffix swapped for /health, so a
# Compose deployment that only sets CLOUD_URL (e.g. http://cloud:8001/data)
# still gets a working readiness check with no extra configuration. Set
# CLOUD_HEALTH_URL explicitly to override.
CLOUD_HEALTH_URL = os.getenv(
    "CLOUD_HEALTH_URL",
    _default_cloud_health_url(CLOUD_URL)
)

# Per-attempt network timeout for the gateway->cloud forward call. Previously
# hardcoded to 5 seconds; lowered so that, combined with the retry budget
# below, a fully-exhausted retry sequence still returns before the simulated
# device's own default 5-second client timeout (see device/app/config.py).
CLOUD_REQUEST_TIMEOUT_SECONDS = float(os.getenv(
    "CLOUD_REQUEST_TIMEOUT_SECONDS",
    "1"
))

# Timeout for the separate, single-attempt cloud health check used by
# GET /ready. Not part of the forward retry budget below.
CLOUD_READINESS_TIMEOUT_SECONDS = float(os.getenv(
    "CLOUD_READINESS_TIMEOUT_SECONDS",
    "2"
))

# Bounded retry for the gateway->cloud leg. This is a short, in-request
# retry -- not a durable queue. A reading that still fails after the retry
# budget is exhausted is discarded; see docs/validation/
# 2026-09-15-reliability.md for the documented residual risk.
CLOUD_FORWARD_MAX_ATTEMPTS = int(os.getenv(
    "CLOUD_FORWARD_MAX_ATTEMPTS",
    "3"
))

CLOUD_FORWARD_BACKOFF_SECONDS = float(os.getenv(
    "CLOUD_FORWARD_BACKOFF_SECONDS",
    "0.2"
))

# Wall-clock ceiling across every attempt and backoff sleep combined. Once
# this elapses, no further attempt is started, so the retry loop cannot run
# long enough to outlast the caller's own timeout. Default (4s) leaves
# headroom under the device's fixed 5-second client timeout.
CLOUD_FORWARD_TOTAL_BUDGET_SECONDS = float(os.getenv(
    "CLOUD_FORWARD_TOTAL_BUDGET_SECONDS",
    "4"
))

# Connection-level failures only. A 4xx response is a validation rejection,
# never retried; a 5xx response is treated as retryable further down.
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout
)


class CloudRejected(Exception):
    """The cloud rejected the reading outright (HTTP 4xx). Never retried."""

    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Cloud rejected reading: {status_code} {detail}")


class CloudUnavailable(Exception):
    """The cloud could not be reached, or kept failing after retries."""


# "off" keeps today's plaintext POST. "enabled"/"required" route every reading
# through the ML-KEM secure channel with no plaintext fallback. Read once at
# import, matching the other settings in this module.
#
# app.crypto is imported lazily inside _send_secure rather than at module level
# so that a broken cryptography wheel cannot stop the gateway from starting in
# "off" mode. See docs/security/ml-kem-integration.md, "Residual risks".
ML_KEM_MODE = os.getenv("GATEWAY_ML_KEM_MODE", "off").strip().lower()


def _send_secure(sensor_data: dict) -> dict:
    from app.crypto import send_secure

    return send_secure(sensor_data)


def _observe_attempt(started_at: float, outcome: str) -> None:
    """Record one gateway-to-cloud attempt, not one request.

    A request that succeeds on its third try produces three observations:
    two failures and one success.
    """
    GATEWAY_CLOUD_REQUEST_DURATION_SECONDS.labels(
        outcome=outcome,
        security_mode=ML_KEM_MODE if ML_KEM_MODE in (
            "off", "enabled", "required"
        ) else "off"
    ).observe(time.perf_counter() - started_at)


def send_to_cloud(sensor_data: dict) -> dict:
    deadline = time.monotonic() + CLOUD_FORWARD_TOTAL_BUDGET_SECONDS
    last_error = None

    for attempt in range(1, CLOUD_FORWARD_MAX_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        attempt_timeout = min(CLOUD_REQUEST_TIMEOUT_SECONDS, remaining)

        GATEWAY_CLOUD_RETRY_ATTEMPTS_TOTAL.inc()

        attempt_started = time.perf_counter()

        try:
            if ML_KEM_MODE != "off":
                secure_result = _send_secure(sensor_data)

                _observe_attempt(attempt_started, "success")

                return secure_result

            response = requests.post(
                CLOUD_URL,
                json=sensor_data,
                timeout=attempt_timeout
            )

        except RETRYABLE_EXCEPTIONS as error:
            _observe_attempt(attempt_started, "failure")

            last_error = error

        else:
            if response.status_code < 400:
                _observe_attempt(attempt_started, "success")

                return response.json()

            _observe_attempt(attempt_started, "failure")

            if response.status_code < 500:
                raise CloudRejected(
                    response.status_code,
                    response.text
                )

            last_error = requests.exceptions.HTTPError(
                f"Cloud returned {response.status_code}"
            )

        if attempt < CLOUD_FORWARD_MAX_ATTEMPTS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            backoff = min(
                CLOUD_FORWARD_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                remaining
            )
            time.sleep(backoff)

    # Every attempt is spent. CLOUD_FORWARD_FAILURES_TOTAL stays a
    # once-per-request counter and is incremented by the caller in main.py;
    # this one counts requests that exhausted the whole retry budget.
    GATEWAY_CLOUD_RETRIES_EXHAUSTED_TOTAL.inc()

    raise CloudUnavailable(str(last_error)) from last_error


def check_cloud_health() -> bool:
    try:
        response = requests.get(
            CLOUD_HEALTH_URL,
            timeout=CLOUD_READINESS_TIMEOUT_SECONDS
        )

    except requests.exceptions.RequestException:
        return False

    return response.status_code == 200
