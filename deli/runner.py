"""Execution runner: scenario, metrics, report. Lightweight, speed-first; no framework layer."""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .config import load_config
from .dashboard import create_live_panel
from .engine import create_client
from .exceptions import DeliRunnerError
from .logging_config import get_logger
from .metrics import MetricsCollector, DEFAULT_MAX_RESULTS
from .models import ParsedRequest, RunConfig
from .postman import load_collection
from .report import generate_report, generate_json_report, generate_junit_report
from .scenarios import run_scenario

from rich.console import Console
from rich.live import Live

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


def _setup_signal_handlers() -> None:
    """Setup handlers for SIGINT/SIGTERM to allow graceful shutdown."""
    global _shutdown_requested
    
    def _signal_handler(signum: int, frame: Any) -> None:
        global _shutdown_requested
        _shutdown_requested = True
        logger.info("Shutdown signal received (signal %d), finishing current requests...", signum)
    
    # Only set up signal handlers on Unix-like systems
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _signal_handler)
    # SIGINT is typically handled by KeyboardInterrupt, but we can still catch it
    signal.signal(signal.SIGINT, _signal_handler)


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
    
    while not scenario_task.done() and time.perf_counter() < end_deadline and not _shutdown_requested:
        elapsed = time.perf_counter() - start_time if start_time else 0
        remaining = max(0, config.duration_seconds - elapsed)
        agg = collector.get_cached_aggregate(cache_ttl_sec=cache_ttl)
        total = len(collector.results)
        tps = agg.tps if agg else 0.0
        err = agg.error_rate_pct if agg else 0.0
        remaining_str = f"{int(remaining)}s" if remaining < 60 else f"{int(remaining // 60)}m {int(remaining % 60)}s"
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
) -> None:
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
    _setup_signal_handlers()
    
    if not requests:
        raise DeliRunnerError("No requests to run")

    test_start_dt = datetime.now(timezone.utc)
    logger.info(
        "Starting load test: collection=%s, users=%s, duration=%ss, scenario=%s",
        collection_name, config.users, config.duration_seconds, config.scenario.value
    )
    result_queue: asyncio.Queue = asyncio.Queue(maxsize=RESULT_QUEUE_MAXSIZE)
    collector = MetricsCollector(max_results=DEFAULT_MAX_RESULTS)

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
                # Wait for at least one item
                try:
                    item = await asyncio.wait_for(queue_get(), timeout=CONSUMER_POLL_SEC)
                except asyncio.TimeoutError:
                    continue
                
                if item is None:
                    if batch:
                        collector_add_batch(batch)
                    break
                
                batch.append(item)
                
                # Drain queue up to limit without waiting
                for _ in range(1000):
                    if queue_empty():
                        break
                    try:
                        next_item = queue_get_nowait()
                        if next_item is None:
                            # Sentinel found in batch drain
                            if batch:
                                collector_add_batch(batch)
                            return
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
        _, end_time = await run_scenario(config, requests, result_queue)

    scenario_task = asyncio.create_task(run_scenario_and_capture_times())

    if live:
        end_deadline = time.perf_counter() + config.duration_seconds + END_DEADLINE_BUFFER_SEC
        if _stdout_is_tty():
            with Live(
                create_live_panel(collector, config, start_time),
                console=console,
                refresh_per_second=LIVE_REFRESH_PER_SEC,
            ) as live_ctx:
                while not scenario_task.done() and time.perf_counter() < end_deadline and not _shutdown_requested:
                    live_ctx.update(create_live_panel(collector, config, start_time))
                    await asyncio.sleep(CONSUMER_POLL_SEC)
                live_ctx.update(create_live_panel(collector, config, start_time))
        else:
            await _run_streaming_fallback(
                collector, config, start_time, scenario_task, end_deadline,
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

    # Let consumer finish processing (workers already sent sentinels). Avoid cancel so in-flight batch is not lost.
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
    logger.info("Load test finished: total_requests=%s, tps=%.1f, error_rate_pct=%.2f", agg.total_requests, agg.tps, agg.error_rate_pct)
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


REPORT_TIMESTAMP_FMT = "%Y%m%d_%H%M%S"


def _resolve_report_path(report_path: str | Path) -> Path:
    p = Path(report_path)
    if p.suffix.lower() != ".html":
        if not p.suffix or p.is_dir():
            p = p / "report.html"
        else:
            p = p.with_suffix(".html")
    # Add timestamp so back-to-back runs do not overwrite report and raw JSON
    stem_ts = p.stem + "_" + datetime.now(timezone.utc).strftime(REPORT_TIMESTAMP_FMT)
    return p.parent / (stem_ts + p.suffix)


async def run_test(
    collection_path: str | Path,
    report_path: str | Path,
    config_path: str | Path | None = None,
    env_override: dict[str, str] | None = None,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
    config_override: RunConfig | None = None,
) -> None:
    """Load Postman collection and config, run scenario, metrics, report. Postman flow only."""
    if config_override is not None:
        config = config_override
    elif config_path is not None:
        config = await asyncio.to_thread(load_config, config_path)
    else:
        raise DeliRunnerError("Either config path (-f) or config overrides (--users, --duration, etc.) required")
    requests = await asyncio.to_thread(load_collection, collection_path, env_override or None)
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
        config = await asyncio.to_thread(load_config, config_path)
    else:
        raise DeliRunnerError("Either config path (-f) or config overrides (--users, --duration, etc.) required")
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
