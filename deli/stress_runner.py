"""Stress test runner: phased ramp, threshold check, breaking point and degradation detection.

This module implements the stress testing workflow:
- Phases: Run load at increasing user counts until SLA threshold exceeded
- Detection: Breaking point, first error, non-linear latency degradation
- Reports: Generate HTML, JUnit, JSON reports with stress-specific metrics
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import create_client, run_worker
from .exceptions import DeliRunnerError
from .logging_config import get_logger
from .metrics import MetricsCollector, compute_aggregate, DEFAULT_MAX_RESULTS
from .models import (
    LoadScenario,
    ParsedRequest,
    RequestResult,
    RunConfig,
    StressConfig,
    StressPhaseResult,
    StressScenario,
    StressTestResult,
)

logger = get_logger("stress_runner")

# Phase execution constants
PHASE_RESULT_QUEUE_MAXSIZE = 20_000
PHASE_COLLECTOR_MAX_RESULTS = 50_000
PHASE_CONSUMER_POLL_SEC = 0.1
PHASE_DRAIN_SLEEP_SEC = 0.2
PHASE_DRAIN_ITERATIONS = 3
# Worker limits
MAX_IN_FLIGHT_MULTIPLIER = 2
MIN_IN_FLIGHT_LIMIT = 50
MAX_IN_FLIGHT_LIMIT = 1000
DEFAULT_HTTP_TIMEOUT = 30.0
# Latency analysis
NONLINEAR_SLOPE_THRESHOLD = 2.0  # Slope must be >2x previous to detect non-linearity


def _timeout_count(results: list[RequestResult]) -> int:
    return sum(
        1
        for r in results
        if not r.success and (r.status_code is None or "timeout" in (r.error or "").lower())
    )


async def run_phase(
    num_users: int,
    duration_seconds: float,
    requests: list[ParsedRequest],
    think_time_ms: float,
) -> tuple[list[RequestResult], float, float]:
    """Run one stress phase: N users for duration_seconds.
    
    Args:
        num_users: Number of concurrent virtual users
        duration_seconds: How long to run this phase
        requests: List of requests to cycle through
        think_time_ms: Delay between requests per user
    
    Returns:
        Tuple of (results list, start_timestamp, end_timestamp)
    """
    if not requests:
        return [], time.perf_counter(), time.perf_counter()

    result_queue: asyncio.Queue = asyncio.Queue(maxsize=PHASE_RESULT_QUEUE_MAXSIZE)
    collector = MetricsCollector(max_results=PHASE_COLLECTOR_MAX_RESULTS)
    stop_event = asyncio.Event()
    start_ts = time.perf_counter()
    end_ts = start_ts + duration_seconds
    max_in_flight = min(MAX_IN_FLIGHT_LIMIT, max(num_users * MAX_IN_FLIGHT_MULTIPLIER, MIN_IN_FLIGHT_LIMIT))
    semaphore = asyncio.Semaphore(max_in_flight)

    async def consume():
        """Consume results in batches for efficiency."""
        batch = []
        # Local refs
        queue_get = result_queue.get
        queue_get_nowait = result_queue.get_nowait
        queue_empty = result_queue.empty
        collector_add_batch = collector.add_batch
        
        while True:
            try:
                # Wait with timeout for first item
                try:
                    item = await asyncio.wait_for(queue_get(), timeout=PHASE_CONSUMER_POLL_SEC)
                except asyncio.TimeoutError:
                    continue
                    
                if item is None:
                    if batch:
                        collector_add_batch(batch)
                    break
                
                batch.append(item)
                
                # Drain rest of queue up to limit
                for _ in range(1000):
                    if queue_empty():
                        break
                    try:
                        next_item = queue_get_nowait()
                        if next_item is None:
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

    async with await create_client(http2=True, timeout=DEFAULT_HTTP_TIMEOUT) as client:
        workers = [
            asyncio.create_task(
                run_worker(client, requests, think_time_ms, result_queue, stop_event, 0, semaphore=semaphore)
            )
            for _ in range(num_users)
        ]
        await asyncio.sleep(duration_seconds)
        stop_event.set()
        await asyncio.gather(*workers)

    collector.set_end_time(end_ts)
    try:
        await asyncio.wait_for(consumer_task, timeout=15.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    def drain():
        batch = []
        while True:
            try:
                item = result_queue.get_nowait()
                if item is not None:
                    batch.append(item)
            except asyncio.QueueEmpty:
                break
        if batch:
            collector.add_batch(batch)

    for _ in range(PHASE_DRAIN_ITERATIONS):
        await asyncio.sleep(PHASE_DRAIN_SLEEP_SEC)
        drain()

    return list(collector.results), start_ts, end_ts


def _phase_metrics(
    results: list[RequestResult],
    start_ts: float,
    end_ts: float,
    phase: int,
    users: int,
    duration_seconds: float,
    config: StressConfig,
) -> StressPhaseResult:
    """Build StressPhaseResult from phase results and check threshold."""
    start_ms = start_ts * 1000
    end_ms = end_ts * 1000
    agg = compute_aggregate(results, start_ms, end_ms)
    total = agg.total_requests
    timeout_count = _timeout_count(results)
    timeout_rate_pct = (100.0 * timeout_count / total) if total else 0.0

    exceeded = False
    reason = ""
    if agg.p95_ms > config.sla_p95_ms:
        exceeded = True
        reason = f"P95 {agg.p95_ms:.1f}ms > SLA {config.sla_p95_ms}ms"
    elif agg.p99_ms > config.sla_p99_ms:
        exceeded = True
        reason = f"P99 {agg.p99_ms:.1f}ms > SLA {config.sla_p99_ms}ms"
    elif agg.error_rate_pct > config.sla_error_rate_pct:
        exceeded = True
        reason = f"Error rate {agg.error_rate_pct:.2f}% > SLA {config.sla_error_rate_pct}%"
    elif timeout_rate_pct > config.sla_timeout_rate_pct:
        exceeded = True
        reason = f"Timeout rate {timeout_rate_pct:.2f}% > SLA {config.sla_timeout_rate_pct}%"

    return StressPhaseResult(
        phase=phase,
        users=users,
        duration_seconds=duration_seconds,
        total_requests=total,
        successful_requests=agg.successful_requests,
        failed_requests=agg.failed_requests,
        tps=round(agg.tps, 2),
        avg_response_time_ms=round(agg.avg_response_time_ms, 2),
        p50_ms=round(agg.p50_ms, 2),
        p95_ms=round(agg.p95_ms, 2),
        p99_ms=round(agg.p99_ms, 2),
        error_rate_pct=round(agg.error_rate_pct, 2),
        timeout_count=timeout_count,
        timeout_rate_pct=round(timeout_rate_pct, 2),
        threshold_exceeded=exceeded,
        exceeded_reason=reason,
    )


def _detect_nonlinear_latency(phases: list[StressPhaseResult]) -> int:
    """Return user count at which P95 increased non-linearly.
    
    Non-linear is defined as slope > NONLINEAR_SLOPE_THRESHOLD * previous slope.
    
    Args:
        phases: List of phase results to analyze
    
    Returns:
        User count at which non-linearity was detected, or 0 if not found
    """
    if len(phases) < 3:
        return 0
    p95s = [p.p95_ms for p in phases]
    users_list = [p.users for p in phases]
    for i in range(2, len(phases)):
        slope_prev = p95s[i - 1] - p95s[i - 2]
        slope_curr = p95s[i] - p95s[i - 1]
        if slope_prev > 0 and slope_curr > NONLINEAR_SLOPE_THRESHOLD * slope_prev:
            return users_list[i]
    return 0


def _first_error_users(phases: list[StressPhaseResult]) -> int:
    for p in phases:
        if p.error_rate_pct > 0:
            return p.users
    return 0


async def run_stress_test(
    requests: list[ParsedRequest],
    config: StressConfig,
    collection_name: str,
    report_path: str | Path,
    live: bool = True,
    junit_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> StressTestResult:
    """Run stress test: ramp users phase by phase until threshold exceeded; detect breaking point etc."""
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    if not requests:
        raise DeliRunnerError("No requests for stress test")

    logger.info("Starting stress test: collection=%s, scenario=%s, initial_users=%s, max_users=%s", collection_name, config.scenario.value, config.initial_users, config.max_users)
    console = Console()
    test_start_dt = datetime.now(timezone.utc)
    phases: list[StressPhaseResult] = []
    all_results: list[RequestResult] = []
    first_phase_start_ts: float | None = None
    last_phase_end_ts: float | None = None
    max_sustainable = config.initial_users
    breaking_point_users = 0
    current_users = config.initial_users

    def _append_phase_results(res: list[RequestResult], st: float, et: float) -> None:
        nonlocal first_phase_start_ts, last_phase_end_ts
        all_results.extend(res)
        if first_phase_start_ts is None:
            first_phase_start_ts = st
        last_phase_end_ts = et

    if config.scenario == StressScenario.SPIKE_STRESS and config.spike_users > 0:
        # Single spike phase
        hold = config.spike_hold_seconds or 30.0
        res, st, et = await run_phase(config.spike_users, hold, requests, config.think_time_ms)
        _append_phase_results(res, st, et)
        pr = _phase_metrics(res, st, et, 0, config.spike_users, hold, config)
        phases.append(pr)
        if pr.threshold_exceeded:
            breaking_point_users = config.spike_users
            max_sustainable = 0
        else:
            max_sustainable = config.spike_users
        # No further phases
        current_users = config.max_users + 1
    elif config.scenario == StressScenario.SOAK_STRESS and config.soak_users > 0 and config.soak_duration_seconds > 0:
        # Soak phase then ramp
        res, st, et = await run_phase(
            config.soak_users,
            config.soak_duration_seconds,
            requests,
            config.think_time_ms,
        )
        _append_phase_results(res, st, et)
        pr = _phase_metrics(res, st, et, 0, config.soak_users, config.soak_duration_seconds, config)
        phases.append(pr)
        if pr.threshold_exceeded:
            max_sustainable = 0
            breaking_point_users = config.soak_users
            current_users = config.max_users + 1
        else:
            max_sustainable = config.soak_users
            current_users = config.initial_users
    # else: linear_overload, current_users = initial_users

    phase_idx = len(phases)
    while current_users <= config.max_users:
        if live:
            console.print(f"[cyan]Stress phase[/cyan]: {current_users} users, {config.step_interval_seconds}s ...")
        res, st, et = await run_phase(
            current_users,
            config.step_interval_seconds,
            requests,
            config.think_time_ms,
        )
        _append_phase_results(res, st, et)
        pr = _phase_metrics(
            res, st, et, phase_idx, current_users, config.step_interval_seconds, config
        )
        phases.append(pr)

        if pr.threshold_exceeded:
            breaking_point_users = current_users
            max_sustainable = max(0, current_users - config.step_users) if phase_idx > 0 else 0
            if live:
                console.print(f"[red]Threshold exceeded[/red]: {pr.exceeded_reason}. Stopping.")
            break

        max_sustainable = current_users
        phase_idx += 1
        current_users += config.step_users

    test_end_dt = datetime.now(timezone.utc)
    first_error_at = _first_error_users(phases)
    nonlinear_at = _detect_nonlinear_latency(phases)

    result = StressTestResult(
        phases=phases,
        max_sustainable_load_users=max_sustainable,
        breaking_point_users=breaking_point_users,
        first_error_at_users=first_error_at,
        nonlinear_latency_at_users=nonlinear_at,
        recovery_seconds=0.0,  # Not measured in current design
        start_datetime=test_start_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        end_datetime=test_end_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        collection_name=collection_name,
        scenario=config.scenario.value,
    )

    # Use same report format as load test (report.html); add timestamp so runs do not overwrite
    out = Path(report_path)
    if out.suffix.lower() != ".html":
        out = out / "report.html" if not out.suffix or out.is_dir() else out.with_suffix(".html")
    stem_ts = out.stem + "_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = out.parent / (stem_ts + out.suffix)
    total_duration_seconds = (last_phase_end_ts - first_phase_start_ts) if (first_phase_start_ts is not None and last_phase_end_ts is not None) else 0.0
    report_users = max_sustainable if max_sustainable > 0 else (breaking_point_users or config.initial_users)
    run_config = RunConfig(
        users=report_users,
        ramp_up_seconds=0,
        duration_seconds=round(total_duration_seconds, 1),
        iterations=0,
        think_time_ms=config.think_time_ms,
        scenario=LoadScenario.CONSTANT,
        sla_p95_ms=config.sla_p95_ms,
        sla_p99_ms=config.sla_p99_ms,
        sla_error_rate_pct=config.sla_error_rate_pct,
    )
    collector = MetricsCollector(max_results=100_000)
    for r in all_results:
        collector.add(r)
    if last_phase_end_ts is not None:
        collector.set_end_time(last_phase_end_ts)
    from .report import generate_report, generate_junit_report, generate_json_report
    generate_report(
        out,
        collector,
        run_config,
        collection_name=collection_name,
        start_dt=test_start_dt,
        end_dt=test_end_dt,
        scenario_label=config.scenario.value,
    )
    if junit_path:
        generate_junit_report(
            junit_path,
            collector,
            run_config,
            collection_name=collection_name,
            start_dt=test_start_dt,
            end_dt=test_end_dt,
            scenario_label=config.scenario.value,
        )
        if live:
            console.print(f"[dim]JUnit report:[/dim] {junit_path}")
    if json_path:
        generate_json_report(
            json_path,
            collector,
            run_config,
            collection_name=collection_name,
            start_dt=test_start_dt,
            end_dt=test_end_dt,
            scenario_label=config.scenario.value,
        )
        if live:
            console.print(f"[dim]JSON report:[/dim] {json_path}")
    logger.info("Stress test finished: max_sustainable=%s, breaking_point=%s", result.max_sustainable_load_users, result.breaking_point_users)
    if live:
        console.print(f"[green]Report written to[/green] {out}")

    return result
