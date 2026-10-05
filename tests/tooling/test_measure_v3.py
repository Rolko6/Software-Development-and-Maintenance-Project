"""Regression checks for PR #14's port: missing metrics must not imply reuse."""
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/evaluation/measure_v3.py"
spec = importlib.util.spec_from_file_location("measure_v3", SCRIPT)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_missing_metrics_are_rejected_not_classified_as_reused_session():
    with pytest.raises(m.MeasurementError, match="not valid Prometheus"):
        m.metric_values("Not Found", ("secure_data_received_total",))


def test_labelled_counter_family_before_first_fault_is_zero():
    text = '# HELP secure_data_rejected_total rejected\n# TYPE secure_data_rejected_total counter\n'
    assert m.metric_values(text, ("secure_data_rejected_total",)) == {"secure_data_rejected_total": 0}


def test_labelled_faults_are_aggregated_and_created_timestamps_excluded():
    text = '''# TYPE secure_data_rejected_total counter
secure_data_rejected_total{reason="decryption_failed"} 2
secure_data_rejected_total{reason="stale_timestamp"} 3
secure_data_rejected_created{reason="stale_timestamp"} 1000
'''
    assert m.metric_values(text, ("secure_data_rejected_total",))["secure_data_rejected_total"] == 5


def test_reset_cannot_be_reported_as_no_fault():
    with pytest.raises(m.MeasurementError, match="reset"):
        m.increase({"x": 4}, {"x": 0}, "x")


@pytest.mark.parametrize("value", ["NaN", "Inf", "-1"])
def test_invalid_counter_values_are_rejected(value):
    with pytest.raises(m.MeasurementError, match="negative or non-finite"):
        m.metric_values(f"# TYPE x_total counter\nx_total {value}\n", ("x_total",))


def test_latency_excludes_failures_and_uses_nearest_rank_p95():
    records = [{"status": 200, "latency_ms": n, "error": None} for n in range(1, 21)]
    records.append({"status": 502, "latency_ms": 999, "error": None})
    summary = m.latency_summary(records)
    assert summary["median_ms"] == 10.5 and summary["p95_ms"] == 19
    assert summary["failures"] == {"502": 1} and summary["max_ms"] == 20


def test_delivery_separates_outage_rejection_from_restart_storage_loss():
    records = [{"device_id": k, "status": s} for k, s in [("a", 200), ("b", 502), ("c", 200)]]
    summary = m.delivery_counts(records, Counter(c=1), Counter(a=1))
    assert summary["missing_final"] == 2 and summary["never_observed"] == 1
    assert summary["lost_across_restart"] == 1 and summary["acknowledged_never_observed"] == 0
    assert summary["failed_but_observed"] == 0


def test_duplicates_and_unrelated_background_readings_are_separated():
    records = [{"device_id": "a", "status": 200}]
    summary = m.delivery_counts(records, Counter(a=2, unrelated=100), Counter())
    assert summary["stored_final_unique"] == 1 and summary["duplicate_records_final"] == 1


def test_success_cannot_be_claimed_without_secure_receipt(monkeypatch):
    class FakeStack:
        def metrics(self, *args):
            return {"secure_data_received_total": 0}

        def send(self, *args):
            return {"status": 200, "latency_ms": 1}

    with pytest.raises(m.MeasurementError, match="secure receipt delta"):
        m.latency(FakeStack(), 3)


def test_interruption_requires_project_and_explicit_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        m.main(["recovery", "--gateway-url", "http://127.0.0.1:1", "--cloud-url",
                "http://127.0.0.1:2", "--json-out", str(tmp_path / "out.json")])
    assert exc.value.code == 2


def test_wrong_compose_port_cannot_be_stopped(monkeypatch):
    import json
    calls = []

    def inspect(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "docker" and cmd[1] == "inspect":
            return json.dumps([{"Config": {"Labels": {"com.docker.compose.project": "test"}},
                                "NetworkSettings": {"Ports": {"8000/tcp": [{"HostPort": "1234"}]}}}])
        return "container"

    monkeypatch.setattr(m.subprocess, "check_output", inspect)
    stack = m.Stack("http://127.0.0.1:9999", "http://127.0.0.1:8888", project="test")
    with pytest.raises(m.MeasurementError, match="URL does not match"):
        stack.verify_control_target()
    assert not any("stop" in cmd or "restart" in cmd for cmd in calls)


def test_well_formed_metrics_without_v3_receipt_counter_are_rejected():
    with pytest.raises(m.MeasurementError, match="required v3 counters absent"):
        m.metric_values("# TYPE other_total counter\nother_total 3\n", ("secure_data_received_total",))
