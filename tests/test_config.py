"""Unit tests for config loader and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.config import load_config
from deli.exceptions import DeliConfigError
from deli.models import LoadScenario


def test_load_config_file_not_found() -> None:
    with pytest.raises(DeliConfigError, match="Config file not found"):
        load_config("/nonexistent/config.yaml")


def test_load_config_valid(tmp_path_config_constant: Path) -> None:
    config = load_config(tmp_path_config_constant)
    assert config.users == 10
    assert config.ramp_up_seconds == 5
    assert config.duration_seconds == 60
    assert config.scenario == LoadScenario.CONSTANT
    assert config.iterations == 0
    assert config.think_time_ms == 0


def test_load_config_spike(tmp_path_config_spike: Path) -> None:
    config = load_config(tmp_path_config_spike)
    assert config.scenario == LoadScenario.SPIKE
    assert config.spike_users == 30
    assert config.spike_duration_seconds == 15


def test_load_config_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: yaml: [")
    with pytest.raises(DeliConfigError, match="Invalid YAML syntax"):
        load_config(bad)


def test_load_config_validation_users_zero(tmp_path: Path) -> None:
    bad = tmp_path / "zero_users.yaml"
    bad.write_text("users: 0\nduration_seconds: 60\nscenario: constant\n")
    with pytest.raises(DeliConfigError, match="users must be >= 1"):
        load_config(bad)


def test_load_config_validation_duration_zero(tmp_path: Path) -> None:
    bad = tmp_path / "zero_duration.yaml"
    bad.write_text("users: 5\nduration_seconds: 0\nscenario: constant\n")
    with pytest.raises(DeliConfigError, match="duration_seconds must be > 0"):
        load_config(bad)


def test_load_config_validation_spike_missing_params(tmp_path: Path) -> None:
    bad = tmp_path / "spike_bad.yaml"
    bad.write_text("users: 10\nduration_seconds: 60\nscenario: spike\nspike_users: 0\nspike_duration_seconds: 0\n")
    with pytest.raises(DeliConfigError, match="spike scenario requires"):
        load_config(bad)


def test_load_config_sla_optional(tmp_path: Path) -> None:
    content = "users: 5\nduration_seconds: 30\nscenario: constant\nsla_p95_ms: 400\nsla_p99_ms: 800\n"
    f = tmp_path / "sla.yaml"
    f.write_text(content)
    config = load_config(f)
    assert config.sla_p95_ms == 400
    assert config.sla_p99_ms == 800
