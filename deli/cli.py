"""CLI entry point for deli lightweight execution engine.

Speed-first design:
- Uses uvloop for faster event loop (2-4x faster than default)
- GC disabled during test execution for consistent latency
- Minimal import overhead at startup
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import sys
from pathlib import Path
from typing import Any, Coroutine

from . import __version__
from .config import load_config, validate_run_config
from .exceptions import DeliCollectionError, DeliConfigError, DeliError, DeliRunnerError
from .jmeter import load_jmx_run_config
from .logging_config import get_logger
from .manual import build_manual_requests, manual_report_name
from .models import LoadScenario, RunConfig
from .postman import load_collection, order_requests_for_runtime_dependencies
from .runner import (
    run_jmeter_test,
    run_jmeter_test_mode,
    run_manual_test,
    run_postman_test_mode,
    run_test,
)
from .stress_config import load_stress_config
from .stress_runner import run_stress_test

# Try to use uvloop for 2-4x faster async performance
_HAS_UVLOOP = False
try:
    import uvloop

    _HAS_UVLOOP = True
except ImportError:
    pass

logger = get_logger("cli")


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run async coroutine with optimal event loop.

    Uses uvloop.run() on Python 3.12+ for best performance.
    Falls back to asyncio.run() with uvloop policy on older versions.
    Disables GC during execution for consistent latency.
    """
    # Disable GC during test for consistent latency
    gc_was_enabled = gc.isenabled()
    gc.disable()

    try:
        if _HAS_UVLOOP:
            # uvloop.run() is the recommended way since Python 3.12
            return uvloop.run(coro)
        else:
            return asyncio.run(coro)
    finally:
        # Re-enable GC after test
        if gc_was_enabled:
            gc.enable()
        # Force a collection after test to clean up
        gc.collect()


def _parse_env_args(env_list: list[str] | None) -> dict[str, str]:
    if not env_list:
        return {}
    out: dict[str, str] = {}
    for s in env_list:
        if "=" in s:
            k, _, v = s.partition("=")
            out[k.strip()] = v.strip()
    return out


def _looks_like_environment_file_arg(value: str) -> bool:
    stripped = value.strip()
    if not stripped or "=" in stripped:
        return False
    return Path(stripped).suffix.lower() == ".json"


def _normalize_environment_args(
    env_list: list[str] | None,
    environment_path: Path | None,
) -> tuple[list[str] | None, Path | None]:
    """Accept legacy `-e environment.json` while preserving `-e KEY=VALUE` overrides."""
    if not env_list:
        return env_list, environment_path

    env_args: list[str] = []
    environment_files: list[Path] = []
    for value in env_list:
        if _looks_like_environment_file_arg(value):
            environment_files.append(Path(value.strip()))
        else:
            env_args.append(value)

    if len(environment_files) > 1:
        raise ValueError("Only one environment file can be provided with -e")

    if environment_files:
        inferred_path = environment_files[0]
        if environment_path is not None and environment_path != inferred_path:
            raise ValueError("Use only one environment file: -E/--environment or -e PATH")
        environment_path = inferred_path

    return env_args, environment_path


# Defaults when running without -f (config file)
DEFAULT_USERS = 10
DEFAULT_DURATION_SECONDS = 60.0
DEFAULT_RAMP_UP_SECONDS = 0.0
DEFAULT_ITERATIONS = 0
DEFAULT_THINK_TIME_MS = 0.0
DEFAULT_LOAD_REPORT = "report.html"
DEFAULT_STRESS_REPORT = "stress_report.html"
DEFAULT_TEST_REPORT = "test_report.html"


def _build_config_from_args(args: argparse.Namespace) -> RunConfig:
    """Build RunConfig from CLI args only (no config file). Uses defaults for omitted values."""
    scenario = LoadScenario(args.scenario) if args.scenario is not None else LoadScenario.CONSTANT
    config = RunConfig(
        users=args.users if args.users is not None else DEFAULT_USERS,
        ramp_up_seconds=args.ramp_up if args.ramp_up is not None else DEFAULT_RAMP_UP_SECONDS,
        duration_seconds=args.duration if args.duration is not None else DEFAULT_DURATION_SECONDS,
        iterations=args.iterations if args.iterations is not None else DEFAULT_ITERATIONS,
        think_time_ms=args.think_time_ms
        if args.think_time_ms is not None
        else DEFAULT_THINK_TIME_MS,
        scenario=scenario,
        spike_users=args.spike_users if args.spike_users is not None else 0,
        spike_duration_seconds=args.spike_duration if args.spike_duration is not None else 0.0,
        sla_p95_ms=args.sla_p95_ms,
        sla_p99_ms=args.sla_p99_ms,
        sla_error_rate_pct=args.sla_error_rate_pct,
    )
    validate_run_config(config)
    return config


def _build_config_with_overrides(config_path: Path, args: argparse.Namespace) -> RunConfig | None:
    """Load config from file and apply CLI overrides. Returns None if no overrides were given."""
    override_keys = (
        "users",
        "duration",
        "ramp_up",
        "scenario",
        "think_time_ms",
        "iterations",
        "spike_users",
        "spike_duration",
        "sla_p95_ms",
        "sla_p99_ms",
        "sla_error_rate_pct",
    )
    has_override = any(getattr(args, k, None) is not None for k in override_keys)
    if not has_override:
        return None
    base = load_config(config_path)
    scenario = base.scenario
    if args.scenario is not None:
        scenario = LoadScenario(args.scenario)
    merged = RunConfig(
        users=args.users if args.users is not None else base.users,
        ramp_up_seconds=args.ramp_up if args.ramp_up is not None else base.ramp_up_seconds,
        duration_seconds=args.duration if args.duration is not None else base.duration_seconds,
        iterations=args.iterations if args.iterations is not None else base.iterations,
        think_time_ms=args.think_time_ms if args.think_time_ms is not None else base.think_time_ms,
        scenario=scenario,
        spike_users=args.spike_users if args.spike_users is not None else base.spike_users,
        spike_duration_seconds=(
            args.spike_duration if args.spike_duration is not None else base.spike_duration_seconds
        ),
        sla_p95_ms=args.sla_p95_ms if args.sla_p95_ms is not None else base.sla_p95_ms,
        sla_p99_ms=args.sla_p99_ms if args.sla_p99_ms is not None else base.sla_p99_ms,
        sla_error_rate_pct=(
            args.sla_error_rate_pct
            if args.sla_error_rate_pct is not None
            else base.sla_error_rate_pct
        ),
    )
    validate_run_config(merged)
    return merged


def _build_jmeter_config_with_overrides(
    jmeter_path: Path,
    args: argparse.Namespace,
    env_override: dict[str, str] | None,
) -> RunConfig:
    """Load ThreadGroup settings from JMX and apply CLI load overrides."""
    base = load_jmx_run_config(jmeter_path, env_override=env_override)
    scenario = base.scenario
    if args.scenario is not None:
        scenario = LoadScenario(args.scenario)
    merged = RunConfig(
        users=args.users if args.users is not None else base.users,
        ramp_up_seconds=args.ramp_up if args.ramp_up is not None else base.ramp_up_seconds,
        duration_seconds=args.duration if args.duration is not None else base.duration_seconds,
        iterations=args.iterations if args.iterations is not None else base.iterations,
        think_time_ms=args.think_time_ms if args.think_time_ms is not None else base.think_time_ms,
        scenario=scenario,
        spike_users=args.spike_users if args.spike_users is not None else base.spike_users,
        spike_duration_seconds=(
            args.spike_duration if args.spike_duration is not None else base.spike_duration_seconds
        ),
        sla_p95_ms=args.sla_p95_ms if args.sla_p95_ms is not None else base.sla_p95_ms,
        sla_p99_ms=args.sla_p99_ms if args.sla_p99_ms is not None else base.sla_p99_ms,
        sla_error_rate_pct=(
            args.sla_error_rate_pct
            if args.sla_error_rate_pct is not None
            else base.sla_error_rate_pct
        ),
    )
    validate_run_config(merged)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="deli",
        description="Lightweight load execution engine. Speed and performance first. "
        "Postman Collection v2.1, async HTTP/2, minimal overhead.",
    )
    parser.add_argument(
        "-c",
        "--collection",
        help="Path to Postman Collection v2.1 JSON file (target mode; mutually exclusive with -j/-m)",
    )
    parser.add_argument(
        "-j",
        "--jmeter",
        dest="jmeter_path",
        metavar="PATH",
        help="Path to Apache JMeter JMX file (target mode; mutually exclusive with -c/-m)",
    )
    parser.add_argument(
        "-f",
        "--config",
        default=None,
        help="Path to YAML config (optional: use --users, --duration, etc. without -f)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path for HTML report (default: report.html, or stress_report.html with --stress)",
    )
    parser.add_argument(
        "--junit",
        metavar="PATH",
        dest="junit_path",
        help="Also write JUnit XML report to PATH (for CI)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        dest="json_path",
        help="Also write JSON report to PATH (machine-readable metrics)",
    )
    parser.add_argument(
        "-e",
        "--env",
        action="append",
        metavar="KEY=VALUE|PATH",
        help="Environment variable override for collection (KEY=VALUE; can be repeated). "
        "A JSON path is treated as --environment PATH for compatibility. Only with -c.",
    )
    parser.add_argument(
        "-E",
        "--environment",
        "--env-file",
        dest="environment_path",
        metavar="PATH",
        help="Path to Postman Environment JSON file. Used with -c; -e overrides its values.",
    )
    parser.add_argument(
        "-m",
        "--manual-url",
        metavar="URL",
        dest="manual_url",
        help="Manual target URL: load test this URL only (target mode; mutually exclusive with -c/-j).",
    )
    parser.add_argument(
        "-s",
        "--stress",
        action="store_true",
        dest="stress",
        help="Run stress test mode (separate config, ramp until threshold exceeded). Use -f for stress config.",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Disable live Rich dashboard (headless mode)",
    )
    parser.add_argument(
        "--test-mode",
        "--smoke-test",
        action="store_true",
        dest="test_mode",
        help="Read collection/environment and run a 5-user one-iteration verification test.",
    )
    # Config overrides (override values from -f YAML when provided)
    parser.add_argument(
        "--users", type=int, default=None, help="Override config: number of virtual users"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        metavar="SEC",
        help="Override config: test duration in seconds",
    )
    parser.add_argument(
        "--ramp-up",
        type=float,
        default=None,
        metavar="SEC",
        dest="ramp_up",
        help="Override config: ramp-up time in seconds",
    )
    parser.add_argument(
        "--scenario",
        choices=["constant", "gradual", "spike"],
        default=None,
        help="Override config: load scenario",
    )
    parser.add_argument(
        "--think-time",
        type=float,
        default=None,
        metavar="MS",
        dest="think_time_ms",
        help="Override config: think time between requests (ms)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Override config: iterations per user (0 = run for duration)",
    )
    parser.add_argument(
        "--spike-users",
        type=int,
        default=None,
        metavar="N",
        dest="spike_users",
        help="Override config: extra users during spike (spike scenario)",
    )
    parser.add_argument(
        "--spike-duration",
        type=float,
        default=None,
        metavar="SEC",
        dest="spike_duration",
        help="Override config: spike duration in seconds (spike scenario)",
    )
    parser.add_argument(
        "--sla-p95",
        type=float,
        default=None,
        metavar="MS",
        dest="sla_p95_ms",
        help="Override config: SLA P95 latency (ms)",
    )
    parser.add_argument(
        "--sla-p99",
        type=float,
        default=None,
        metavar="MS",
        dest="sla_p99_ms",
        help="Override config: SLA P99 latency (ms)",
    )
    parser.add_argument(
        "--sla-error-rate",
        type=float,
        default=None,
        metavar="PCT",
        dest="sla_error_rate_pct",
        help="Override config: SLA max error rate (%%)",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"deli {__version__}",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    environment_path = Path(args.environment_path) if args.environment_path else None
    try:
        env_args, environment_path = _normalize_environment_args(args.env, environment_path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    args.env = env_args
    output_path = args.output or (
        DEFAULT_TEST_REPORT
        if args.test_mode
        else DEFAULT_STRESS_REPORT
        if args.stress
        else DEFAULT_LOAD_REPORT
    )

    target_count = sum(bool(v) for v in (args.collection, args.jmeter_path, args.manual_url))
    if target_count > 1:
        print("Error: use only one target: -c/--collection, -j/--jmeter, or -m/--manual-url", file=sys.stderr)
        return 1

    if environment_path is not None and not args.collection:
        print("Error: --environment requires -c/--collection", file=sys.stderr)
        return 1

    if args.test_mode and args.stress:
        print("Error: --test-mode cannot be combined with --stress", file=sys.stderr)
        return 1

    def handle_error(e: BaseException) -> int:
        if isinstance(e, DeliError):
            print(f"Error: {e.message}", file=sys.stderr)
            return 1
        if isinstance(e, (FileNotFoundError, ValueError)):
            print(f"Error: {e}", file=sys.stderr)
            return 1
        logger.exception("Unexpected error")
        print("Error: An unexpected error occurred. Check logs for details.", file=sys.stderr)
        return 1

    if args.test_mode:
        if not args.collection and not args.jmeter_path:
            print("Error: --test-mode requires -c/--collection or -j/--jmeter", file=sys.stderr)
            return 1
        try:
            env_override = _parse_env_args(args.env)
            if args.jmeter_path:
                _run_async(
                    run_jmeter_test_mode(
                        jmeter_path=Path(args.jmeter_path),
                        report_path=output_path,
                        env_override=env_override or None,
                        live=not args.no_live,
                        junit_path=getattr(args, "junit_path", None),
                        json_path=getattr(args, "json_path", None),
                    )
                )
            else:
                _run_async(
                    run_postman_test_mode(
                        collection_path=Path(args.collection),
                        report_path=output_path,
                        env_override=env_override or None,
                        environment_path=environment_path,
                        live=not args.no_live,
                        junit_path=getattr(args, "junit_path", None),
                        json_path=getattr(args, "json_path", None),
                    )
                )
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130
        except (DeliCollectionError, DeliRunnerError) as e:
            return handle_error(e)
        except Exception as e:
            return handle_error(e)
        return 0

    # Stress test mode: -s with -f (stress config), target via -c or -m
    if args.stress:
        if config_path is None:
            print("Error: stress mode requires -f/--config (stress config YAML)", file=sys.stderr)
            return 1
        try:
            stress_config = load_stress_config(config_path)
        except (DeliConfigError, FileNotFoundError) as e:
            return handle_error(e)
        if args.manual_url:
            try:
                requests = build_manual_requests(args.manual_url)
            except DeliRunnerError as e:
                return handle_error(e)
            collection_name = manual_report_name(args.manual_url)
        elif args.collection:
            collection = Path(args.collection)
            try:
                env_override = _parse_env_args(args.env)
                requests = load_collection(
                    collection,
                    env_override=env_override or None,
                    environment_path=environment_path,
                )
                requests = order_requests_for_runtime_dependencies(requests)
            except DeliCollectionError as e:
                return handle_error(e)
            collection_name = collection.stem
        elif args.jmeter_path:
            jmeter_path = Path(args.jmeter_path)
            try:
                from .jmeter import load_jmx

                env_override = _parse_env_args(args.env)
                requests = load_jmx(jmeter_path, env_override=env_override or None)
            except DeliCollectionError as e:
                return handle_error(e)
            collection_name = jmeter_path.stem
        else:
            print(
                "Error: stress mode requires -c/--collection, -j/--jmeter, or -m/--manual-url for target",
                file=sys.stderr,
            )
            return 1
        if not requests:
            print("Error: no requests to run for stress test", file=sys.stderr)
            return 1
        try:
            _run_async(
                run_stress_test(
                    requests=requests,
                    config=stress_config,
                    collection_name=collection_name,
                    report_path=output_path,
                    live=not args.no_live,
                    junit_path=getattr(args, "junit_path", None),
                    json_path=getattr(args, "json_path", None),
                )
            )
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130
        except (DeliError, DeliRunnerError) as e:
            return handle_error(e)
        except Exception as e:
            return handle_error(e)
        return 0

    if args.manual_url:
        try:
            if config_path is None:
                config_override = _build_config_from_args(args)
            else:
                config_override = _build_config_with_overrides(config_path, args)
            _run_async(
                run_manual_test(
                    manual_url=args.manual_url,
                    report_path=output_path,
                    config_path=config_path,
                    live=not args.no_live,
                    junit_path=getattr(args, "junit_path", None),
                    json_path=getattr(args, "json_path", None),
                    config_override=config_override,
                )
            )
        except (DeliConfigError, FileNotFoundError) as e:
            return handle_error(e)
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130
        except (DeliConfigError, DeliRunnerError) as e:
            return handle_error(e)
        except Exception as e:
            return handle_error(e)
        return 0

    # File target mode: Postman (-c) or JMeter (-j) required when not using -m.
    if not args.collection and not args.jmeter_path:
        print("Error: -c/--collection or -j/--jmeter required when not using -m/--manual-url", file=sys.stderr)
        return 1
    try:
        if config_path is None:
            config_override = _build_config_from_args(args)
        else:
            config_override = _build_config_with_overrides(config_path, args)
        env_override = _parse_env_args(args.env)
        if args.jmeter_path:
            if config_path is None:
                config_override = _build_jmeter_config_with_overrides(
                    Path(args.jmeter_path),
                    args,
                    env_override or None,
                )
            _run_async(
                run_jmeter_test(
                    jmeter_path=Path(args.jmeter_path),
                    report_path=output_path,
                    config_path=config_path,
                    env_override=env_override or None,
                    live=not args.no_live,
                    junit_path=getattr(args, "junit_path", None),
                    json_path=getattr(args, "json_path", None),
                    config_override=config_override,
                )
            )
        else:
            _run_async(
                run_test(
                    collection_path=Path(args.collection),
                    report_path=output_path,
                    config_path=config_path,
                    env_override=env_override or None,
                    environment_path=environment_path,
                    live=not args.no_live,
                    junit_path=getattr(args, "junit_path", None),
                    json_path=getattr(args, "json_path", None),
                    config_override=config_override,
                )
            )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except (DeliConfigError, DeliCollectionError, DeliRunnerError) as e:
        return handle_error(e)
    except Exception as e:
        return handle_error(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
