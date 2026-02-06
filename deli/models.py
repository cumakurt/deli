"""Data models for deli execution engine.

Optimized for high-throughput, low-memory load testing:
- __slots__ on hot-path classes to reduce memory and improve access speed
- Minimal object allocation on request/result paths
- Enum for type safety without runtime overhead
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LoadScenario(str, Enum):
    """Load pattern during test."""

    GRADUAL = "gradual"  # Ramp-up then sustain
    CONSTANT = "constant"  # Fixed concurrent users
    SPIKE = "spike"  # Sudden spike then drop


class ParsedRequest:
    """A single HTTP request parsed from Postman collection.
    
    Uses __slots__ for memory efficiency - each instance saves ~100 bytes.
    Headers are cached after first preparation to avoid repeated dict creation.
    """
    
    __slots__ = ("name", "method", "url", "headers", "body", "folder_path", "_prepared_headers")
    
    def __init__(
        self,
        name: str,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        folder_path: str = "",
    ) -> None:
        self.name = name
        self.method = method
        self.url = url
        self.headers = headers if headers is not None else {}
        self.body = body
        self.folder_path = folder_path
        self._prepared_headers: dict[str, str] | None = None

    def get_prepared_headers(self) -> dict[str, str]:
        """Get prepared headers with Content-Type added if needed.
        
        Computed once on first call, then cached. Zero allocation on cache hit.
        """
        if self._prepared_headers is not None:
            return self._prepared_headers
        
        h = dict(self.headers)
        if self.body and "content-type" not in {k.lower() for k in h}:
            h["Content-Type"] = "application/json"
        self._prepared_headers = h
        return self._prepared_headers
    
    def __repr__(self) -> str:
        return f"ParsedRequest(name={self.name!r}, method={self.method!r}, url={self.url!r})"


class RequestResult:
    """Result of a single request execution.
    
    Uses __slots__ for memory efficiency - each instance saves ~100 bytes.
    This is the most allocated object during load tests; optimization critical.
    """
    
    __slots__ = (
        "request_name", "folder_path", "method", "url", 
        "status_code", "response_time_ms", "success", "error", "timestamp"
    )
    
    def __init__(
        self,
        request_name: str,
        folder_path: str,
        method: str,
        url: str,
        status_code: int | None,
        response_time_ms: float,
        success: bool,
        error: str | None = None,
        timestamp: float = 0.0,
    ) -> None:
        self.request_name = request_name
        self.folder_path = folder_path
        self.method = method
        self.url = url
        self.status_code = status_code
        self.response_time_ms = response_time_ms
        self.success = success
        self.error = error
        self.timestamp = timestamp
    
    def __repr__(self) -> str:
        return (
            f"RequestResult(name={self.request_name!r}, status={self.status_code}, "
            f"time_ms={self.response_time_ms:.2f}, success={self.success})"
        )


@dataclass(slots=True)
class RunConfig:
    """Runtime configuration from YAML.
    
    Uses slots=True for memory efficiency. Immutable after creation.
    """

    users: int
    ramp_up_seconds: float
    duration_seconds: float
    iterations: int  # 0 = run for duration, >0 = run N iterations per user
    think_time_ms: float
    scenario: LoadScenario
    # Spike-specific
    spike_users: int = 0
    spike_duration_seconds: float = 0.0
    # SLA (optional)
    sla_p95_ms: float | None = None
    sla_p99_ms: float | None = None
    sla_error_rate_pct: float | None = None


@dataclass(slots=True)
class AggregateMetrics:
    """Aggregated metrics for a time window or full run.
    
    Uses slots=True for memory efficiency. response_times_ms is only
    populated when histogram is needed (report generation), keeping
    memory low during live monitoring.
    """

    total_requests: int
    successful_requests: int
    failed_requests: int
    total_duration_ms: float
    # response_times_ms: kept for histogram in reports, but computed lazily or empty
    response_times_ms: list[float] = field(default_factory=list)
    tps: float = 0.0
    avg_response_time_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    error_rate_pct: float = 0.0
    # Status code distribution for reports (computed during aggregation)
    status_code_counts: dict[str, int] = field(default_factory=dict)
    # Advanced metrics
    apdex_score: float = 0.0
    top_errors: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate_pct(self) -> float:
        if self.total_requests == 0:
            return 100.0
        return 100.0 * self.successful_requests / self.total_requests


# --- Stress testing ---

class StressScenario(str, Enum):
    """Stress test pattern."""

    LINEAR_OVERLOAD = "linear_overload"  # Gradual user increase until threshold
    SPIKE_STRESS = "spike_stress"        # Sudden spike then hold
    SOAK_STRESS = "soak_stress"          # Soak at baseline then ramp (soak + stress)


@dataclass(slots=True)
class StressConfig:
    """Stress test configuration (separate YAML, industry-style thresholds)."""

    sla_p95_ms: float
    sla_p99_ms: float
    sla_error_rate_pct: float
    initial_users: int
    step_users: int
    step_interval_seconds: float
    max_users: int
    sla_timeout_rate_pct: float = 5.0
    think_time_ms: float = 0.0
    scenario: StressScenario = StressScenario.LINEAR_OVERLOAD
    spike_users: int = 0
    spike_hold_seconds: float = 30.0
    soak_users: int = 0
    soak_duration_seconds: float = 0.0


@dataclass(slots=True)
class StressPhaseResult:
    """Metrics for one stress phase (one load level)."""

    phase: int
    users: int
    duration_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    tps: float
    avg_response_time_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate_pct: float
    timeout_count: int
    timeout_rate_pct: float
    threshold_exceeded: bool
    exceeded_reason: str = ""


@dataclass(slots=True)
class StressTestResult:
    """Full stress test result for report."""

    phases: list[StressPhaseResult]
    max_sustainable_load_users: int
    breaking_point_users: int
    first_error_at_users: int
    nonlinear_latency_at_users: int
    recovery_seconds: float
    start_datetime: str
    end_datetime: str
    collection_name: str
    scenario: str
