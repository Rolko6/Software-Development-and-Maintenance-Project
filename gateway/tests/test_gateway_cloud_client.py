"""Tests for send_to_cloud() in app/cloud_client.py."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app import cloud_client
from app.cloud_client import send_to_cloud


def test_cloud_url_defaults_to_localhost_when_env_var_unset():
    """CLOUD_URL is "http://localhost:8001/data" when the CLOUD_URL env var is unset.

    CLOUD_URL is read once at import time (os.getenv at module load), so
    setting the env var after the module has already been imported has no
    effect on this value. We therefore do not test env-var override by
    reloading the module. conftest.py pops CLOUD_URL from os.environ before
    app.cloud_client is first imported, so this assertion stays deterministic
    even if the ambient shell/CI (e.g. docker-compose) exports CLOUD_URL.
    """
    assert cloud_client.CLOUD_URL == "http://localhost:8001/data"


def test_send_to_cloud_posts_payload_and_returns_json():
    """send_to_cloud calls requests.post with json=payload and the per-attempt
    timeout min(CLOUD_REQUEST_TIMEOUT_SECONDS, remaining_budget) -- which on a
    fresh call equals CLOUD_REQUEST_TIMEOUT_SECONDS -- returning the parsed JSON."""
    payload = {"device_id": "sensor-1", "temperature": 21.5}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "stored"}

    with patch("app.cloud_client.requests.post", return_value=mock_response) as mock_post:
        result = send_to_cloud(payload)

    assert result == {"status": "stored"}
    mock_post.assert_called_once_with(
        cloud_client.CLOUD_URL,
        json=payload,
        timeout=cloud_client.CLOUD_REQUEST_TIMEOUT_SECONDS
    )


def test_send_to_cloud_raises_cloud_unavailable_after_max_attempts_on_retryable_failure():
    """A retryable failure (e.g. ConnectionError) on every attempt raises
    CloudUnavailable after exactly CLOUD_FORWARD_MAX_ATTEMPTS calls to
    requests.post, with a backoff sleep between attempts but not after the
    last one."""
    with patch(
        "app.cloud_client.requests.post",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ) as mock_post, patch("app.cloud_client.time.sleep") as mock_sleep:
        with pytest.raises(cloud_client.CloudUnavailable):
            send_to_cloud({"device_id": "sensor-1", "temperature": 21.5})

    assert mock_post.call_count == cloud_client.CLOUD_FORWARD_MAX_ATTEMPTS
    assert mock_sleep.call_count == cloud_client.CLOUD_FORWARD_MAX_ATTEMPTS - 1


def test_send_to_cloud_retries_and_recovers_after_one_retryable_failure():
    """A retryable failure on the first attempt followed by a successful
    response returns the parsed JSON, proving the retry actually recovers."""
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {"status": "stored"}

    with patch(
        "app.cloud_client.requests.post",
        side_effect=[requests.exceptions.ConnectionError("boom"), success_response],
    ) as mock_post, patch("app.cloud_client.time.sleep"):
        result = send_to_cloud({"device_id": "sensor-1", "temperature": 21.5})

    assert result == {"status": "stored"}
    assert mock_post.call_count == 2


def test_send_to_cloud_raises_cloud_rejected_on_4xx_response_without_retrying():
    """A 4xx response is a validation rejection: send_to_cloud raises
    CloudRejected immediately, with a single requests.post call and no
    backoff sleep."""
    rejected_response = MagicMock()
    rejected_response.status_code = 422
    rejected_response.text = "Unprocessable Entity"

    with patch(
        "app.cloud_client.requests.post", return_value=rejected_response
    ) as mock_post, patch("app.cloud_client.time.sleep") as mock_sleep:
        with pytest.raises(cloud_client.CloudRejected) as exc_info:
            send_to_cloud({"device_id": "sensor-1", "temperature": 21.5})

    assert mock_post.call_count == 1
    assert exc_info.value.status_code == 422
    mock_sleep.assert_not_called()


def _retry_count(metric_value):
    return metric_value("gateway_cloud_retry_attempts_total")


def test_retry_counter_ignores_a_request_that_succeeds_first_time(metric_value):
    """gateway_cloud_retry_attempts_total counts retries only, not first attempts."""
    ok = MagicMock(status_code=200)
    ok.json.return_value = {"status": "stored"}
    before = _retry_count(metric_value)

    with patch("app.cloud_client.requests.post", return_value=ok):
        send_to_cloud({"device_id": "sensor-1", "temperature": 21.5})

    assert _retry_count(metric_value) - before == 0


def test_retry_counter_counts_each_retry_once(metric_value):
    """Every attempt fails: MAX_ATTEMPTS attempts are MAX_ATTEMPTS - 1 retries."""
    before = _retry_count(metric_value)

    with patch(
        "app.cloud_client.requests.post",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ), patch("app.cloud_client.time.sleep"):
        with pytest.raises(cloud_client.CloudUnavailable):
            send_to_cloud({"device_id": "sensor-1", "temperature": 21.5})

    assert _retry_count(metric_value) - before == cloud_client.CLOUD_FORWARD_MAX_ATTEMPTS - 1
