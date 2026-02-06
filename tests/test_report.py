"""Unit tests for report masking and JUnit/JSON export."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from deli.metrics import MetricsCollector
from deli.models import LoadScenario, RequestResult, RunConfig
from deli.report import (
    mask_error_message,
    mask_url,
    generate_json_report,
    generate_junit_report,
)


def test_mask_url_removes_query_and_fragment() -> None:
    u = "https://api.example.com/path?token=secret&foo=bar#section"
    assert "?" not in mask_url(u)
    assert "token=" not in mask_url(u)
    assert "api.example.com" in mask_url(u)
    assert "/path" in mask_url(u)


def test_mask_url_short() -> None:
    assert mask_url("https://example.com/") == "https://example.com/"


def test_mask_error_message_redacts_urls() -> None:
    msg = "Connection failed to https://user:pass@host.com/api"
    out = mask_error_message(msg)
    assert "user" not in out
    assert "pass" not in out
    assert "[REDACTED]" in out


def test_mask_error_message_truncates() -> None:
    msg = "x" * 300
    out = mask_error_message(msg, max_length=100)
    assert len(out) <= 103
    assert out.endswith("...")


def _make_collector_with_results() -> tuple[MetricsCollector, RunConfig]:
    config = RunConfig(
        users=10,
        ramp_up_seconds=5,
        duration_seconds=60,
        iterations=0,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
        sla_p95_ms=500,
        sla_p99_ms=1000,
        sla_error_rate_pct=1.0,
    )
    c = MetricsCollector(max_results=1000)
    for i in range(5):
        c.add(
            RequestResult(
                request_name="r",
                folder_path="",
                method="GET",
                url="https://example.com/",
                status_code=200,
                response_time_ms=50 + i,
                success=True,
                timestamp=i / 10,
            )
        )
    c.set_end_time(1.0)
    return c, config


def test_generate_json_report(tmp_path: Path) -> None:
    c, config = _make_collector_with_results()
    out = tmp_path / "report.json"
    generate_json_report(out, c, config, collection_name="Test", scenario_label="constant")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["collection_name"] == "Test"
    assert data["scenario"] == "constant"
    assert data["total_requests"] == 5
    assert "tps" in data
    assert "p95_ms" in data
    assert data["passed"] is True
    assert data["sla_violations"] == []


def test_generate_junit_report(tmp_path: Path) -> None:
    c, config = _make_collector_with_results()
    out = tmp_path / "junit.xml"
    generate_junit_report(out, c, config, collection_name="Test", scenario_label="constant")
    assert out.exists()
    xml = out.read_text(encoding="utf-8")
    assert "<testsuites" in xml
    assert "<testsuite" in xml
    assert "deli.Test" in xml
    assert "<failure" not in xml  # no SLA violation (avoid matching "failures=")


def test_generate_report_full_html(tmp_path: Path) -> None:
    """generate_report produces valid HTML with key sections."""
    c, config = _make_collector_with_results()
    out = tmp_path / "report.html"
    from deli.report import generate_report
    from datetime import datetime, timezone
    start_dt = datetime.now(timezone.utc)
    end_dt = datetime.now(timezone.utc)
    generate_report(out, c, config, collection_name="Test", start_dt=start_dt, end_dt=end_dt)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Test" in html
    assert "Load" in html or "deli" in html.lower() or "report" in html.lower()
    assert "echarts" in html.lower() or "chart" in html.lower()
    assert "<!DOCTYPE" in html or "<html" in html


def test_generate_junit_report_with_failure(tmp_path: Path) -> None:
    config = RunConfig(
        users=10,
        ramp_up_seconds=5,
        duration_seconds=60,
        iterations=0,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
        sla_p95_ms=10,  # very strict
        sla_p99_ms=20,
        sla_error_rate_pct=0.1,
    )
    c = MetricsCollector(max_results=1000)
    for i in range(3):
        c.add(
            RequestResult(
                request_name="r",
                folder_path="",
                method="GET",
                url="https://example.com/",
                status_code=200,
                response_time_ms=500,  # above SLA
                success=True,
                timestamp=i / 10,
            )
        )
    c.set_end_time(1.0)
    out = tmp_path / "junit_fail.xml"
    generate_junit_report(out, c, config, collection_name="Test")
    assert out.exists()
    xml = out.read_text(encoding="utf-8")
    assert "<failure" in xml
    assert "SLA" in xml
