"""Startup checks for the ML-KEM mode and the pre-shared key (S3, S4).

Both services carry an identical copy of app/security_config.py; every test
runs against both copies.
"""

import logging
from pathlib import Path

import pytest

from .conftest import _import_from

cloud_config = _import_from("_cloud_app", "security_config")
gateway_config = _import_from("_gateway_app", "security_config")

BOTH = pytest.mark.parametrize("config", [cloud_config, gateway_config], ids=["cloud", "gateway"])

GOOD_PSK = "a" * 64
BAD_PSKS = {
    "unset": None,
    "empty": "",
    "placeholder": "dev-only-insecure-psk-change-me",
    "short": "b" * 31,
}


def test_both_copies_are_identical():
    assert Path(cloud_config.__file__).read_text() == Path(gateway_config.__file__).read_text()


@BOTH
@pytest.mark.parametrize("raw, expected", [
    (None, "off"),
    ("off", "off"),
    ("enabled", "enabled"),
    ("required", "required"),
    ("  Required ", "required"),
])
def test_valid_modes_are_accepted(config, raw, expected):
    assert config.parse_mode(raw, "X_ML_KEM_MODE") == expected


@BOTH
@pytest.mark.parametrize("raw", ["enabeld", "on", "true", ""])
def test_unknown_mode_is_rejected(config, raw):
    with pytest.raises(config.InsecureConfigurationError, match="X_ML_KEM_MODE"):
        config.parse_mode(raw, "X_ML_KEM_MODE")


@BOTH
@pytest.mark.parametrize("psk", BAD_PSKS.values(), ids=BAD_PSKS.keys())
def test_required_mode_refuses_an_unusable_psk(config, psk, monkeypatch):
    if psk is None:
        monkeypatch.delenv("ML_KEM_PSK", raising=False)
    else:
        monkeypatch.setenv("ML_KEM_PSK", psk)
    with pytest.raises(config.InsecureConfigurationError, match="required"):
        config.check_psk("required", "X_ML_KEM_MODE")


@BOTH
@pytest.mark.parametrize("psk", BAD_PSKS.values(), ids=BAD_PSKS.keys())
def test_enabled_mode_only_warns_about_an_unusable_psk(config, psk, monkeypatch, caplog):
    if psk is None:
        monkeypatch.delenv("ML_KEM_PSK", raising=False)
    else:
        monkeypatch.setenv("ML_KEM_PSK", psk)
    with caplog.at_level(logging.WARNING):
        config.check_psk("enabled", "X_ML_KEM_MODE")
    assert "ML_KEM_PSK" in caplog.text


@BOTH
def test_off_mode_ignores_the_psk(config, monkeypatch, caplog):
    monkeypatch.delenv("ML_KEM_PSK", raising=False)
    with caplog.at_level(logging.WARNING):
        config.check_psk("off", "X_ML_KEM_MODE")
    assert caplog.text == ""


@BOTH
@pytest.mark.parametrize("mode", ["enabled", "required"])
def test_a_real_psk_passes_without_warning(config, mode, monkeypatch, caplog):
    monkeypatch.setenv("ML_KEM_PSK", GOOD_PSK)
    with caplog.at_level(logging.WARNING):
        config.check_psk(mode, "X_ML_KEM_MODE")
    assert caplog.text == ""
