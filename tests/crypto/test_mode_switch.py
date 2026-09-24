"""The off / enabled / required migration mode switch, on both services.

FakeCloudApp (see conftest.py) mounts a dummy plaintext POST /data endpoint
gated by the real `enforce_legacy_mode` dependency from
cloud/app/crypto/mode.py -- the exact dependency the integration patch adds
to cloud/app/main.py's real /data route (see docs/security/
ml-kem-integration.md, "Integration steps for the main agent"). This lets
us test the "required mode rejects plaintext" contract without touching
cloud/app/main.py, which this task must not edit.
"""

from .conftest import FakeCloudApp, gateway_mode_module


def test_default_cloud_mode_is_off(monkeypatch):
    monkeypatch.delenv("CLOUD_ML_KEM_MODE", raising=False)
    from .conftest import cloud_mode_module

    assert cloud_mode_module.get_cloud_mode() == "off"


def test_default_gateway_mode_is_off(monkeypatch):
    monkeypatch.delenv("GATEWAY_ML_KEM_MODE", raising=False)
    assert gateway_mode_module.get_gateway_mode() == "off"
    assert gateway_mode_module.secure_channel_enabled() is False


def test_invalid_mode_value_falls_back_to_off(monkeypatch):
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "bogus-value")
    from .conftest import cloud_mode_module

    assert cloud_mode_module.get_cloud_mode() == "off"


def test_gateway_enabled_and_required_both_use_secure_channel(monkeypatch):
    monkeypatch.setenv("GATEWAY_ML_KEM_MODE", "enabled")
    assert gateway_mode_module.secure_channel_enabled() is True
    monkeypatch.setenv("GATEWAY_ML_KEM_MODE", "required")
    assert gateway_mode_module.secure_channel_enabled() is True


def test_mode_off_accepts_plaintext_and_secure_endpoints_are_disabled(monkeypatch):
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "off")
    from fastapi.testclient import TestClient

    fake = FakeCloudApp()
    with TestClient(fake.app) as client:
        plaintext = client.post("/data", json={"device_id": "d1", "temperature": 1.0})
        assert plaintext.status_code == 200

        secure = client.get("http://cloud:8001/secure/handshake")
        assert secure.status_code == 403


def test_mode_enabled_accepts_both_plaintext_and_secure(monkeypatch):
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "enabled")
    from fastapi.testclient import TestClient

    fake = FakeCloudApp()
    with TestClient(fake.app) as client:
        plaintext = client.post("/data", json={"device_id": "d1", "temperature": 1.0})
        assert plaintext.status_code == 200

        handshake_info = client.get("http://cloud:8001/secure/handshake")
        assert handshake_info.status_code == 200


def test_mode_required_rejects_plaintext_post(monkeypatch):
    monkeypatch.setenv("CLOUD_ML_KEM_MODE", "required")
    from fastapi.testclient import TestClient

    fake = FakeCloudApp()
    with TestClient(fake.app) as client:
        plaintext = client.post("/data", json={"device_id": "d1", "temperature": 1.0})
        assert plaintext.status_code == 403

        handshake_info = client.get("http://cloud:8001/secure/handshake")
        assert handshake_info.status_code == 200
