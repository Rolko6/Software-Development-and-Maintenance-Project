import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.config import LEGACY_INGESTION_ENV, load_allow_legacy_ingestion


CLOUD_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_ingestion_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv(LEGACY_INGESTION_ENV, raising=False)

    assert load_allow_legacy_ingestion() is False


@pytest.mark.parametrize(
    "configured_value, expected",
    [
        ("true", True),
        (" TRUE ", True),
        ("false", False),
        (" False ", False),
    ],
)
def test_legacy_ingestion_accepts_only_boolean_words(
    monkeypatch,
    configured_value,
    expected,
):
    monkeypatch.setenv(LEGACY_INGESTION_ENV, configured_value)

    assert load_allow_legacy_ingestion() is expected


@pytest.mark.parametrize("configured_value", ["", "1", "yes", "enabled"])
def test_legacy_ingestion_rejects_invalid_values(monkeypatch, configured_value):
    monkeypatch.setenv(LEGACY_INGESTION_ENV, configured_value)

    with pytest.raises(RuntimeError, match=LEGACY_INGESTION_ENV):
        load_allow_legacy_ingestion()


@pytest.mark.parametrize("configured_value", ["", "yes"])
def test_invalid_legacy_ingestion_setting_stops_app_import(configured_value):
    environment = os.environ.copy()
    environment[LEGACY_INGESTION_ENV] = configured_value
    environment["PYTHONPATH"] = str(CLOUD_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=CLOUD_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert LEGACY_INGESTION_ENV in result.stderr


def test_true_legacy_ingestion_setting_allows_app_import():
    environment = os.environ.copy()
    environment[LEGACY_INGESTION_ENV] = "true"
    environment["PYTHONPATH"] = str(CLOUD_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=CLOUD_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", ["", " ", ":memory:"])
def test_transient_storage_path_stops_app_import(path):
    environment = dict(os.environ, CLOUD_DB_PATH=path, PYTHONPATH=str(CLOUD_ROOT))
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"], cwd=CLOUD_ROOT, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "CLOUD_DB_PATH" in result.stderr
