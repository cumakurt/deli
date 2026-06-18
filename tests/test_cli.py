"""Unit tests for CLI (_parse_env_args, main exit codes)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

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


def test_main_environment_requires_collection(tmp_path: Path) -> None:
    env = tmp_path / "environment.json"
    env.write_text('{"values": []}')
    with patch.object(sys, "argv", ["deli", "-m", "https://example.com", "-E", str(env)]):
        code = main()
        assert code == 1


def test_main_test_mode_requires_collection() -> None:
    with patch.object(sys, "argv", ["deli", "--test-mode"]):
        code = main()
        assert code == 1


def test_main_test_mode_invokes_runner(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text('{"info": {}, "item": []}')
    sentinel = object()
    with patch.object(sys, "argv", ["deli", "--test-mode", "-c", str(collection), "--no-live"]):
        with patch("deli.cli.run_postman_test_mode", new=Mock(return_value=sentinel)) as run_mode:
            with patch("deli.cli._run_async", return_value=None) as run_async:
                code = main()

    assert code == 0
    run_async.assert_called_once_with(sentinel)
    run_mode.assert_called_once()


def test_main_test_mode_accepts_env_file_with_short_e(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text('{"info": {}, "item": []}')
    environment = tmp_path / "environment.json"
    environment.write_text('{"values": []}')
    sentinel = object()
    with patch.object(
        sys,
        "argv",
        ["deli", "--test-mode", "-c", str(collection), "-e", str(environment), "--no-live"],
    ):
        with patch("deli.cli.run_postman_test_mode", new=Mock(return_value=sentinel)) as run_mode:
            with patch("deli.cli._run_async", return_value=None) as run_async:
                code = main()

    assert code == 0
    run_async.assert_called_once_with(sentinel)
    _, kwargs = run_mode.call_args
    assert kwargs["environment_path"] == environment
    assert kwargs["env_override"] is None


def test_main_test_mode_invokes_jmeter_runner(tmp_path: Path) -> None:
    jmx = tmp_path / "plan.jmx"
    jmx.write_text("<jmeterTestPlan><hashTree/></jmeterTestPlan>")
    sentinel = object()
    with patch.object(sys, "argv", ["deli", "--test-mode", "-j", str(jmx), "--no-live"]):
        with patch("deli.cli.run_jmeter_test_mode", new=Mock(return_value=sentinel)) as run_mode:
            with patch("deli.cli._run_async", return_value=None) as run_async:
                code = main()

    assert code == 0
    run_async.assert_called_once_with(sentinel)
    _, kwargs = run_mode.call_args
    assert kwargs["jmeter_path"] == jmx


def test_main_rejects_multiple_targets(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text('{"info": {}, "item": []}')
    jmx = tmp_path / "plan.jmx"
    jmx.write_text("<jmeterTestPlan><hashTree/></jmeterTestPlan>")
    with patch.object(sys, "argv", ["deli", "-c", str(collection), "-j", str(jmx)]):
        code = main()

    assert code == 1
