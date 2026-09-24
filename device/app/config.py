# Reads and validates the device's runtime configuration from environment
# variables, keeping every default equal to today's observed behaviour.

import os
from dataclasses import dataclass
from typing import Mapping, Optional


KNOWN_TEMPERATURE_MODELS = ("uniform", "random-walk")


KNOWN_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


@dataclass(frozen=True)
class DeviceConfig:
    gateway_url: str
    device_id: str
    send_interval_seconds: float
    request_timeout_seconds: float
    temperature_min: float
    temperature_max: float
    temperature_model: str
    random_seed: Optional[int]
    log_level: str

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "DeviceConfig":
        source = env if env is not None else os.environ

        gateway_url = source.get(
            "GATEWAY_URL",
            "http://localhost:8000/device-data"
        )

        device_id = source.get(
            "DEVICE_ID",
            "legacy-sensor-001"
        )

        send_interval_seconds = _parse_positive_float(
            source,
            "SEND_INTERVAL_SECONDS",
            "5.0"
        )

        request_timeout_seconds = _parse_positive_float(
            source,
            "REQUEST_TIMEOUT_SECONDS",
            "5.0"
        )

        temperature_min = _parse_float(
            source,
            "TEMPERATURE_MIN",
            "15.0"
        )

        temperature_max = _parse_float(
            source,
            "TEMPERATURE_MAX",
            "30.0"
        )

        if temperature_min > temperature_max:
            raise ValueError(
                "TEMPERATURE_MIN must be less than or equal to TEMPERATURE_MAX, "
                f"got TEMPERATURE_MIN={temperature_min!r} and TEMPERATURE_MAX={temperature_max!r}"
            )

        temperature_model = source.get(
            "TEMPERATURE_MODEL",
            "uniform"
        )

        if temperature_model not in KNOWN_TEMPERATURE_MODELS:
            raise ValueError(
                f"TEMPERATURE_MODEL must be one of {KNOWN_TEMPERATURE_MODELS}, "
                f"got {temperature_model!r}"
            )

        random_seed = _parse_optional_int(
            source,
            "RANDOM_SEED"
        )

        log_level = source.get(
            "LOG_LEVEL",
            "INFO"
        ).upper()

        if log_level not in KNOWN_LOG_LEVELS:
            raise ValueError(
                f"LOG_LEVEL must be one of {KNOWN_LOG_LEVELS}, "
                f"got {log_level!r}"
            )

        return cls(
            gateway_url=gateway_url,
            device_id=device_id,
            send_interval_seconds=send_interval_seconds,
            request_timeout_seconds=request_timeout_seconds,
            temperature_min=temperature_min,
            temperature_max=temperature_max,
            temperature_model=temperature_model,
            random_seed=random_seed,
            log_level=log_level
        )


def _parse_float(source: Mapping[str, str], name: str, default: str) -> float:
    raw = source.get(name, default)

    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} must be a number, got {raw!r}"
        )


def _parse_positive_float(source: Mapping[str, str], name: str, default: str) -> float:
    value = _parse_float(source, name, default)

    if value <= 0:
        raise ValueError(
            f"{name} must be a positive number, got {value!r}"
        )

    return value


def _parse_optional_int(source: Mapping[str, str], name: str) -> Optional[int]:
    raw = source.get(name)

    if raw is None:
        return None

    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"{name} must be an integer, got {raw!r}"
        )
