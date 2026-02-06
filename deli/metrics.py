"""Metrics collection and aggregation with minimal memory footprint.

Ring-buffer storage (deque), T-Digest for streaming percentiles. Bounded memory only.
Single-pass aggregation with status code counting.

Performance optimizations:
- __slots__ on all classes for memory efficiency
- Streaming T-Digest for O(1) percentile updates
- Cached aggregate for live dashboard (avoid recomputation)
- Single-pass aggregation with status code counting
- Batch add support for bulk ingestion
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tdigest import TDigest

from .logging_config import get_logger
from .models import AggregateMetrics, RequestResult, RunConfig

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = get_logger("metrics")

# Default maximum results in collector ring buffer
DEFAULT_MAX_RESULTS = 100_000
# Cache TTL for live dashboard aggregates (seconds)
DEFAULT_CACHE_TTL_SEC = 0.5
# Log warning threshold for overflow (percentage of max capacity)
OVERFLOW_WARNING_THRESHOLD_PCT = 0.95
# Time series bucket size in seconds
TIME_SERIES_BUCKET_SEC = 1


@dataclass
class TimeSeriesPoint:
    """Single point for time-series (e.g. TPS per second)."""

    timestamp_ms: float
    tps: float
    avg_ms: float
    p95_ms: float
    error_rate_pct: float
    active_requests: int


def _percentile_from_digest(digest: TDigest, p: float) -> float:
    """Get percentile from T-Digest. Returns 0.0 if empty."""
    try:
        return digest.percentile(p) or 0.0
    except (ValueError, IndexError):
        return 0.0


def _percentile(sorted_times: list[float], p: float) -> float:
    """Fallback percentile for small lists."""
    if not sorted_times:
        return 0.0
    k = (len(sorted_times) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_times) else f
    return sorted_times[f] + (k - f) * (sorted_times[c] - sorted_times[f])


def compute_aggregate(
    results: list[RequestResult] | deque[RequestResult],
    window_start_ms: float,
    window_end_ms: float,
    include_response_times: bool = False,
) -> AggregateMetrics:
    """Compute aggregate metrics for a time window.
    
    Single-pass aggregation with T-Digest for percentiles and status code counting.
    Set include_response_times=True only when histogram is needed (report generation).
    """
    # Use T-Digest for memory-efficient percentile streaming
    digest = TDigest()
    total = 0
    success = 0
    failed = 0
    sum_times = 0.0
    status_counts: dict[str, int] = defaultdict(int)
    response_times: list[float] = [] if include_response_times else []
    
    for r in results:
        ts_ms = r.timestamp * 1000
        if not (window_start_ms <= ts_ms <= window_end_ms):
            continue
        
        total += 1
        if r.success:
            success += 1
        else:
            failed += 1
        
        rt = r.response_time_ms
        sum_times += rt
        digest.update(rt)
        
        # Status code counting (single pass, no extra iteration)
        key = str(r.status_code) if r.status_code is not None else "Error"
        status_counts[key] += 1
        
        # Only collect response times when needed for histogram
        if include_response_times:
            response_times.append(rt)
    
    if total == 0:
        return AggregateMetrics(
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            total_duration_ms=window_end_ms - window_start_ms,
            response_times_ms=[],
            status_code_counts={},
        )
    
    duration_ms = window_end_ms - window_start_ms
    tps = 1000.0 * total / duration_ms if duration_ms > 0 else 0.0
    
    return AggregateMetrics(
        total_requests=total,
        successful_requests=success,
        failed_requests=failed,
        total_duration_ms=duration_ms,
        response_times_ms=response_times,
        tps=tps,
        avg_response_time_ms=sum_times / total,
        p50_ms=_percentile_from_digest(digest, 50),
        p95_ms=_percentile_from_digest(digest, 95),
        p99_ms=_percentile_from_digest(digest, 99),
        error_rate_pct=100.0 * failed / total,
        status_code_counts=dict(status_counts),
    )


class MetricsCollector:
    """
    Collects RequestResults in a ring-buffer (deque). Fixed max size, no unbounded growth.
    Uses T-Digest for streaming percentile calculation.
    
    Overflow behavior: When the buffer is full, oldest results are silently dropped.
    A warning is logged when the buffer approaches capacity.
    """

    __slots__ = (
        "_results", "_max_results", "_start_time", "_end_time",
        "_agg_cache", "_agg_cache_time", "_digest", "_sum_times",
        "_success_count", "_failed_count", "_status_counts", "_error_counts",
        "_overflow_count", "_overflow_warned", "_total_added",
        "_satisfied_count", "_tolerating_count"  # For Apdex
    )

    def __init__(self, max_results: int = DEFAULT_MAX_RESULTS) -> None:
        self._results: deque[RequestResult] = deque(maxlen=max_results)
        self._max_results = max_results
        self._start_time: float | None = None
        self._end_time: float | None = None
        self._agg_cache: AggregateMetrics | None = None
        self._agg_cache_time: float = 0.0
        # Streaming metrics
        self._digest = TDigest()
        self._sum_times: float = 0.0
        self._success_count: int = 0
        self._failed_count: int = 0
        self._status_counts: dict[str, int] = defaultdict(int)
        self._error_counts: dict[str, int] = defaultdict(int)  # Track specific error messages
        # Apdex counters (T = 500ms default)
        self._satisfied_count: int = 0  # < T
        self._tolerating_count: int = 0 # T < t < 4T
        
        # Overflow tracking
        self._overflow_count: int = 0
        self._overflow_warned: bool = False
        self._total_added: int = 0

    @property
    def overflow_count(self) -> int:
        """Number of results dropped due to buffer overflow."""
        return self._overflow_count

    @property
    def total_added(self) -> int:
        """Total number of results added (including overflowed)."""
        return self._total_added

    def add(self, result: RequestResult) -> None:
        """Add a single result. Use add_batch for multiple results."""
        if self._start_time is None:
            self._start_time = result.timestamp
        self._end_time = result.timestamp
        
        # Track overflow before append (deque drops oldest automatically)
        current_len = len(self._results)
        if current_len >= self._max_results:
            self._overflow_count += 1
            if not self._overflow_warned:
                logger.warning(
                    "MetricsCollector buffer overflow: oldest results are being dropped. "
                    "Consider increasing max_results (current: %d) or reducing test duration.",
                    self._max_results
                )
                self._overflow_warned = True
        elif not self._overflow_warned and current_len >= int(self._max_results * OVERFLOW_WARNING_THRESHOLD_PCT):
            logger.warning(
                "MetricsCollector buffer approaching capacity (%d/%d, %.1f%%). "
                "Oldest results will be dropped when full.",
                current_len, self._max_results, 100.0 * current_len / self._max_results
            )
            self._overflow_warned = True
        
        self._results.append(result)
        self._total_added += 1
        
        # Update streaming metrics incrementally
        self._digest.update(result.response_time_ms)
        self._sum_times += result.response_time_ms
        if result.success:
            self._success_count += 1
        else:
            self._failed_count += 1
            # Track error message (truncate to avoid memory bloat)
            if result.error:
                msg = result.error[:200]
                self._error_counts[msg] += 1
            elif result.status_code:
                msg = f"HTTP {result.status_code}"
                self._error_counts[msg] += 1
        
        # Apdex tracking (T=500ms)
        # Satisfied: < 500ms
        # Tolerating: 500ms - 2000ms
        # Frustrated: > 2000ms or Error (failed)
        if not result.success:
            pass # Frustrated (already counted in total)
        elif result.response_time_ms < 500:
            self._satisfied_count += 1
        elif result.response_time_ms < 2000:
            self._tolerating_count += 1
        
        # Status code counting
        key = str(result.status_code) if result.status_code is not None else "Error"
        self._status_counts[key] += 1
        
        self._agg_cache = None

    def add_batch(self, results: Iterable[RequestResult]) -> None:
        """Add multiple results efficiently. Reduces per-item overhead.
        
        This is faster than calling add() in a loop because:
        - Single overflow check per batch
        - Local variable caching
        - Less function call overhead
        """
        # Local references for faster access
        deque_append = self._results.append
        digest_update = self._digest.update
        status_counts = self._status_counts
        max_results = self._max_results
        
        batch_count = 0
        batch_sum = 0.0
        batch_success = 0
        batch_failed = 0
        
        batch_error_counts = defaultdict(int)
        batch_satisfied = 0
        batch_tolerating = 0
        
        for result in results:
            if self._start_time is None:
                self._start_time = result.timestamp
            self._end_time = result.timestamp
            
            # Track overflow
            if len(self._results) >= max_results:
                self._overflow_count += 1
            
            deque_append(result)
            batch_count += 1
            
            rt = result.response_time_ms
            batch_sum += rt
            digest_update(rt)
            
            if result.success:
                batch_success += 1
                # Apdex
                if rt < 500:
                    batch_satisfied += 1
                elif rt < 2000:
                    batch_tolerating += 1
            else:
                batch_failed += 1
                # Track error
                if result.error:
                    msg = result.error[:200]
                    batch_error_counts[msg] += 1
                elif result.status_code:
                    msg = f"HTTP {result.status_code}"
                    batch_error_counts[msg] += 1
            
            key = str(result.status_code) if result.status_code is not None else "Error"
            status_counts[key] += 1
        
        self._total_added += batch_count
        self._sum_times += batch_sum
        self._success_count += batch_success
        self._failed_count += batch_failed
        self._satisfied_count += batch_satisfied
        self._tolerating_count += batch_tolerating
        
        for k, v in batch_error_counts.items():
            self._error_counts[k] += v
        self._agg_cache = None
        
        # Log overflow warning once
        if not self._overflow_warned and self._overflow_count > 0:
            logger.warning(
                "MetricsCollector buffer overflow: %d results dropped.",
                self._overflow_count
            )
            self._overflow_warned = True

    def set_end_time(self, t: float) -> None:
        self._end_time = t
        self._agg_cache = None

    @property
    def results(self) -> deque[RequestResult]:
        return self._results

    def get_first_results(self, n: int) -> list[RequestResult]:
        """First n results (oldest). O(n)."""
        from itertools import islice
        return list(islice(self._results, 0, n))

    def get_recent_results(self, n: int) -> list[RequestResult]:
        """Last n results (newest). O(n)."""
        from itertools import islice
        total = len(self._results)
        if total <= n:
            return list(self._results)
        return list(islice(self._results, total - n, None))

    @property
    def start_time(self) -> float:
        return self._start_time or 0.0

    @property
    def end_time(self) -> float:
        return self._end_time or time.perf_counter()

    def full_aggregate(self, include_response_times: bool = False) -> AggregateMetrics:
        """Compute full aggregate using streaming metrics (no recomputation).
        
        Set include_response_times=True only when histogram is needed.
        """
        total = self._success_count + self._failed_count
        if total == 0:
            dur = (self._end_time or time.perf_counter()) - (self._start_time or 0)
            return AggregateMetrics(
                total_requests=0,
                successful_requests=0,
                failed_requests=0,
                total_duration_ms=max(dur * 1000, 1),
                response_times_ms=[],
                status_code_counts={},
            )
        
        start_ms = (self._start_time or 0) * 1000
        end_ms = (self._end_time or self._results[-1].timestamp) * 1000
        duration_ms = end_ms - start_ms
        tps = 1000.0 * total / duration_ms if duration_ms > 0 else 0.0
        
        # Collect response times only when needed
        response_times: list[float] = []
        if include_response_times:
            response_times = [r.response_time_ms for r in self._results]
        
        # Calculate Apdex
        # Apdex = (Satisfied + Tolerating / 2) / Total
        apdex = 0.0
        if total > 0:
            apdex = (self._satisfied_count + (self._tolerating_count / 2.0)) / total

        # Top 5 Errors
        top_errors = sorted(self._error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_errors_dict = dict(top_errors)

        return AggregateMetrics(
            total_requests=total,
            successful_requests=self._success_count,
            failed_requests=self._failed_count,
            total_duration_ms=duration_ms,
            response_times_ms=response_times,
            tps=tps,
            avg_response_time_ms=self._sum_times / total,
            p50_ms=_percentile_from_digest(self._digest, 50),
            p95_ms=_percentile_from_digest(self._digest, 95),
            p99_ms=_percentile_from_digest(self._digest, 99),
            error_rate_pct=100.0 * self._failed_count / total,
            status_code_counts=dict(self._status_counts),
            apdex_score=apdex,
            top_errors=top_errors_dict,
        )

    def get_cached_aggregate(self, cache_ttl_sec: float = 0.5) -> AggregateMetrics:
        """Aggregate with short TTL cache for live dashboard (low overhead)."""
        now = time.perf_counter()
        if self._agg_cache is not None and (now - self._agg_cache_time) <= cache_ttl_sec:
            return self._agg_cache
        self._agg_cache = self.full_aggregate(include_response_times=False)
        self._agg_cache_time = now
        return self._agg_cache

    def time_series_1s(self) -> list[TimeSeriesPoint]:
        """Bucket results by second for TPS/time-series charts.
        
        Optimized single-pass implementation:
        - Uses integer bucket keys for faster hashing
        - Pre-allocates output list
        - Minimizes object creation
        """
        if not self._results:
            return []
        
        start = self._start_time or 0.0
        
        # Use dict with int keys for faster hashing
        # Format: bucket_sec -> (sum_times, count, failed_count, times_list)
        buckets: dict[int, tuple[float, int, int, list[float]]] = defaultdict(
            lambda: (0.0, 0, 0, [])
        )
        
        for r in self._results:
            sec = int(r.timestamp - start)
            sum_t, cnt, fail, times = buckets[sec]
            times.append(r.response_time_ms)
            buckets[sec] = (
                sum_t + r.response_time_ms,
                cnt + 1,
                fail + (0 if r.success else 1),
                times
            )
        
        # Pre-allocate output list
        out: list[TimeSeriesPoint] = []
        for sec in sorted(buckets.keys()):
            sum_t, total, failed, times = buckets[sec]
            times_sorted = sorted(times)
            t_start = start + sec
            out.append(
                TimeSeriesPoint(
                    timestamp_ms=t_start * 1000,
                    tps=total,
                    avg_ms=sum_t / total if total else 0,
                    p95_ms=_percentile(times_sorted, 95),
                    error_rate_pct=100.0 * failed / total if total else 0,
                    active_requests=total,
                )
            )
        return out

    def endpoint_aggregates(self) -> dict[str, AggregateMetrics]:
        """Per-endpoint (method + path key) aggregates. Single pass with tuple keys."""
        by_key: dict[tuple[str, str], list[RequestResult]] = defaultdict(list)
        for r in self._results:
            # Use tuple key for faster hashing
            by_key[(r.method, r.url)].append(r)
        
        start_ms = (self._start_time or 0) * 1000
        end_ms = (self._end_time or 0) * 1000
        if self._results:
            end_ms = max(r.timestamp * 1000 for r in self._results)
        
        result: dict[str, AggregateMetrics] = {}
        for (method, url), v in by_key.items():
            key = f"{method} {url}"
            result[key] = compute_aggregate(v, start_ms, end_ms, include_response_times=False)
        return result

    def sla_violations(self, config: RunConfig) -> list[str]:
        """Return list of SLA violation descriptions."""
        violations: list[str] = []
        agg = self.full_aggregate(include_response_times=False)
        if config.sla_p95_ms is not None and agg.p95_ms > config.sla_p95_ms:
            violations.append(
                f"P95 response time {agg.p95_ms:.1f}ms exceeds SLA {config.sla_p95_ms}ms"
            )
        if config.sla_p99_ms is not None and agg.p99_ms > config.sla_p99_ms:
            violations.append(
                f"P99 response time {agg.p99_ms:.1f}ms exceeds SLA {config.sla_p99_ms}ms"
            )
        if (
            config.sla_error_rate_pct is not None
            and agg.error_rate_pct > config.sla_error_rate_pct
        ):
            violations.append(
                f"Error rate {agg.error_rate_pct:.2f}% exceeds SLA {config.sla_error_rate_pct}%"
            )
        return violations
