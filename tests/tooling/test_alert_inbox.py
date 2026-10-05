"""The local receiver must persist firing/recovery notifications and reject junk."""
import importlib.util
from pathlib import Path
import threading

import pytest
import requests

SOURCE = Path(__file__).resolve().parents[2] / "monitoring/alert-inbox/server.py"
spec = importlib.util.spec_from_file_location("alert_inbox", SOURCE)
inbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inbox)


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "DB_PATH", tmp_path / "alerts.sqlite3")
    server = inbox.ThreadingHTTPServer(("127.0.0.1", 0), inbox.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(server.server_port)
    server.shutdown()
    server.server_close()
    thread.join()


def test_firing_and_recovery_are_committed_and_read_after_fresh_import(receiver):
    for status in ("firing", "resolved"):
        response = requests.post(receiver + "/alerts", json={"status": status, "alerts": []}, timeout=2)
        assert response.status_code == 200
    fresh_spec = importlib.util.spec_from_file_location("fresh_inbox", SOURCE)
    fresh = importlib.util.module_from_spec(fresh_spec)
    fresh_spec.loader.exec_module(fresh)
    fresh.DB_PATH = inbox.DB_PATH
    assert [r["notification"]["status"] for r in fresh.get_notifications()] == ["resolved", "firing"]


@pytest.mark.parametrize("body", [[], {"status": "invalid"}, {"alerts": []}])
def test_invalid_notifications_are_rejected_without_storage(receiver, body):
    assert requests.post(receiver + "/alerts", json=body, timeout=2).status_code == 400
    assert requests.get(receiver + "/alerts", timeout=2).json() == []


def test_write_failure_is_not_acknowledged(receiver, monkeypatch):
    def fail(payload):
        raise inbox.sqlite3.OperationalError("injected write failure")
    monkeypatch.setattr(inbox, "store_notification", fail)
    assert requests.post(receiver + "/alerts", json={"status": "firing"}, timeout=2).status_code == 503


def test_health_requires_writable_storage_and_does_not_create_notification(receiver, monkeypatch):
    assert requests.get(receiver + "/health", timeout=2).status_code == 200
    assert requests.get(receiver + "/alerts", timeout=2).json() == []
    def fail():
        raise inbox.sqlite3.OperationalError("injected readiness failure")
    monkeypatch.setattr(inbox, "check_storage", fail)
    assert requests.get(receiver + "/health", timeout=2).status_code == 503
