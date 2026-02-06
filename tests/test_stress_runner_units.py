"""Unit tests for stress_runner helpers (_timeout_count, _phase_metrics, _detect_nonlinear_latency, _first_error_users)."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from deli.models import (
    RequestResult,
    StressConfig,
    StressPhaseResult,
    StressScenario,
)
from deli.stress_runner import (
    _timeout_count,
    _phase_metrics,
    _detect_nonlinear_latency,
    _first_error_users,
    run_phase,
)


def _result(success: bool, error: str | None = None, status_code: int | None = 200) -> RequestResult:
    return RequestResult(
        request_name="R", folder_path="", method="GET", url="https://x.com",
        status_code=status_code, response_time_ms=10, success=success, error=error, timestamp=0,
    )


def test_timeout_count_none() -> None:
    results = [_result(True), _result(True)]
    assert _timeout_count(results) == 0


def test_timeout_count_with_timeout_error() -> None:
    results = [_result(False, error="Connection timeout"), _result(True)]
    assert _timeout_count(results) == 1


def test_timeout_count_status_none() -> None:
    results = [_result(False, status_code=None)]
    assert _timeout_count(results) == 1


def test_phase_metrics_no_exceed() -> None:
    config = StressConfig(
        sla_p95_ms=500,
        sla_p99_ms=1000,
        sla_error_rate_pct=1.0,
        initial_users=5,
        step_users=5,
        step_interval_seconds=30,
        max_users=100,
        scenario=StressScenario.LINEAR_OVERLOAD,
    )
    results = [_result(True) for _ in range(10)]
    start_ts, end_ts = 0, 1
    pr = _phase_metrics(results, start_ts, end_ts, 0, 5, 1, config)
    assert pr.phase == 0
    assert pr.users == 5
    assert pr.threshold_exceeded is False
    assert pr.exceeded_reason == ""


def test_phase_metrics_exceed_p95() -> None:
    config = StressConfig(
        sla_p95_ms=10,
        sla_p99_ms=100,
        sla_error_rate_pct=5,
        initial_users=5,
        step_users=5,
        step_interval_seconds=30,
        max_users=100,
        scenario=StressScenario.LINEAR_OVERLOAD,
    )
    results = [_result(True) for _ in range(10)]
    for i, r in enumerate(results):
        r.response_time_ms = 500
        r.timestamp = i / 1000
    pr = _phase_metrics(results, 0, 1, 0, 5, 1, config)
    assert pr.threshold_exceeded is True
    assert "P95" in pr.exceeded_reason


def _phase(users: int, p95_ms: float) -> StressPhaseResult:
    return StressPhaseResult(
        phase=0, users=users, duration_seconds=30, total_requests=10,
        successful_requests=10, failed_requests=0, tps=1, avg_response_time_ms=p95_ms,
        p50_ms=p95_ms, p95_ms=p95_ms, p99_ms=p95_ms, error_rate_pct=0,
        timeout_count=0, timeout_rate_pct=0, threshold_exceeded=False, exceeded_reason="",
    )


def test_detect_nonlinear_latency_empty() -> None:
    assert _detect_nonlinear_latency([]) == 0
    assert _detect_nonlinear_latency([_phase(10, 10), _phase(20, 20)]) == 0


def test_detect_nonlinear_latency_jump() -> None:
    phases = [_phase(5, 10), _phase(10, 20), _phase(15, 100)]
    assert _detect_nonlinear_latency(phases) == 15


def test_first_error_users_none() -> None:
    phases = [
        StressPhaseResult(
            phase=0, users=5, duration_seconds=30, total_requests=100,
            successful_requests=100, failed_requests=0, tps=10,
            avg_response_time_ms=10, p50_ms=10, p95_ms=10, p99_ms=10,
            error_rate_pct=0, timeout_count=0, timeout_rate_pct=0,
            threshold_exceeded=False, exceeded_reason="",
        ),
        StressPhaseResult(
            phase=1, users=10, duration_seconds=30, total_requests=100,
            successful_requests=100, failed_requests=0, tps=10,
            avg_response_time_ms=10, p50_ms=10, p95_ms=10, p99_ms=10,
            error_rate_pct=0, timeout_count=0, timeout_rate_pct=0,
            threshold_exceeded=False, exceeded_reason="",
        ),
    ]
    assert _first_error_users(phases) == 0


def test_first_error_users_found() -> None:
    phases = [
        StressPhaseResult(
            phase=0, users=5, duration_seconds=30, total_requests=100,
            successful_requests=100, failed_requests=0, tps=10,
            avg_response_time_ms=10, p50_ms=10, p95_ms=10, p99_ms=10,
            error_rate_pct=0, timeout_count=0, timeout_rate_pct=0,
            threshold_exceeded=False, exceeded_reason="",
        ),
        StressPhaseResult(
            phase=1, users=10, duration_seconds=30, total_requests=100,
            successful_requests=95, failed_requests=5, tps=10,
            avg_response_time_ms=10, p50_ms=10, p95_ms=10, p99_ms=10,
            error_rate_pct=5, timeout_count=0, timeout_rate_pct=0,
            threshold_exceeded=False, exceeded_reason="",
        ),
    ]
    assert _first_error_users(phases) == 10


def test_run_phase_empty_requests() -> None:
    """run_phase with no requests returns immediately."""
    import asyncio
    from deli.models import ParsedRequest
    async def _run():
        return await run_phase(0, 1.0, [], 0)
    results_list, start_ts, end_ts = asyncio.run(_run())
    assert start_ts <= end_ts
    assert results_list == []
