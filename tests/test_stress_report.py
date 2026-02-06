"""Unit tests for stress report (generate_stress_report)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.models import StressConfig, StressPhaseResult, StressScenario, StressTestResult
from deli.stress_report import generate_stress_report


def test_generate_stress_report(tmp_path: Path) -> None:
    config = StressConfig(
        sla_p95_ms=500,
        sla_p99_ms=1000,
        sla_error_rate_pct=1,
        initial_users=5,
        step_users=5,
        step_interval_seconds=30,
        max_users=100,
        scenario=StressScenario.LINEAR_OVERLOAD,
    )
    phases = [
        StressPhaseResult(
            phase=0, users=5, duration_seconds=30, total_requests=100,
            successful_requests=100, failed_requests=0, tps=3.33,
            avg_response_time_ms=50, p50_ms=45, p95_ms=80, p99_ms=120,
            error_rate_pct=0, timeout_count=0, timeout_rate_pct=0,
            threshold_exceeded=False, exceeded_reason="",
        ),
        StressPhaseResult(
            phase=1, users=10, duration_seconds=30, total_requests=200,
            successful_requests=195, failed_requests=5, tps=6.5,
            avg_response_time_ms=90, p50_ms=85, p95_ms=150, p99_ms=200,
            error_rate_pct=2.5, timeout_count=2, timeout_rate_pct=1,
            threshold_exceeded=False, exceeded_reason="",
        ),
    ]
    result = StressTestResult(
        phases=phases,
        max_sustainable_load_users=10,
        breaking_point_users=15,
        first_error_at_users=10,
        nonlinear_latency_at_users=10,
        recovery_seconds=0,
        start_datetime="2025-01-01 12:00:00 UTC",
        end_datetime="2025-01-01 12:05:00 UTC",
        collection_name="Test",
        scenario="linear_overload",
    )
    out = tmp_path / "stress_report.html"
    generate_stress_report(out, result, config)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Test" in html
    assert "linear_overload" in html
    assert "max_sustainable" in html or "sustainable" in html.lower()
    assert "breaking_point" in html or "breaking" in html.lower()
    assert "echarts" in html.lower() or "chart" in html.lower()
