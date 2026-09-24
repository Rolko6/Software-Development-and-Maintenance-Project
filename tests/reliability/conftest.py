"""Fixtures for the gateway/cloud reliability suite (work package 2).

Scope: this directory tests the gateway and cloud FastAPI services described
in gateway/app/ and cloud/app/, in-process and without Docker or real
network calls. It is deliberately a subdirectory with its own conftest.py
(rather than adding to the root tests/conftest.py or tests/support.py, which
belong to the ML-KEM verification suite) so this work never has to touch
files owned by that suite.

Import collision: gateway/app/ and cloud/app/ both define a top-level
package literally named `app` (matching how their Dockerfiles run
`uvicorn app.main:app` from inside each service directory). Importing both
in one pytest process would collide on the bare name `app`, so each service
is imported exactly once per session and its modules are re-homed under a
private alias (`gateway_app`, `cloud_app`) immediately afterwards. Gateway
also registers Prometheus counters at import time in the global registry;
importing it more than once in one process raises "Duplicate timeseries",
which is another reason each service is imported exactly once (session
scope) rather than per test.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_ROOT = REPO_ROOT / "gateway"
CLOUD_ROOT = REPO_ROOT / "cloud"

# Hard-set (not setdefault) so test configuration is deterministic and does
# not depend on whatever happens to be in the host/CI environment. These are
# read once, at import time, by the module-level constants in
# gateway/app/cloud_client.py and cloud/app/storage.py -- which is why they
# must be set here, before the session-scoped fixtures below trigger the
# first (and only) import of each service.
os.environ["CLOUD_URL"] = "http://cloud.test/data"
os.environ["CLOUD_HEALTH_URL"] = "http://cloud.test/health"
os.environ["CLOUD_REQUEST_TIMEOUT_SECONDS"] = "1"
os.environ["CLOUD_READINESS_TIMEOUT_SECONDS"] = "2"
os.environ["CLOUD_FORWARD_MAX_ATTEMPTS"] = "3"
# Real production default is 0.2s (see gateway/app/cloud_client.py); zeroed
# here so retry tests do not spend wall-clock time sleeping.
os.environ["CLOUD_FORWARD_BACKOFF_SECONDS"] = "0"
os.environ["CLOUD_FORWARD_TOTAL_BUDGET_SECONDS"] = "4"
# Small on purpose so the bounded-retention test can prove eviction without
# writing thousands of readings. Production default is 1000 (see
# cloud/app/storage.py).
os.environ["CLOUD_MAX_STORED_READINGS"] = "5"


def _import_service_app(service_root: Path, alias: str):
    """Import a service's `app` package under a private alias.

    Returns the service's `app.main` module (accessible afterwards as
    `sys.modules["<alias>.main"]`).

    Other suites in this repository also insert a service directory onto
    sys.path for their own bare `import app` (e.g.
    tests/protected_path/test_protected_path_contract.py, which imports
    gateway/app deliberately and can leave a bare "app" entry behind when a
    submodule import inside it is skipped). Rather than assume nothing else
    ever touches the bare "app" name, any such entry is temporarily
    detached before this import and restored afterwards, so this suite
    borrows the name instead of permanently evicting whatever another
    suite left there.
    """
    main_alias = f"{alias}.main"
    if main_alias in sys.modules:
        return sys.modules[main_alias]

    stashed = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "app" or name.startswith("app.")
    }

    root_str = str(service_root)
    sys.path.insert(0, root_str)
    try:
        main_module = importlib.import_module("app.main")

        # Warm caches that key off sys.modules[cls.__module__] (FastAPI's
        # OpenAPI schema generation, pydantic model rebuilds) *before* the
        # module is renamed below and the "app.*" names stop resolving.
        # main_module.app is the FastAPI instance; .openapi() builds and
        # caches the schema on first call.
        main_module.app.openapi()
    finally:
        sys.path.remove(root_str)

    renamed = [name for name in sys.modules if name == "app" or name.startswith("app.")]
    for name in renamed:
        new_name = alias + name[len("app"):]
        sys.modules[new_name] = sys.modules.pop(name)

    sys.modules.update(stashed)

    return sys.modules[main_alias]


@pytest.fixture(scope="session")
def gateway_main():
    return _import_service_app(GATEWAY_ROOT, "gateway_app")


@pytest.fixture(scope="session")
def cloud_main():
    return _import_service_app(CLOUD_ROOT, "cloud_app")


@pytest.fixture(scope="session")
def gateway_app(gateway_main):
    return gateway_main.app


@pytest.fixture(scope="session")
def cloud_app(cloud_main):
    return cloud_main.app


@pytest.fixture()
def gateway_client(gateway_app):
    return TestClient(gateway_app)


@pytest.fixture()
def cloud_test_client(cloud_app):
    return TestClient(cloud_app)


@pytest.fixture(autouse=True)
def _reset_cloud_storage(cloud_main):
    """Isolate cloud storage between tests.

    Depends on cloud_main so the cloud app -- and hence its storage module --
    is guaranteed to be imported (once) before the reset runs, including for
    the very first cloud-touching test in the session.
    """
    storage = importlib.import_module("cloud_app.storage")
    storage.clear_data()
    yield
    storage.clear_data()


def counter_value(counter) -> float:
    """Current total of a prometheus_client Counter, via the public API.

    Used for delta-based assertions instead of assuming a counter starts at
    zero, since gateway metrics are process-global and shared across tests
    in this session.
    """
    metric_family = next(iter(counter.collect()))
    return next(
        sample.value
        for sample in metric_family.samples
        if sample.name.endswith("_total")
    )
