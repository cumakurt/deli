"""Unit tests for CLI (_parse_env_args, main exit codes)."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from deli.cli import _parse_env_args, main


def test_parse_env_args_empty() -> None:
    assert _parse_env_args(None) == {}
    assert _parse_env_args([]) == {}


def test_parse_env_args_single() -> None:
    assert _parse_env_args(["key=value"]) == {"key": "value"}


def test_parse_env_args_multiple() -> None:
    out = _parse_env_args(["a=1", "b=2", "base_url=https://api.example.com"])
    assert out == {"a": "1", "b": "2", "base_url": "https://api.example.com"}


def test_parse_env_args_no_equals_ignored() -> None:
    out = _parse_env_args(["novalue", "key=val"])
    assert out == {"key": "val"}


def test_parse_env_args_strips() -> None:
    out = _parse_env_args(["  key  =  value  "])
    assert out == {"key": "value"}


def test_main_version_exits_zero() -> None:
    with patch.object(sys, "argv", ["deli", "--version"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_main_missing_config_exits_one() -> None:
    with patch.object(sys, "argv", ["deli", "-f", "/nonexistent/config.yaml"]):
        code = main()
        assert code == 1


def test_main_help_exits_zero() -> None:
    with patch.object(sys, "argv", ["deli", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_main_stress_mode_requires_target(tmp_path: Path) -> None:
    config = tmp_path / "stress.yaml"
    config.write_text(
        "sla_p95_ms: 500\nsla_p99_ms: 1000\nsla_error_rate_pct: 1\n"
        "initial_users: 5\nstep_users: 5\nstep_interval_seconds: 30\nmax_users: 100\n"
    )
    with patch.object(sys, "argv", ["deli", "-s", "-f", str(config)]):
        code = main()
        assert code == 1


def test_main_postman_mode_requires_collection(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("users: 5\nduration_seconds: 10\nscenario: constant\n")
    with patch.object(sys, "argv", ["deli", "-f", str(config)]):
        code = main()
        assert code == 1
