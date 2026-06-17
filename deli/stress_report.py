"""Stress test HTML report: breaking point, load vs latency, error curves, System Behavior Summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from .models import StressConfig, StressTestResult
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


def _phase_payload(result: StressTestResult) -> list[dict[str, Any]]:
    return [
        {
            "phase": p.phase + 1,
            "users": p.users,
            "duration_seconds": p.duration_seconds,
            "total_requests": p.total_requests,
            "successful_requests": p.successful_requests,
            "failed_requests": p.failed_requests,
            "tps": p.tps,
            "avg_response_time_ms": p.avg_response_time_ms,
            "p50_ms": p.p50_ms,
            "p95_ms": p.p95_ms,
            "p99_ms": p.p99_ms,
            "error_rate_pct": p.error_rate_pct,
            "timeout_count": p.timeout_count,
            "timeout_rate_pct": p.timeout_rate_pct,
            "threshold_exceeded": p.threshold_exceeded,
            "exceeded_reason": p.exceeded_reason,
        }
        for p in result.phases
    ]


def generate_stress_json_report(
    output_path: str | Path,
    result: StressTestResult,
    config: StressConfig,
) -> None:
    """Write machine-readable stress report with phase metrics and capacity findings."""
    payload: dict[str, Any] = {
        "collection_name": result.collection_name,
        "scenario": result.scenario,
        "start_datetime": result.start_datetime,
        "end_datetime": result.end_datetime,
        "max_sustainable_load_users": result.max_sustainable_load_users,
        "breaking_point_users": result.breaking_point_users,
        "first_error_at_users": result.first_error_at_users,
        "nonlinear_latency_at_users": result.nonlinear_latency_at_users,
        "recovery_seconds": result.recovery_seconds,
        "sla": {
            "p95_ms": config.sla_p95_ms,
            "p99_ms": config.sla_p99_ms,
            "error_rate_pct": config.sla_error_rate_pct,
            "timeout_rate_pct": config.sla_timeout_rate_pct,
        },
        "passed": all(not p.threshold_exceeded for p in result.phases),
        "phases": _phase_payload(result),
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_serialize(payload), encoding="utf-8")


def generate_stress_junit_report(
    output_path: str | Path,
    result: StressTestResult,
    config: StressConfig,
) -> None:
    """Write JUnit XML where threshold-exceeded phases are failed test cases."""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    failed_phases = [p for p in result.phases if p.threshold_exceeded]
    failure_count = len(failed_phases) if result.phases else 1
    testsuite = ET.Element(
        "testsuite",
        name=f"deli.stress.{result.collection_name}",
        tests=str(max(1, len(result.phases))),
        failures=str(failure_count),
        errors="0",
        skipped="0",
        time=f"{sum(p.duration_seconds for p in result.phases):.3f}",
    )

    if not result.phases:
        testcase = ET.SubElement(
            testsuite,
            "testcase",
            name="stress_no_phases",
            classname=f"deli.stress.{result.collection_name}",
            time="0.000",
        )
        failure = ET.SubElement(testcase, "failure", message="No stress phases executed")
        failure.text = "Stress test completed without executing any phase."
    else:
        for p in result.phases:
            testcase = ET.SubElement(
                testsuite,
                "testcase",
                name=f"phase_{p.phase + 1}_{p.users}_users",
                classname=f"deli.stress.{result.collection_name}",
                time=f"{p.duration_seconds:.3f}",
            )
            if p.threshold_exceeded:
                failure = ET.SubElement(
                    testcase,
                    "failure",
                    message=p.exceeded_reason or "Stress threshold exceeded",
                )
                failure.text = (
                    f"users={p.users} p95_ms={p.p95_ms:.2f} p99_ms={p.p99_ms:.2f} "
                    f"error_rate_pct={p.error_rate_pct:.2f} timeout_rate_pct={p.timeout_rate_pct:.2f}"
                )
            system_out = ET.SubElement(testcase, "system-out")
            system_out.text = (
                f"users={p.users} total_requests={p.total_requests} tps={p.tps:.2f} "
                f"p95_ms={p.p95_ms:.2f} error_rate_pct={p.error_rate_pct:.2f}"
            )

    properties = ET.SubElement(testsuite, "properties")
    for name, value in {
        "max_sustainable_load_users": result.max_sustainable_load_users,
        "breaking_point_users": result.breaking_point_users,
        "sla_p95_ms": config.sla_p95_ms,
        "sla_p99_ms": config.sla_p99_ms,
        "sla_error_rate_pct": config.sla_error_rate_pct,
        "sla_timeout_rate_pct": config.sla_timeout_rate_pct,
    }.items():
        ET.SubElement(properties, "property", name=name, value=str(value))

    root = ET.Element("testsuites")
    root.append(testsuite)
    xml_str = minidom.parseString(ET.tostring(root, encoding="unicode", method="xml")).toprettyxml(
        indent="  "
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml_str, encoding="utf-8")
