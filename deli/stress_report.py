"""Stress test HTML report: breaking point, load vs latency, error curves, System Behavior Summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import StressConfig, StressPhaseResult, StressTestResult
from .report import _get_echarts_script


def _serialize(obj: Any) -> str:
    s = json.dumps(obj, allow_nan=False)
    return s.replace("</", "<\\/")


def generate_stress_report(
    output_path: str | Path,
    result: StressTestResult,
    config: StressConfig,
) -> None:
    """Generate stress test HTML report with ECharts."""
    phases = result.phases
    phase_users = [p.users for p in phases]
    phase_labels = [str(p.users) for p in phases]
    phase_p95 = [p.p95_ms for p in phases]
    phase_p99 = [p.p99_ms for p in phases]
    phase_error_rate = [p.error_rate_pct for p in phases]
    phase_tps = [p.tps for p in phases]
    phase_timeout_rate = [p.timeout_rate_pct for p in phases]

    # Phase table rows
    phase_rows = [
        {
            "phase": p.phase + 1,
            "users": p.users,
            "duration_s": p.duration_seconds,
            "total": p.total_requests,
            "tps": p.tps,
            "p95_ms": p.p95_ms,
            "p99_ms": p.p99_ms,
            "error_pct": p.error_rate_pct,
            "timeout_pct": p.timeout_rate_pct,
            "threshold_exceeded": p.threshold_exceeded,
            "exceeded_reason": p.exceeded_reason or "",
        }
        for p in phases
    ]

    env = Environment(
        loader=PackageLoader("deli", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("stress_report.html")
    html = template.render(
        collection_name=result.collection_name,
        scenario=result.scenario,
        start_datetime=result.start_datetime,
        end_datetime=result.end_datetime,
        max_sustainable_load_users=result.max_sustainable_load_users,
        breaking_point_users=result.breaking_point_users,
        first_error_at_users=result.first_error_at_users,
        nonlinear_latency_at_users=result.nonlinear_latency_at_users,
        recovery_seconds=result.recovery_seconds,
        sla_p95_ms=config.sla_p95_ms,
        sla_p99_ms=config.sla_p99_ms,
        sla_error_rate_pct=config.sla_error_rate_pct,
        phase_labels=_serialize(phase_labels),
        phase_users=_serialize(phase_users),
        phase_p95=_serialize(phase_p95),
        phase_p99=_serialize(phase_p99),
        phase_error_rate=_serialize(phase_error_rate),
        phase_tps=_serialize(phase_tps),
        phase_timeout_rate=_serialize(phase_timeout_rate),
        phase_rows=phase_rows,
        echarts_script=_get_echarts_script(),
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
