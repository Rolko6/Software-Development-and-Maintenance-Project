"""Shared fixtures for the end-to-end integration suite.

These tests exercise the real Docker Compose stack (device, gateway, cloud)
over HTTP. They are not unit tests and are skipped from the per-service
suites because each service runs pytest from its own directory; from the
repository root they are selected with `pytest tests/integration -m
integration`, which is what scripts/smoke-test.sh does.
"""

import os
import time

import pytest
import requests

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://localhost:8000")
CLOUD_BASE_URL = os.environ.get("CLOUD_BASE_URL", "http://localhost:8001")

# docker-compose.yml has no healthchecks configured (documented known
# limitation), so readiness must be polled here instead of relied upon.
READINESS_TIMEOUT_SECONDS = 60
READINESS_POLL_INTERVAL_SECONDS = 1


def _service_is_healthy(url: str) -> bool:
    try:
        response = requests.get(url, timeout=2)
    except requests.exceptions.RequestException:
        return False

    return response.status_code == 200


@pytest.fixture(scope="session", autouse=True)
def wait_for_stack():
    """Poll both /health endpoints until they respond or time out.

    Fails the session outright (never skips) so a missing stack is reported
    as a real failure rather than silently passing an empty test run.
    """

    gateway_health_url = f"{GATEWAY_BASE_URL}/health"
    cloud_health_url = f"{CLOUD_BASE_URL}/health"

    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS

    gateway_ready = False
    cloud_ready = False

    while time.monotonic() < deadline:
        gateway_ready = gateway_ready or _service_is_healthy(gateway_health_url)
        cloud_ready = cloud_ready or _service_is_healthy(cloud_health_url)

        if gateway_ready and cloud_ready:
            return

        time.sleep(READINESS_POLL_INTERVAL_SECONDS)

    missing = []
    if not gateway_ready:
        missing.append(f"gateway ({gateway_health_url})")
    if not cloud_ready:
        missing.append(f"cloud ({cloud_health_url})")

    pytest.fail(
        "Docker Compose stack did not become ready within "
        f"{READINESS_TIMEOUT_SECONDS}s: {', '.join(missing)} never responded "
        "to /health. Is `docker compose up --build -d` running?"
    )


@pytest.fixture
def gateway_base_url():
    return GATEWAY_BASE_URL


@pytest.fixture
def cloud_base_url():
    return CLOUD_BASE_URL
