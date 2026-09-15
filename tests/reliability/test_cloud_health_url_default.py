"""Regression tests for the default CLOUD_HEALTH_URL derivation.

The rest of this suite sets CLOUD_HEALTH_URL explicitly (see conftest.py), so
the *default* derivation was never exercised by a test. It was wrong: for the
Compose value CLOUD_URL=http://cloud:8001/data it produced
"http://cloud:8001health" (no slash), and the gateway's /ready endpoint
answered 503 against a perfectly healthy cloud. Found by running the real
Compose stack, not by the unit suite -- these tests close that gap.

_default_cloud_health_url is read directly from source rather than imported,
because importing gateway.app.cloud_client here would trigger a second import
of the gateway `app` package in this process (see conftest.py).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "gateway" / "app" / "cloud_client.py"


def _load_derivation():
    source = SOURCE.read_text()
    match = re.search(
        r"^def _default_cloud_health_url.*?(?=^\S)",
        source,
        re.S | re.M
    )
    assert match, "_default_cloud_health_url not found in cloud_client.py"

    namespace = {}
    exec(match.group(0), namespace)
    return namespace["_default_cloud_health_url"]


derive = _load_derivation()


@pytest.mark.parametrize(
    "cloud_url, expected",
    [
        # The docker-compose.yml value. This is the case that was broken.
        ("http://cloud:8001/data", "http://cloud:8001/health"),
        # The module default when CLOUD_URL is unset.
        ("http://localhost:8001/data", "http://localhost:8001/health"),
        # A base URL with no /data suffix.
        ("http://cloud:8001", "http://cloud:8001/health"),
        # A trailing slash must not produce a doubled slash.
        ("http://cloud:8001/", "http://cloud:8001/health"),
    ]
)
def test_derives_a_well_formed_health_url(cloud_url, expected):
    assert derive(cloud_url) == expected


@pytest.mark.parametrize(
    "cloud_url",
    [
        "http://cloud:8001/data",
        "http://localhost:8001/data",
        "http://cloud:8001",
        "http://cloud:8001/",
    ]
)
def test_host_and_path_are_always_separated_by_a_slash(cloud_url):
    derived = derive(cloud_url)

    assert derived.endswith("/health")
    assert "8001health" not in derived
    assert "//health" not in derived.replace("http://", "")
