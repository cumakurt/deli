"""YAML configuration loader for deli load tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .exceptions import DeliConfigError
from .logging_config import get_logger
from .models import LoadScenario, RunConfig

logger = get_logger("config")


def _validate_run_config(c: RunConfig) -> None:
    """Validate RunConfig bounds. Raises DeliConfigError if invalid."""
    if c.users < 1:
        raise DeliConfigError("users must be >= 1")
    if c.duration_seconds <= 0:
        raise DeliConfigError("duration_seconds must be > 0")
    if c.ramp_up_seconds < 0:
        raise DeliConfigError("ramp_up_seconds must be >= 0")
    if c.iterations < 0:
        raise DeliConfigError("iterations must be >= 0")
    if c.think_time_ms < 0:
        raise DeliConfigError("think_time_ms must be >= 0")
    if c.spike_users < 0:
        raise DeliConfigError("spike_users must be >= 0")
    if c.spike_duration_seconds < 0:
        raise DeliConfigError("spike_duration_seconds must be >= 0")
    if c.sla_p95_ms is not None and c.sla_p95_ms <= 0:
        raise DeliConfigError("sla_p95_ms must be > 0 when set")
    if c.sla_p99_ms is not None and c.sla_p99_ms <= 0:
        raise DeliConfigError("sla_p99_ms must be > 0 when set")
    if c.sla_error_rate_pct is not None and (c.sla_error_rate_pct < 0 or c.sla_error_rate_pct > 100):
        raise DeliConfigError("sla_error_rate_pct must be between 0 and 100 when set")
    if c.scenario == LoadScenario.SPIKE and (c.spike_users <= 0 or c.spike_duration_seconds <= 0):
        raise DeliConfigError("spike scenario requires spike_users > 0 and spike_duration_seconds > 0")


def load_config(path: str | Path) -> RunConfig:
    """Load run configuration from YAML file.
    
    Args:
        path: Path to YAML configuration file
    
    Returns:
        Validated RunConfig instance
    
    Raises:
        DeliConfigError: If file not found, invalid YAML, or validation fails
    """
    p = Path(path)
    if not p.exists():
        raise DeliConfigError(
            f"Config file not found: {path}",
            context={"path": str(path)}
        )

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        logger.exception("Failed to parse YAML config file")
        raise DeliConfigError(
            f"Invalid YAML syntax in config file: {e}",
            context={"path": str(path)},
            original_error=e
        ) from e
    except OSError as e:
        logger.exception("Failed to read config file")
        raise DeliConfigError(
            f"Cannot read config file: {e}",
            context={"path": str(path)},
            original_error=e
        ) from e

    if not isinstance(raw, dict):
        raise DeliConfigError(
            "Config must be a YAML object/dictionary",
            context={"path": str(path), "actual_type": type(raw).__name__}
        )

    scenario_str = (raw.get("scenario") or "constant").strip().lower()
    try:
        scenario = LoadScenario(scenario_str)
    except ValueError:
        logger.debug("Unknown scenario '%s', defaulting to 'constant'", scenario_str)
        scenario = LoadScenario.CONSTANT

    try:
        config = RunConfig(
            users=int(raw.get("users", 10)),
            ramp_up_seconds=float(raw.get("ramp_up_seconds", 10)),
            duration_seconds=float(raw.get("duration_seconds", 60)),
            iterations=int(raw.get("iterations", 0)),
            think_time_ms=float(raw.get("think_time_ms", 0)),
            scenario=scenario,
            spike_users=int(raw.get("spike_users", 0)),
            spike_duration_seconds=float(raw.get("spike_duration_seconds", 0)),
            sla_p95_ms=_optional_float(raw, "sla_p95_ms"),
            sla_p99_ms=_optional_float(raw, "sla_p99_ms"),
            sla_error_rate_pct=_optional_float(raw, "sla_error_rate_pct"),
        )
    except (TypeError, ValueError) as e:
        raise DeliConfigError(
            f"Invalid config value: {e}",
            context={"path": str(path)},
            original_error=e
        ) from e

    _validate_run_config(config)
    logger.debug("Loaded config: users=%s, duration=%s, scenario=%s", config.users, config.duration_seconds, config.scenario.value)
    return config


def validate_run_config(config: RunConfig) -> None:
    """Validate RunConfig. Raises DeliConfigError if invalid."""
    _validate_run_config(config)


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    v = data.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
