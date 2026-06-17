"""Execution runner: scenario, metrics, report. Lightweight, speed-first; no framework layer."""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live

from .config import load_config
from .dashboard import create_live_panel
from .exceptions import DeliRunnerError
from .logging_config import get_logger
from .metrics import DEFAULT_MAX_RESULTS, MetricsCollector
from .models import AggregateMetrics, LoadScenario, ParsedRequest, RunConfig
from .postman import load_collection, load_environment, unresolved_variables_in_requests
from .report import generate_json_report, generate_junit_report, generate_report
from .scenarios import run_scenario

if TYPE_CHECKING:
    from typing import Any

logger = get_logger("runner")

# Speed-first: fast consumer drain, minimal post-run delay, low live refresh.
CONSUMER_POLL_SEC = 0.1
DRAIN_SLEEP_SEC = 0.1
DRAIN_ITERATIONS = 3
POST_SCENARIO_SLEEP_SEC = 0.05
LIVE_REFRESH_PER_SEC = 1
# When stdout is not a TTY (e.g. Docker without -it), refresh interval for streaming fallback
STREAMING_FALLBACK_INTERVAL_SEC = 1.0
# End deadline buffer (seconds beyond test duration)
END_DEADLINE_BUFFER_SEC = 5
# Result queue maximum size
RESULT_QUEUE_MAXSIZE = 50_000

# Global flag for graceful shutdown
_shutdown_requested = False


def _setup_signal_handlers() -> dict[int, Any]:
    """Setup handlers for SIGINT/SIGTERM to allow graceful shutdown."""
    global _shutdown_requested
    previous_handlers: dict[int, Any] = {}

    def _signal_handler(signum: int, frame: Any) -> None:
        global _shutdown_requested
        _shutdown_requested = True
        logger.info("Shutdown signal received (signal %d), finishing current requests...", signum)

    try:
        if hasattr(signal, "SIGTERM"):
            previous_handlers[signal.SIGTERM] = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _signal_handler)
        previous_handlers[signal.SIGINT] = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _signal_handler)
    except ValueError:
        logger.debug("Signal handlers can only be installed from the main thread")
    return previous_handlers


def _restore_signal_handlers(previous_handlers: dict[int, Any]) -> None:
    """Restore signal handlers changed by _setup_signal_handlers."""
    for signum, handler in previous_handlers.items():
        try:
            signal.signal(signum, handler)
        except ValueError:
            logger.debug("Signal handlers can only be restored from the main thread")


def _stdout_is_tty() -> bool:
    """True if stdout is a TTY (interactive terminal). False in Docker without -it, CI, pipes."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


async def _run_streaming_fallback(
    collector: MetricsCollector,
    config: RunConfig,
    start_time: float,
    scenario_task: asyncio.Task,
    end_deadline: float,
) -> None:
    """Print one line per interval when not a TTY (Docker, CI) so output streams in real time."""
    global _shutdown_requested

    # Use cached aggregate directly to minimize overhead in logging loop
    cache_ttl = 0.3

    while (
        not scenario_task.done() and time.perf_counter() < end_deadline and not _shutdown_requested
    ):
        elapsed = time.perf_counter() - start_time if start_time else 0
        remaining = max(0, config.duration_seconds - elapsed)
        agg = collector.get_cached_aggregate(cache_ttl_sec=cache_ttl)
        total = len(collector.results)
        tps = agg.tps if agg else 0.0
        err = agg.error_rate_pct if agg else 0.0
        remaining_str = (
            f"{int(remaining)}s"
            if remaining < 60
            else f"{int(remaining // 60)}m {int(remaining % 60)}s"
        )
        line = f"deli | {elapsed:.1f}s/{config.duration_seconds}s | remaining: {remaining_str} | requests={total} tps={tps:.1f} err%={err:.2f}\n"
        sys.stdout.write(line)
        sys.stdout.flush()

        await asyncio.sleep(STREAMING_FALLBACK_INTERVAL_SEC)


async def _run_with_requests(
    requests: list[ParsedRequest],
    config: RunConfig,
    report_path: Path,
    collection_name: str,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
    http2: bool = True,
) -> AggregateMetrics:
    previous_signal_handlers = _setup_signal_handlers()
    try:
        return await _run_with_requests_impl(
            requests=requests,
            config=config,
            report_path=report_path,
            collection_name=collection_name,
            live=live,
            junit_path=junit_path,
            json_path=json_path,
            http2=http2,
        )
    finally:
        _restore_signal_handlers(previous_signal_handlers)


async def _run_with_requests_impl(
    requests: list[ParsedRequest],
    config: RunConfig,
    report_path: Path,
    collection_name: str,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
    http2: bool = True,
) -> AggregateMetrics:
    """Core load test loop: scenario, collector, drain, report.

    This is the main execution function that:
    1. Creates a result queue and metrics collector
    2. Spawns scenario workers and a consumer task
    3. Displays live progress (if enabled)
    4. Drains remaining results after scenario completion
    5. Generates HTML, JUnit, and JSON reports

    Raises:
        DeliRunnerError: If no requests are provided
    """
    global _shutdown_requested
    _shutdown_requested = False

    if not requests:
        raise DeliRunnerError("No requests to run")

    test_start_dt = datetime.now(timezone.utc)
    logger.info(
        "Starting load test: collection=%s, users=%s, duration=%ss, scenario=%s",
        collection_name,
        config.users,
        config.duration_seconds,
        config.scenario.value,
    )
    result_queue: asyncio.Queue = asyncio.Queue(maxsize=RESULT_QUEUE_MAXSIZE)
    collector = MetricsCollector(max_results=DEFAULT_MAX_RESULTS)
    producer_done = asyncio.Event()

    async def consume():
        """Consume results from queue in batches for efficiency."""
        batch = []
        # Cache local methods
        queue_get = result_queue.get
        queue_get_nowait = result_queue.get_nowait
        queue_empty = result_queue.empty
        collector_add_batch = collector.add_batch

        while True:
            try:
                if producer_done.is_set() and queue_empty():
                    if batch:
                        collector_add_batch(batch)
                    break

                # Wait for at least one item
                try:
                    item = await asyncio.wait_for(queue_get(), timeout=CONSUMER_POLL_SEC)
                except asyncio.TimeoutError:
                    continue

                if item is None:
                    continue

                batch.append(item)

                # Drain queue up to limit without waiting
                for _ in range(1000):
                    if queue_empty():
                        break
                    try:
                        next_item = queue_get_nowait()
                        if next_item is None:
                            continue
                        batch.append(next_item)
                    except asyncio.QueueEmpty:
                        break

                if batch:
                    collector_add_batch(batch)
                    batch.clear()
            except asyncio.CancelledError:
                if batch:
                    collector_add_batch(batch)
                break

    consumer_task = asyncio.create_task(consume())
    console = Console()
    start_time: float = 0.0
    end_time: float = 0.0

    async def run_scenario_and_capture_times():
        nonlocal start_time, end_time
        start_time = time.perf_counter()
        _, end_time = await run_scenario(config, requests, result_queue, http2=http2)

    scenario_task = asyncio.create_task(run_scenario_and_capture_times())

    if live:
        end_deadline = time.perf_counter() + config.duration_seconds + END_DEADLINE_BUFFER_SEC
        if _stdout_is_tty():
            with Live(
                create_live_panel(collector, config, start_time),
                console=console,
                refresh_per_second=LIVE_REFRESH_PER_SEC,
            ) as live_ctx:
                while (
                    not scenario_task.done()
                    and time.perf_counter() < end_deadline
                    and not _shutdown_requested
                ):
                    live_ctx.update(create_live_panel(collector, config, start_time))
                    await asyncio.sleep(CONSUMER_POLL_SEC)
                live_ctx.update(create_live_panel(collector, config, start_time))
        else:
            await _run_streaming_fallback(
                collector,
                config,
                start_time,
                scenario_task,
                end_deadline,
            )
    await scenario_task
    collector.set_end_time(end_time)

    await asyncio.sleep(POST_SCENARIO_SLEEP_SEC)

    def drain_queue() -> None:
        while True:
            try:
                item = result_queue.get_nowait()
                if item is not None:
                    collector.add(item)
            except asyncio.QueueEmpty:
                break

    drain_queue()
    for _ in range(DRAIN_ITERATIONS):
        # Allow time for delayed packets
        await asyncio.sleep(DRAIN_SLEEP_SEC)
        drain_queue()

    # Manual finish time if needed
    final_end_time = time.perf_counter()
    if collector._end_time is None:
        collector.set_end_time(final_end_time)

    # Let consumer finish processing after workers have stopped and the queue is empty.
    producer_done.set()
    try:
        await asyncio.wait_for(consumer_task, timeout=30.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    drain_queue()

    test_end_dt = datetime.now(timezone.utc)
    agg = collector.full_aggregate()
    logger.info(
        "Load test finished: total_requests=%s, tps=%.1f, error_rate_pct=%.2f",
        agg.total_requests,
        agg.tps,
        agg.error_rate_pct,
    )
    generate_report(
        report_path,
        collector,
        config,
        collection_name=collection_name,
        start_dt=test_start_dt,
        end_dt=test_end_dt,
    )
    if junit_path:
        generate_junit_report(
            junit_path,
            collector,
            config,
            collection_name=collection_name,
            start_dt=test_start_dt,
            end_dt=test_end_dt,
        )
        if live:
            console.print(f"[dim]JUnit report:[/dim] {junit_path}")
    if json_path:
        generate_json_report(
            json_path,
            collector,
            config,
            collection_name=collection_name,
            start_dt=test_start_dt,
            end_dt=test_end_dt,
        )
        if live:
            console.print(f"[dim]JSON report:[/dim] {json_path}")
    if live:
        console.print(f"[green]Report written to[/green] {report_path}")
    return agg


def _resolve_report_path(report_path: str | Path) -> Path:
    p = Path(report_path)
    if p.suffix.lower() != ".html":
        if not p.suffix or p.is_dir():
            p = p / "report.html"
        else:
            p = p.with_suffix(".html")
    return p


async def run_test(
    collection_path: str | Path,
    report_path: str | Path,
    config_path: str | Path | None = None,
    env_override: dict[str, str] | None = None,
    environment_path: str | Path | None = None,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
    config_override: RunConfig | None = None,
) -> None:
    """Load Postman collection and config, run scenario, metrics, report. Postman flow only."""
    if config_override is not None:
        config = config_override
    elif config_path is not None:
        config = load_config(config_path)
    else:
        raise DeliRunnerError(
            "Either config path (-f) or config overrides (--users, --duration, etc.) required"
        )
    requests = load_collection(
        collection_path,
        env_override=env_override or None,
        environment_path=environment_path,
    )
    if not requests:
        raise DeliRunnerError("No requests found in collection")

    report_path_resolved = _resolve_report_path(report_path)
    collection_name = Path(collection_path).stem
    await _run_with_requests(
        requests=requests,
        config=config,
        report_path=report_path_resolved,
        collection_name=collection_name,
        live=live,
        junit_path=junit_path,
        json_path=json_path,
    )


TEST_MODE_USERS = 5
TEST_MODE_DURATION_SECONDS = 10.0
TEST_MODE_ITERATIONS = 1


def _test_mode_config() -> RunConfig:
    return RunConfig(
        users=TEST_MODE_USERS,
        ramp_up_seconds=0.0,
        duration_seconds=TEST_MODE_DURATION_SECONDS,
        iterations=TEST_MODE_ITERATIONS,
        think_time_ms=0.0,
        scenario=LoadScenario.CONSTANT,
    )


def _confirm_continue_after_preflight_issue(message: str) -> bool:
    """Ask whether to continue after a recoverable Postman preflight issue."""
    if not sys.stdin.isatty():
        raise DeliRunnerError(f"{message}. Refusing to continue in non-interactive mode")
    answer = input("Continue with HTTP verification despite this issue? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _print_unresolved_variables(
    console: Console,
    unresolved: dict[str, list[str]],
) -> None:
    console.print("[yellow]Variables unresolved[/yellow]")
    for request_name, names in unresolved.items():
        console.print(f"  - {request_name}: {', '.join(names)}")


def _load_requests_for_test_mode(
    collection_path: str | Path,
    env_override: dict[str, str] | None,
    environment_path: str | Path | None,
    console: Console,
) -> list[ParsedRequest]:
    console.print("[bold]Postman preflight[/bold]")
    console.print(f"Collection: {collection_path}")
    if environment_path is not None:
        console.print(f"Environment: {environment_path}")
    else:
        console.print("Environment: not provided")

    env_values: dict[str, str] | None = None
    if environment_path is not None:
        try:
            env_values = load_environment(environment_path, required=True)
            console.print(f"[green]Environment OK[/green]: {len(env_values)} enabled variable(s)")
        except DeliRunnerError:
            raise
        except Exception as exc:
            message = f"Environment file could not be loaded: {exc}"
            console.print(f"[yellow]{message}[/yellow]")
            if not _confirm_continue_after_preflight_issue(message):
                raise DeliRunnerError(message)
            env_values = {}

    if env_values is not None and env_override:
        env_values.update(env_override)
    try:
        requests = load_collection(
            collection_path,
            env_override=None if env_values is not None else env_override,
            environment_values=env_values,
        )
    except Exception as exc:
        raise DeliRunnerError(f"Collection file could not be loaded: {exc}") from exc

    console.print(f"[green]Collection OK[/green]: {len(requests)} request(s)")
    if not requests:
        raise DeliRunnerError("No requests found in collection")

    unresolved = unresolved_variables_in_requests(requests)
    if unresolved:
        _print_unresolved_variables(console, unresolved)
        message = "Some Postman variables could not be resolved"
        if not _confirm_continue_after_preflight_issue(message):
            raise DeliRunnerError(f"Unresolved Postman variables: {unresolved}")
    else:
        console.print("[green]Variables OK[/green]: all Postman variables resolved")

    console.print("[cyan]HTTP verification[/cyan]: 5 users, 1 iteration per user")
    return requests


async def run_postman_test_mode(
    collection_path: str | Path,
    report_path: str | Path,
    env_override: dict[str, str] | None = None,
    environment_path: str | Path | None = None,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> AggregateMetrics:
    """Read collection/environment and verify targets with a 5-user one-iteration run."""
    console = Console()
    requests = _load_requests_for_test_mode(
        collection_path=collection_path,
        env_override=env_override or None,
        environment_path=environment_path,
        console=console,
    )

    agg = await _run_with_requests(
        requests=requests,
        config=_test_mode_config(),
        report_path=_resolve_report_path(report_path),
        collection_name=f"{Path(collection_path).stem} test",
        live=live,
        junit_path=junit_path,
        json_path=json_path,
        http2=False,
    )
    if agg.total_requests == 0:
        raise DeliRunnerError("Test mode did not record any requests")
    if agg.failed_requests > 0:
        status_summary = ", ".join(
            f"{status}={count}" for status, count in sorted(agg.status_code_counts.items())
        )
        console.print(
            f"[red]HTTP verification failed[/red]: {agg.failed_requests}/{agg.total_requests} "
            f"request(s) failed ({status_summary})"
        )
        raise DeliRunnerError(
            f"Test mode failed: {agg.failed_requests}/{agg.total_requests} requests failed"
            + (f" ({status_summary})" if status_summary else "")
        )
    console.print(
        f"[green]HTTP verification OK[/green]: {agg.total_requests} request(s), "
        f"error_rate={agg.error_rate_pct:.2f}%"
    )
    return agg


async def run_manual_test(
    manual_url: str,
    report_path: str | Path,
    config_path: str | Path | None = None,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
    config_override: RunConfig | None = None,
) -> None:
    """
    Load test a single URL. No Postman, no collection.
    Uses manual module only; same engine/scenarios/report pipeline.
    """
    from .manual import build_manual_requests, manual_report_name

    if config_override is not None:
        config = config_override
    elif config_path is not None:
        config = load_config(config_path)
    else:
        raise DeliRunnerError(
            "Either config path (-f) or config overrides (--users, --duration, etc.) required"
        )
    requests = build_manual_requests(manual_url)
    report_path_resolved = _resolve_report_path(report_path)
    collection_name = manual_report_name(manual_url)

    await _run_with_requests(
        requests=requests,
        config=config,
        report_path=report_path_resolved,
        collection_name=collection_name,
        live=live,
        junit_path=junit_path,
        json_path=json_path,
    )
