"""Rich live dashboard with low overhead for real-time metrics."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.panel import Panel

from .logging_config import get_logger
from .metrics import MetricsCollector
from .models import RunConfig
from .scenarios import expected_active_users

if TYPE_CHECKING:
    pass

logger = get_logger("dashboard")


def _safe_agg(collector: MetricsCollector, cache_ttl_sec: float = 0.5):
    """Cached aggregate for live view (low overhead, avoid full scan every frame)."""
    try:
        return collector.get_cached_aggregate(cache_ttl_sec=cache_ttl_sec)
    except Exception as e:
        logger.debug("Failed to get aggregate metrics: %s", e)
        return None


def build_metrics_table(
    collector: MetricsCollector,
    config: RunConfig,
    elapsed_seconds: float,
) -> Table:
    """Build a single Rich table with current metrics."""
    agg = _safe_agg(collector)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column(style="green")

    expected = expected_active_users(config, elapsed_seconds)
    table.add_row("Active users (expected)", str(expected))
    table.add_row("Total requests", str(len(collector.results)))

    if agg:
        table.add_row("TPS", f"{agg.tps:.1f}")
        table.add_row("Avg response (ms)", f"{agg.avg_response_time_ms:.1f}")
        table.add_row("P95 (ms)", f"{agg.p95_ms:.1f}")
        table.add_row("P99 (ms)", f"{agg.p99_ms:.1f}")
        table.add_row("Error rate %", f"{agg.error_rate_pct:.2f}%")
        table.add_row("Success rate %", f"{agg.success_rate_pct:.2f}%")
    else:
        table.add_row("TPS", "-")
        table.add_row("Avg response (ms)", "-")
        table.add_row("P95 (ms)", "-")
        table.add_row("P99 (ms)", "-")
        table.add_row("Error rate %", "-")

    return table


def _format_remaining(seconds: float) -> str:
    """Format remaining time as Xs or Xm Ys."""
    s = max(0, int(round(seconds)))
    if s >= 60:
        m, s = divmod(s, 60)
        return f"{m}m {s}s"
    return f"{s}s"


def create_live_panel(
    collector: MetricsCollector,
    config: RunConfig,
    start_time: float,
) -> Panel:
    """Create Rich Panel for live display."""
    now = time.perf_counter()
    elapsed = now - start_time if start_time else 0
    if start_time:
        remaining = max(0.0, config.duration_seconds - elapsed)
    else:
        remaining = config.duration_seconds
    table = build_metrics_table(collector, config, elapsed)
    table.add_row("Elapsed", f"{elapsed:.1f}s / {config.duration_seconds}s")
    table.add_row("Remaining (ETA)", _format_remaining(remaining))
    title = Text()
    title.append("deli ", style="bold magenta")
    title.append(f"| {config.scenario.value} | {elapsed:.1f}s / {config.duration_seconds}s", style="dim")
    title.append(f" | ETA: {_format_remaining(remaining)}", style="bold yellow")
    return Panel(
        table,
        title=title,
        border_style="blue",
    )


async def run_live_dashboard(
    collector: MetricsCollector,
    config: RunConfig,
    start_time: float,
    refresh_interval: float = 0.5,
) -> None:
    """Run Rich Live display until duration_seconds from start_time."""
    console = Console()
    end_time = start_time + config.duration_seconds
    try:
        with Live(
            create_live_panel(collector, config, start_time),
            console=console,
            refresh_per_second=min(4, 1.0 / refresh_interval),
        ) as live:
            while time.perf_counter() < end_time + 2:
                live.update(create_live_panel(collector, config, start_time))
                await asyncio.sleep(refresh_interval)
    except Exception as e:
        logger.debug("Live dashboard stopped: %s", e)
