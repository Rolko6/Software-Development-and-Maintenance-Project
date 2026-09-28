"""Tests for DeviceConfig.from_env() in app/config.py."""

import pytest

from app.config import DeviceConfig


def test_defaults_match_legacy_behaviour_when_env_is_empty():
    """With no env vars set, every field matches the original device.py
    behaviour: 5s interval, 5s timeout, uniform 15-30C."""
    config = DeviceConfig.from_env({})

    assert config.gateway_url == "http://localhost:8000/device-data"
    assert config.device_id == "legacy-sensor-001"
    assert config.send_interval_seconds == 5.0
    assert config.request_timeout_seconds == 5.0
    assert config.temperature_min == 15.0
    assert config.temperature_max == 30.0
    assert config.temperature_model == "uniform"
    assert config.random_seed is None
    assert config.log_level == "INFO"


def test_all_fields_can_be_overridden_via_env():
    env = {
        "GATEWAY_URL": "http://gateway.example/device-data",
        "DEVICE_ID": "sensor-42",
        "SEND_INTERVAL_SECONDS": "2.5",
        "REQUEST_TIMEOUT_SECONDS": "1.5",
        "TEMPERATURE_MIN": "10",
        "TEMPERATURE_MAX": "20",
        "TEMPERATURE_MODEL": "random-walk",
        "RANDOM_SEED": "42",
        "LOG_LEVEL": "DEBUG",
    }

    config = DeviceConfig.from_env(env)

    assert config.gateway_url == "http://gateway.example/device-data"
    assert config.device_id == "sensor-42"
    assert config.send_interval_seconds == 2.5
    assert config.request_timeout_seconds == 1.5
    assert config.temperature_min == 10.0
    assert config.temperature_max == 20.0
    assert config.temperature_model == "random-walk"
    assert config.random_seed == 42
    assert config.log_level == "DEBUG"


def test_non_numeric_send_interval_raises_value_error_naming_the_variable():
    with pytest.raises(ValueError, match="SEND_INTERVAL_SECONDS"):
        DeviceConfig.from_env({"SEND_INTERVAL_SECONDS": "not-a-number"})


def test_zero_send_interval_raises_value_error():
    with pytest.raises(ValueError, match="SEND_INTERVAL_SECONDS"):
        DeviceConfig.from_env({"SEND_INTERVAL_SECONDS": "0"})


def test_negative_send_interval_raises_value_error():
    with pytest.raises(ValueError, match="SEND_INTERVAL_SECONDS"):
        DeviceConfig.from_env({"SEND_INTERVAL_SECONDS": "-1"})


def test_non_numeric_request_timeout_raises_value_error():
    with pytest.raises(ValueError, match="REQUEST_TIMEOUT_SECONDS"):
        DeviceConfig.from_env({"REQUEST_TIMEOUT_SECONDS": "nope"})


def test_zero_request_timeout_raises_value_error():
    with pytest.raises(ValueError, match="REQUEST_TIMEOUT_SECONDS"):
        DeviceConfig.from_env({"REQUEST_TIMEOUT_SECONDS": "0"})


def test_non_numeric_temperature_min_raises_value_error():
    with pytest.raises(ValueError, match="TEMPERATURE_MIN"):
        DeviceConfig.from_env({"TEMPERATURE_MIN": "cold"})


def test_non_numeric_temperature_max_raises_value_error():
    with pytest.raises(ValueError, match="TEMPERATURE_MAX"):
        DeviceConfig.from_env({"TEMPERATURE_MAX": "hot"})


def test_temperature_min_greater_than_max_raises_value_error():
    with pytest.raises(ValueError, match="TEMPERATURE_MIN"):
        DeviceConfig.from_env({"TEMPERATURE_MIN": "30", "TEMPERATURE_MAX": "15"})


def test_temperature_min_equal_to_max_is_allowed():
    config = DeviceConfig.from_env({"TEMPERATURE_MIN": "20", "TEMPERATURE_MAX": "20"})

    assert config.temperature_min == config.temperature_max == 20.0


def test_unknown_temperature_model_raises_value_error():
    with pytest.raises(ValueError, match="TEMPERATURE_MODEL"):
        DeviceConfig.from_env({"TEMPERATURE_MODEL": "quantum"})


def test_non_integer_random_seed_raises_value_error():
    with pytest.raises(ValueError, match="RANDOM_SEED"):
        DeviceConfig.from_env({"RANDOM_SEED": "not-an-int"})


def test_unknown_log_level_raises_value_error():
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        DeviceConfig.from_env({"LOG_LEVEL": "verbose"})


def test_log_level_is_normalised_to_upper_case():
    config = DeviceConfig.from_env({"LOG_LEVEL": "debug"})

    assert config.log_level == "DEBUG"


def test_config_instance_is_frozen():
    config = DeviceConfig.from_env({})

    with pytest.raises(Exception):
        config.device_id = "changed"


def test_from_env_defaults_to_os_environ_when_no_mapping_given(monkeypatch):
    monkeypatch.setenv("DEVICE_ID", "from-os-environ")

    config = DeviceConfig.from_env()

    assert config.device_id == "from-os-environ"


FAULT_VARIABLES = (
    "FAULT_DISCONNECT_RATE",
    "FAULT_POWER_ON_RESET_RATE",
    "FAULT_NAN_RATE",
    "FAULT_STUCK_RATE",
)


def test_ds18b20_temperature_model_is_accepted():
    config = DeviceConfig.from_env({"TEMPERATURE_MODEL": "ds18b20"})

    assert config.temperature_model == "ds18b20"


def test_fault_rates_default_to_zero_so_the_legacy_device_never_misbehaves():
    config = DeviceConfig.from_env({})

    assert config.fault_disconnect_rate == 0.0
    assert config.fault_power_on_reset_rate == 0.0
    assert config.fault_nan_rate == 0.0
    assert config.fault_stuck_rate == 0.0


def test_fault_rates_can_be_set_via_env():
    config = DeviceConfig.from_env({
        "FAULT_DISCONNECT_RATE": "0.05",
        "FAULT_POWER_ON_RESET_RATE": "0.01",
        "FAULT_NAN_RATE": "0.02",
        "FAULT_STUCK_RATE": "0.03",
    })

    assert config.fault_disconnect_rate == 0.05
    assert config.fault_power_on_reset_rate == 0.01
    assert config.fault_nan_rate == 0.02
    assert config.fault_stuck_rate == 0.03


@pytest.mark.parametrize("variable", FAULT_VARIABLES)
@pytest.mark.parametrize("raw", ["-0.1", "1.5", "often"])
def test_fault_rate_outside_zero_to_one_raises_value_error(variable, raw):
    with pytest.raises(ValueError, match=variable):
        DeviceConfig.from_env({variable: raw})


def test_fault_rates_summing_above_one_raise_value_error():
    """Each reading draws at most one fault, so the rates are shares of a
    single probability and together cannot exceed 1."""
    with pytest.raises(ValueError, match="FAULT_"):
        DeviceConfig.from_env({
            "FAULT_DISCONNECT_RATE": "0.6",
            "FAULT_NAN_RATE": "0.6",
        })


def test_fault_rates_summing_to_exactly_one_are_allowed():
    config = DeviceConfig.from_env({
        "FAULT_DISCONNECT_RATE": "0.5",
        "FAULT_NAN_RATE": "0.5",
    })

    assert config.fault_disconnect_rate + config.fault_nan_rate == 1.0


def test_fault_rates_summing_to_one_are_allowed_despite_float_rounding():
    """0.33 + 0.56 + 0.11 is 1.0000000000000002 in floating point."""
    config = DeviceConfig.from_env({
        "FAULT_POWER_ON_RESET_RATE": "0.33",
        "FAULT_NAN_RATE": "0.56",
        "FAULT_STUCK_RATE": "0.11",
    })

    assert config.fault_stuck_rate == 0.11

# Github Actions trigger push