"""Shared fixtures for the gateway test suite."""

import os

# `app.cloud_client` reads CLOUD_URL via os.getenv at import time, so the ambient
# environment must be cleared before the application package is imported --
# otherwise an exported CLOUD_URL (as docker-compose sets) changes the module
# constant and the default-value test becomes environment-dependent.
os.environ.pop("CLOUD_URL", None)

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.main import app


@pytest.fixture(scope="session")
def client():
    """A TestClient shared across the whole test session, backed by the real app."""
    return TestClient(app)


@pytest.fixture
def metric_value():
    """A callable that reads a Prometheus counter's current value by sample name.

    Counters live in the process-wide default REGISTRY and persist across
    tests, so callers should read a value before and after an action and
    compare the delta rather than asserting an absolute value.
    """

    def _read(sample_name: str) -> float:
        value = REGISTRY.get_sample_value(sample_name)
        return value if value is not None else 0.0

    return _read
