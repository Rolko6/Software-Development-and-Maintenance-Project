"""Fixtures for tests/crypto.

cloud/app and gateway/app are both packages literally named ``app`` living
in separate service directories (matching the existing repo convention,
e.g. cloud/app/main.py does ``from app.models import SensorData``). This
test suite needs to exercise *both* sides in the same pytest process, so a
plain ``sys.path.insert`` + ``import app`` would have the second import
silently reuse the first service's cached ``app`` module.

Instead, each service's ``app`` package tree is loaded once under a private
alias (``_cloud_app`` / `_gateway_app`) via importlib, using
``submodule_search_locations`` so it behaves as a normal package for
subsequent ``importlib.import_module("<alias>.crypto.router")`` calls. This
only works because every module *inside* cloud/app/crypto and
gateway/app/crypto uses **relative** imports (``from . import wire``,
``from ..storage import save_sensor_data``) rather than absolute
``from app... import ...`` imports -- relative imports resolve via the
parent-package chain, which is correct regardless of what name the top
package was registered under. This is deliberate; see the top-of-file
comment in cloud/app/crypto/wire.py and gateway/app/crypto/wire.py.

This file only touches tests/crypto/**; it does not read or modify
tests/conftest.py (owned by another agent) or any file outside this
directory.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Optional

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUD_DIR = REPO_ROOT / "cloud"
GATEWAY_DIR = REPO_ROOT / "gateway"


def _load_app_package(service_dir: Path, alias: str) -> types.ModuleType:
    if alias in sys.modules:
        return sys.modules[alias]
    app_dir = service_dir / "app"
    spec = importlib.util.spec_from_file_location(
        alias,
        app_dir / "__init__.py",
        submodule_search_locations=[str(app_dir)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _import_from(alias: str, dotted: str):
    full_name = f"{alias}.{dotted}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    return importlib.import_module(full_name)


_load_app_package(CLOUD_DIR, "_cloud_app")
_load_app_package(GATEWAY_DIR, "_gateway_app")

cloud_router_module = _import_from("_cloud_app", "crypto.router")
cloud_keys_module = _import_from("_cloud_app", "crypto.keys")
cloud_mode_module = _import_from("_cloud_app", "crypto.mode")
cloud_sessions_module = _import_from("_cloud_app", "crypto.sessions")
cloud_wire_module = _import_from("_cloud_app", "crypto.wire")
cloud_storage_module = _import_from("_cloud_app", "storage")

gateway_client_module = _import_from("_gateway_app", "crypto.client")
gateway_mode_module = _import_from("_gateway_app", "crypto.mode")
gateway_wire_module = _import_from("_gateway_app", "crypto.wire")
gateway_exceptions_module = _import_from("_gateway_app", "crypto.exceptions")


class FakeCloudApp:
    """A minimal FastAPI app wrapping a *fresh* secure router (isolated
    KeyManager + SessionStore) plus a dummy plaintext /data endpoint gated
    by enforce_legacy_mode, so tests can exercise the full integration
    contract (mode switch included) without touching cloud/app/main.py."""

    def __init__(self, key_path: Optional[str] = None, session_ttl_seconds: float = 300.0):
        from fastapi import Depends, FastAPI

        self.key_manager = cloud_keys_module.KeyManager(key_path=key_path)
        self.session_store = cloud_sessions_module.SessionStore(ttl_seconds=session_ttl_seconds)
        self.router = cloud_router_module.create_secure_router(
            key_manager=self.key_manager, session_store=self.session_store
        )

        self.app = FastAPI()
        self.app.include_router(self.router)

        @self.app.post("/data")
        def receive_plaintext_data(
            data: dict, _legacy_gate=Depends(cloud_mode_module.enforce_legacy_mode)
        ):
            cloud_storage_module.save_sensor_data(data)
            return {"status": "stored"}

        @self.app.get("/data")
        def get_all_data():
            return cloud_storage_module.get_all_data()


@pytest.fixture()
def cloud_app(monkeypatch):
    """A fresh cloud app (isolated key + session store) with
    CLOUD_ML_KEM_MODE=enabled by default. Clears cloud storage afterwards."""
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "enabled")
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    cloud_storage_module.stored_data.clear()
    fake = FakeCloudApp()
    yield fake
    cloud_storage_module.stored_data.clear()


@pytest.fixture()
def test_client(cloud_app):
    from fastapi.testclient import TestClient

    with TestClient(cloud_app.app) as client:
        yield client


class _RequestsCompatibleResponse:
    """Adapts an httpx.Response (from FastAPI's TestClient) to the small
    slice of the requests.Response interface SecureCloudClient relies on
    (.status_code, .json(), .raise_for_status()), so that error paths
    exercised through the in-process test transport raise the same
    requests.exceptions.HTTPError that a real `requests.post(...)` against
    the real cloud service would raise -- not httpx's own exception type.
    Production code never goes through this adapter; it always uses real
    `requests` (see client.py's _default_http_get/_default_http_post)."""

    def __init__(self, httpx_response):
        self._response = httpx_response
        self.status_code = httpx_response.status_code
        self.text = httpx_response.text

    def json(self):
        return self._response.json()

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} error for url {self._response.request.url}",
                response=self,
            )


def make_transport(test_client):
    """Build (http_get, http_post) callables that route through a FastAPI
    TestClient instead of a real socket, for use as SecureCloudClient's
    injectable transport in tests."""

    def http_get(url: str, timeout: float):
        return _RequestsCompatibleResponse(test_client.get(url, timeout=timeout))

    def http_post(url: str, json_body: dict, timeout: float):
        return _RequestsCompatibleResponse(test_client.post(url, json=json_body, timeout=timeout))

    return http_get, http_post


@pytest.fixture()
def secure_client(test_client, monkeypatch):
    """A SecureCloudClient wired to `cloud_app`/`test_client` via the
    in-process transport adapter above, with no PSK/pin by default."""
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    monkeypatch.delenv("GATEWAY_ML_KEM_PINNED_EK_FINGERPRINT", raising=False)
    http_get, http_post = make_transport(test_client)
    return gateway_client_module.SecureCloudClient(
        base_url="http://cloud:8001", http_get=http_get, http_post=http_post
    )
