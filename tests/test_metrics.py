"""Unit tests for metrics aggregation and collector."""

from __future__ import annotations

import pytest

from deli.metrics import MetricsCollector, TimeSeriesPoint, compute_aggregate
from deli.models import AggregateMetrics, RequestResult, RunConfig
from deli.models import LoadScenario


def _result(
    name: str = "r",
    status: int | None = 200,
    response_time_ms: float = 100.0,
    success: bool = True,
    timestamp_ms: float = 0,
) -> RequestResult:
    return RequestResult(
        request_name=name,
        folder_path="",
        method="GET",
        url="https://example.com",
        status_code=status,
        response_time_ms=response_time_ms,
        success=success,
        timestamp=timestamp_ms / 1000,
    )


def test_compute_aggregate_empty_window() -> None:
    agg = compute_aggregate([], 0, 1000)
    assert agg.total_requests == 0
    assert agg.total_duration_ms == 1000
    assert agg.response_times_ms == []


def test_compute_aggregate_single_request() -> None:
    r = _result(timestamp_ms=500, response_time_ms=50)
    agg = compute_aggregate([r], 0, 1000)
    assert agg.total_requests == 1
    assert agg.successful_requests == 1
    assert agg.tps > 0
    assert agg.avg_response_time_ms == 50
    assert agg.p50_ms == 50
    assert agg.p95_ms == 50
    assert agg.p99_ms == 50
    assert agg.error_rate_pct == 0


def test_compute_aggregate_multiple() -> None:
    results = [
        _result(timestamp_ms=100, response_time_ms=10),
        _result(timestamp_ms=200, response_time_ms=20),
        _result(timestamp_ms=300, response_time_ms=30),
        _result(timestamp_ms=400, response_time_ms=40),
        _result(timestamp_ms=500, response_time_ms=50),
    ]
    agg = compute_aggregate(results, 0, 1000)
    assert agg.total_requests == 5
    assert agg.avg_response_time_ms == 30
    assert agg.p50_ms == 30
    assert agg.p95_ms >= 40  # linear interpolation for 5 points
    assert agg.error_rate_pct == 0


def test_compute_aggregate_failures() -> None:
    results = [
        _result(success=True, status=200),
        _result(success=False, status=500),
    ]
    for i, r in enumerate(results):
        r.timestamp = i / 1000
    agg = compute_aggregate(results, 0, 100)
    assert agg.total_requests == 2
    assert agg.successful_requests == 1
    assert agg.failed_requests == 1
    assert agg.error_rate_pct == 50


def test_metrics_collector_add_and_full_aggregate() -> None:
    c = MetricsCollector(max_results=1000)
    for i in range(5):
        c.add(_result(timestamp_ms=i * 100, response_time_ms=10 + i))
    agg = c.full_aggregate()
    assert agg.total_requests == 5
    assert agg.avg_response_time_ms == 12  # 10,11,12,13,14


def test_metrics_collector_time_series_1s() -> None:
    c = MetricsCollector(max_results=1000)
    c._start_time = 0
    for sec in range(3):
        for _ in range(2):
            c.add(_result(timestamp_ms=sec * 1000, response_time_ms=50))
    series = c.time_series_1s()
    assert len(series) == 3
    assert series[0].tps == 2
    assert series[1].tps == 2
    assert series[2].tps == 2


def test_metrics_collector_sla_violations() -> None:
    config = RunConfig(
        users=10,
        ramp_up_seconds=5,
        duration_seconds=60,
        iterations=0,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
        sla_p95_ms=50,
        sla_p99_ms=100,
        sla_error_rate_pct=1.0,
    )
    c = MetricsCollector(max_results=1000)
    for i in range(10):
        c.add(_result(timestamp_ms=i, response_time_ms=200))  # all above SLA
    violations = c.sla_violations(config)
    assert len(violations) >= 1
    assert any("P95" in v for v in violations)


def test_metrics_collector_ring_buffer_bounded() -> None:
    """Ring-buffer: adding more than maxlen keeps size at maxlen (oldest dropped)."""
    c = MetricsCollector(max_results=5)
    for i in range(10):
        c.add(_result(timestamp_ms=i, response_time_ms=10 + i))
    assert len(c.results) == 5
    assert c.results[0].response_time_ms == 5 + 10
    assert c.results[-1].response_time_ms == 9 + 10


def test_metrics_collector_get_first_results() -> None:
    c = MetricsCollector(max_results=100)
    for i in range(5):
        c.add(_result(timestamp_ms=i, response_time_ms=10 + i))
    first3 = c.get_first_results(3)
    assert len(first3) == 3
    assert first3[0].response_time_ms == 10
    assert first3[2].response_time_ms == 12


def test_metrics_collector_get_recent_results() -> None:
    c = MetricsCollector(max_results=100)
    for i in range(5):
        c.add(_result(timestamp_ms=i, response_time_ms=10 + i))
    last2 = c.get_recent_results(2)
    assert len(last2) == 2
    assert last2[0].response_time_ms == 13
    assert last2[1].response_time_ms == 14


def test_metrics_collector_get_recent_results_more_than_stored() -> None:
    c = MetricsCollector(max_results=100)
    for i in range(3):
        c.add(_result(timestamp_ms=i, response_time_ms=10))
    last10 = c.get_recent_results(10)
    assert len(last10) == 3


def test_metrics_collector_get_cached_aggregate() -> None:
    c = MetricsCollector(max_results=100)
    for i in range(3):
        c.add(_result(timestamp_ms=i, response_time_ms=50))
    agg1 = c.get_cached_aggregate(cache_ttl_sec=1.0)
    agg2 = c.get_cached_aggregate(cache_ttl_sec=1.0)
    assert agg1.total_requests == agg2.total_requests == 3
    assert agg1.avg_response_time_ms == agg2.avg_response_time_ms


def test_compute_aggregate_with_deque() -> None:
    """compute_aggregate accepts deque (ring-buffer)."""
    from collections import deque
    results = deque([
        _result(timestamp_ms=100, response_time_ms=10),
        _result(timestamp_ms=200, response_time_ms=20),
    ], maxlen=10)
    agg = compute_aggregate(results, 0, 1000)
    assert agg.total_requests == 2
    assert agg.avg_response_time_ms == 15
