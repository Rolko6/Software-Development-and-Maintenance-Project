"""Tests for the Prometheus counters and the mounted /metrics/ ASGI app."""

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY


VALID_PAYLOAD = {"device_id": "sensor-1", "temperature": 21.5}


def test_successful_forward_increments_messages_not_failures(client, metric_value):
    """A successful post increments device_messages_total by 1 and leaves failures unchanged."""
    messages_before = metric_value("device_messages_total")
    failures_before = metric_value("cloud_forward_failures_total")

    with patch("app.main.send_to_cloud", return_value={"status": "stored"}):
        response = client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert metric_value("device_messages_total") - messages_before == 1
    assert metric_value("cloud_forward_failures_total") - failures_before == 0


def test_failed_forward_increments_both_counters(client, metric_value):
    """A failing forward increments both device_messages_total and cloud_forward_failures_total by 1."""
    messages_before = metric_value("device_messages_total")
    failures_before = metric_value("cloud_forward_failures_total")

    with patch("app.main.send_to_cloud", side_effect=RuntimeError("network down")):
        response = client.post("/device-data", json=VALID_PAYLOAD)

    assert response.status_code == 502
    assert metric_value("device_messages_total") - messages_before == 1
    assert metric_value("cloud_forward_failures_total") - failures_before == 1


def test_validation_rejection_increments_neither_counter(client, metric_value):
    """A 422-rejected post increments neither counter: validation runs before the counters are touched."""
    messages_before = metric_value("device_messages_total")
    failures_before = metric_value("cloud_forward_failures_total")

    with patch("app.main.send_to_cloud") as mock_send:
        response = client.post(
            "/device-data",
            json={"device_id": "", "temperature": 21.5}
        )

    assert response.status_code == 422
    mock_send.assert_not_called()
    assert metric_value("device_messages_total") - messages_before == 0
    assert metric_value("cloud_forward_failures_total") - failures_before == 0


@pytest.mark.parametrize(
    "body",
    [
        '{"device_id":"broken-sensor","temperature":-127.0}',
        '{"device_id":"broken-sensor","temperature":85.0}',
        '{"device_id":"broken-sensor","temperature":NaN}',
    ],
    ids=["ds18b20_disconnected", "ds18b20_power_on_reset", "failed_read_nan"],
)
def test_validation_rejection_is_counted_as_rejected_validation(client, body):
    """Every reading the gateway rejects is visible in
    gateway_delivery_outcome_total{outcome="rejected_validation"}, as
    documented in app/metrics.py, so a faulty sensor shows up in monitoring."""
    sample = 'gateway_delivery_outcome_total'
    labels = {"outcome": "rejected_validation"}
    before = REGISTRY.get_sample_value(sample, labels) or 0.0

    response = client.post(
        "/device-data",
        content=body,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert (REGISTRY.get_sample_value(sample, labels) or 0.0) - before == 1


def test_metrics_endpoint_exposes_both_counter_names(client):
    """GET /metrics/ (with trailing slash) returns 200 and lists both counter names."""
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert "device_messages_total" in response.text
    assert "cloud_forward_failures_total" in response.text
