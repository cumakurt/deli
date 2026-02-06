"""Unit tests for stress config loader and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.exceptions import DeliConfigError
from deli.models import StressScenario
from deli.stress_config import load_stress_config


def test_load_stress_config_file_not_found() -> None:
    with pytest.raises(DeliConfigError, match="Stress config file not found"):
        load_stress_config("/nonexistent/stress.yaml")


def test_load_stress_config_valid(tmp_path_stress_config: Path) -> None:
    config = load_stress_config(tmp_path_stress_config)
    assert config.sla_p95_ms == 500
    assert config.sla_p99_ms == 1000
    assert config.initial_users == 5
    assert config.step_users == 5
    assert config.max_users == 100
    assert config.scenario == StressScenario.LINEAR_OVERLOAD


def test_load_stress_config_validation_max_less_than_initial(tmp_path: Path) -> None:
    bad = tmp_path / "stress_bad.yaml"
    bad.write_text(
        "sla_p95_ms: 500\nsla_p99_ms: 1000\nsla_error_rate_pct: 1\n"
        "initial_users: 50\nstep_users: 5\nstep_interval_seconds: 30\nmax_users: 10\n"
    )
    with pytest.raises(DeliConfigError, match="max_users must be >= initial_users"):
        load_stress_config(bad)


def test_load_stress_config_spike_stress_requires_spike_params(tmp_path: Path) -> None:
    bad = tmp_path / "spike_stress_bad.yaml"
    bad.write_text(
        "sla_p95_ms: 500\nsla_p99_ms: 1000\nsla_error_rate_pct: 1\n"
        "initial_users: 5\nstep_users: 5\nstep_interval_seconds: 30\nmax_users: 100\n"
        "scenario: spike_stress\nspike_users: 0\nspike_hold_seconds: 0\n"
    )
    with pytest.raises(DeliConfigError, match="spike_stress"):
        load_stress_config(bad)
