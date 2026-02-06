"""Unit tests for dashboard (build_metrics_table, create_live_panel, _safe_agg)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from deli.dashboard import build_metrics_table, create_live_panel, run_live_dashboard
from deli.metrics import MetricsCollector
from deli.models import LoadScenario, RequestResult, RunConfig


def _config(users: int = 10, duration_seconds: float = 60) -> RunConfig:
    return RunConfig(
        users=users,
        ramp_up_seconds=5,
        duration_seconds=duration_seconds,
        iterations=0,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
    )


def test_build_metrics_table_empty_collector() -> None:
    collector = MetricsCollector(max_results=1000)
    config = _config()
    table = build_metrics_table(collector, config, 0)
    assert table is not None
    # Empty collector: TPS etc show "-"
    # We can't easily assert Rich Table content; just ensure no exception
    assert hasattr(table, "add_row")


def test_build_metrics_table_with_results() -> None:
    collector = MetricsCollector(max_results=1000)
    for i in range(5):
        collector.add(
            RequestResult(
                request_name="R", folder_path="", method="GET", url="https://x.com",
                status_code=200, response_time_ms=50 + i, success=True, timestamp=i / 10,
            )
        )
    config = _config()
    table = build_metrics_table(collector, config, 1)
    assert table is not None


def test_create_live_panel() -> None:
    collector = MetricsCollector(max_results=1000)
    collector.add(
        RequestResult(
            request_name="R", folder_path="", method="GET", url="https://x.com",
            status_code=200, response_time_ms=100, success=True, timestamp=0,
        )
    )
    config = _config()
    panel = create_live_panel(collector, config, 0)
    assert panel is not None
    assert hasattr(panel, "renderable") or hasattr(panel, "title")


def test_run_live_dashboard_short() -> None:
    import asyncio
    import time
    collector = MetricsCollector(max_results=1000)
    config = RunConfig(
        users=1,
        ramp_up_seconds=0,
        duration_seconds=0.05,
        iterations=0,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
    )
    start = time.perf_counter()
    asyncio.run(run_live_dashboard(collector, config, start, refresh_interval=0.02))
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.04
