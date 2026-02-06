"""Stress test YAML configuration loader (industry-style thresholds)."""

from __future__ import annotations

from pathlib import Path

import yaml

from .exceptions import DeliConfigError
from .logging_config import get_logger
from .models import StressConfig, StressScenario

logger = get_logger("stress_config")


def _validate_stress_config(c: StressConfig) -> None:
    """Validate StressConfig bounds. Raises DeliConfigError if invalid."""
    if c.sla_p95_ms <= 0 or c.sla_p99_ms <= 0:
        raise DeliConfigError("sla_p95_ms and sla_p99_ms must be > 0")
    if not 0 <= c.sla_error_rate_pct <= 100:
        raise DeliConfigError("sla_error_rate_pct must be between 0 and 100")
    if not 0 <= c.sla_timeout_rate_pct <= 100:
        raise DeliConfigError("sla_timeout_rate_pct must be between 0 and 100")
    if c.initial_users < 1:
        raise DeliConfigError("initial_users must be >= 1")
    if c.step_users < 1:
        raise DeliConfigError("step_users must be >= 1")
    if c.step_interval_seconds <= 0:
        raise DeliConfigError("step_interval_seconds must be > 0")
    if c.max_users < c.initial_users:
        raise DeliConfigError("max_users must be >= initial_users")
    if c.think_time_ms < 0:
        raise DeliConfigError("think_time_ms must be >= 0")
    if c.scenario == StressScenario.SPIKE_STRESS and (c.spike_users <= 0 or c.spike_hold_seconds <= 0):
        raise DeliConfigError("spike_stress scenario requires spike_users > 0 and spike_hold_seconds > 0")
    if c.scenario == StressScenario.SOAK_STRESS and (c.soak_users <= 0 or c.soak_duration_seconds <= 0):
        raise DeliConfigError("soak_stress scenario requires soak_users > 0 and soak_duration_seconds > 0")


def load_stress_config(path: str | Path) -> StressConfig:
    """Load stress test configuration from YAML file. Raises DeliConfigError on invalid config."""
    p = Path(path)
    if not p.exists():
        raise DeliConfigError(f"Stress config file not found: {path}")

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.exception("Failed to read stress config file")
        raise DeliConfigError(f"Failed to load stress config: {e}") from e

    if not isinstance(raw, dict):
        raise DeliConfigError("Stress config must be a YAML object")

    scenario_str = (raw.get("scenario") or "linear_overload").strip().lower()
    try:
        scenario = StressScenario(scenario_str)
    except ValueError:
        scenario = StressScenario.LINEAR_OVERLOAD

    try:
        config = StressConfig(
            sla_p95_ms=float(raw.get("sla_p95_ms", 500)),
            sla_p99_ms=float(raw.get("sla_p99_ms", 1000)),
            sla_error_rate_pct=float(raw.get("sla_error_rate_pct", 1.0)),
            sla_timeout_rate_pct=float(raw.get("sla_timeout_rate_pct", 5.0)),
            initial_users=int(raw.get("initial_users", 5)),
            step_users=int(raw.get("step_users", 5)),
            step_interval_seconds=float(raw.get("step_interval_seconds", 30)),
            max_users=int(raw.get("max_users", 200)),
            think_time_ms=float(raw.get("think_time_ms", 0)),
            scenario=scenario,
            spike_users=int(raw.get("spike_users", 0)),
            spike_hold_seconds=float(raw.get("spike_hold_seconds", 30)),
            soak_users=int(raw.get("soak_users", 0)),
            soak_duration_seconds=float(raw.get("soak_duration_seconds", 60)),
        )
    except (TypeError, ValueError) as e:
        raise DeliConfigError(f"Invalid stress config value: {e}") from e

    _validate_stress_config(config)
    logger.debug("Loaded stress config: scenario=%s, initial_users=%s, max_users=%s", config.scenario.value, config.initial_users, config.max_users)
    return config
