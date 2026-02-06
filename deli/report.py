"""HTML report generator with ECharts - executive summary, charts, tables, offline-capable."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import orjson
from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__ as deli_version
from . import __author__ as deli_author
from . import __email__ as deli_email
from .metrics import MetricsCollector, TimeSeriesPoint
from .models import RequestResult, RunConfig

# Footer developer links (repo from pyproject; update if moved)
FOOTER_LINKEDIN_URL = "https://www.linkedin.com/in/cuma-kurt-34414917/"
FOOTER_GITHUB_REPO_URL = "https://github.com/cumakurt/deli"

# Headers that must be redacted in reports (case-insensitive)
SENSITIVE_HEADER_NAMES = frozenset(
    k.lower()
    for k in (
        "Authorization",
        "Cookie",
        "Set-Cookie",
        "X-Api-Key",
        "X-Auth-Token",
        "Api-Key",
        "ApiKey",
        "Token",
        "Proxy-Authorization",
    )
)
REDACTED_PLACEHOLDER = "[REDACTED]"


def mask_url(url: str, max_path_length: int = 120) -> str:
    """Remove query string and fragment from URL to avoid leaking tokens in reports."""
    if not url or not url.strip():
        return url
    try:
        parsed = urlparse(url)
        # Keep scheme, netloc, path; drop query and fragment
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path or "", "", "", ""))
        if len(clean) > max_path_length:
            clean = clean[: max_path_length - 3] + "..."
        return clean
    except Exception:
        return url[:max_path_length] + ("..." if len(url) > max_path_length else "")


def mask_error_message(msg: str | None, max_length: int = 200) -> str:
    """Truncate error message and redact URLs to avoid leaking sensitive data."""
    if not msg:
        return ""
    # Redact URL-like substrings
    msg = re.sub(r"https?://[^\s]+", REDACTED_PLACEHOLDER, msg)
    if len(msg) > max_length:
        return msg[: max_length - 3] + "..."
    return msg


def _get_echarts_script() -> str:
    """Embed ECharts from vendor file for fully offline single-file HTML. No CDN."""
    vendor_path = Path(__file__).resolve().parent / "templates" / "vendor" / "echarts.min.js"
    if vendor_path.exists():
        return "<script>\n" + vendor_path.read_text(encoding="utf-8") + "\n</script>"
    return "<!-- ECharts not bundled. Add templates/vendor/echarts.min.js for offline charts. -->"

# Raw data: full export is written to a separate JSON file (no limit); HTML report stays light
RAW_DATA_JSON_SUFFIX = "_raw.json"


def _serialize(obj: Any) -> str:
    """JSON-serialize for HTML embedding (orjson). Safe for script context (no </script>)."""
    s = orjson.dumps(obj).decode("utf-8")
    return s.replace("</", "<\\/")


def _compute_violations(agg: "AggregateMetrics", config: RunConfig) -> list[str]:
    """Compute SLA violations from pre-computed aggregate (no re-aggregation)."""
    from .models import AggregateMetrics
    violations: list[str] = []
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


def _build_test_assessments(
    agg: "AggregateMetrics",
    config: RunConfig,
    violations: list[str],
) -> list[str]:
    """Build human-readable evaluations and comments based on test results."""
    assessments: list[str] = []
    if agg.total_requests == 0:
        assessments.append("No requests were recorded; check target availability and test configuration.")
        return assessments
    if violations:
        assessments.append("SLA thresholds were exceeded; review capacity or optimization.")
    if agg.success_rate_pct >= 99:
        assessments.append("Success rate is excellent (≥99%); system is stable under load.")
    elif agg.success_rate_pct >= 95:
        assessments.append("Success rate is good (≥95%); minor errors may warrant follow-up.")
    elif agg.success_rate_pct >= 80:
        assessments.append("Success rate is acceptable but error rate should be investigated.")
    else:
        assessments.append("Low success rate; prioritize failure analysis and stability fixes.")
    if config.sla_p95_ms is not None and agg.p95_ms <= config.sla_p95_ms and agg.total_requests > 0:
        assessments.append(f"P95 latency ({agg.p95_ms:.1f} ms) is within SLA ({config.sla_p95_ms} ms).")
    elif config.sla_p95_ms is not None and agg.p95_ms > config.sla_p95_ms:
        assessments.append(f"P95 latency ({agg.p95_ms:.1f} ms) exceeds SLA ({config.sla_p95_ms} ms).")
    if agg.error_rate_pct > 0:
        assessments.append(f"Failed requests: {agg.failed_requests} ({agg.error_rate_pct:.2f}%). Review error messages and endpoints.")
    if agg.tps > 0:
        assessments.append(f"Throughput: {agg.tps:.1f} TPS over {agg.total_requests} total requests.")
    return assessments


def generate_report(
    output_path: str | Path,
    collector: MetricsCollector,
    config: RunConfig,
    collection_name: str = "Load Test",
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    scenario_label: str | None = None,
) -> None:
    """Generate a single self-contained HTML report with ECharts.
    Use scenario_label to override the scenario name in the report (e.g. for stress test)."""
    # Single aggregation call with response times for histogram
    agg = collector.full_aggregate(include_response_times=True)
    time_series = collector.time_series_1s()
    by_endpoint = collector.endpoint_aggregates()
    # Use pre-computed aggregate for SLA check (no re-computation)
    violations = _compute_violations(agg, config)

    # Time-series data for TPS, latency, error charts (relative time: 0s, 1s, 2s...)
    tps_labels = [f"{i}s" for i in range(len(time_series))]
    tps_values = [p.tps for p in time_series]
    avg_rt_values = [round(p.avg_ms, 2) for p in time_series]
    p95_rt_values = [round(p.p95_ms, 2) for p in time_series]
    error_rate_values = [round(p.error_rate_pct, 2) for p in time_series]

    # Response time distribution buckets (histogram)
    times = agg.response_times_ms or []
    if times:
        step = max(1, (max(times) - min(times)) / 20) if len(set(times)) > 1 else 1
        buckets: dict[float, int] = {}
        for t in times:
            b = round(t / step) * step
            buckets[b] = buckets.get(b, 0) + 1
        dist_labels = [str(round(k)) for k in sorted(buckets.keys())]
        dist_values = [buckets[k] for k in sorted(buckets.keys())]
    else:
        dist_labels = []
        dist_values = []

    # Status code distribution (for pie chart) - use pre-computed from aggregation
    status_code_counts = agg.status_code_counts
    status_pie_data = [{"name": f"{k}", "value": v} for k, v in sorted(status_code_counts.items(), key=lambda x: -x[1])]

    # Success / Failed for donut
    success_count = agg.successful_requests
    failed_count = agg.failed_requests
    # Success / Failed for donut
    success_count = agg.successful_requests
    failed_count = agg.failed_requests
    success_fail_donut = [{"name": "Success", "value": success_count}, {"name": "Failed", "value": failed_count}] if (success_count or failed_count) else []

    # Top Errors for bar chart
    top_errors = agg.top_errors or {}
    top_error_labels = [k[:60] + "..." if len(k) > 60 else k for k in top_errors.keys()]
    top_error_values = list(top_errors.values())

    # Percentiles for comparison bar chart (P50, P95, P99)
    percentile_names = ["P50", "P95", "P99"]
    percentile_values = [round(agg.p50_ms, 2), round(agg.p95_ms, 2), round(agg.p99_ms, 2)]

    # Min/Max/Std response time (report-time only; times already loaded above for histogram)
    min_rt_ms = round(min(times), 2) if times else 0.0
    max_rt_ms = round(max(times), 2) if times else 0.0
    if times:
        mean_rt = sum(times) / len(times)
        variance = sum((t - mean_rt) ** 2 for t in times) / len(times)
        std_rt_ms = round((variance ** 0.5), 2)
    else:
        std_rt_ms = 0.0

    # SLA summary for report (report-time only)
    sla_summary: list[dict[str, Any]] = []
    if config.sla_p95_ms is not None:
        sla_summary.append({
            "name": "P95 Latency",
            "target_ms": config.sla_p95_ms,
            "actual_ms": round(agg.p95_ms, 2),
            "met": agg.p95_ms <= config.sla_p95_ms,
        })
    if config.sla_p99_ms is not None:
        sla_summary.append({
            "name": "P99 Latency",
            "target_ms": config.sla_p99_ms,
            "actual_ms": round(agg.p99_ms, 2),
            "met": agg.p99_ms <= config.sla_p99_ms,
        })
    if config.sla_error_rate_pct is not None:
        sla_summary.append({
            "name": "Error Rate",
            "target_pct": config.sla_error_rate_pct,
            "actual_pct": round(agg.error_rate_pct, 2),
            "met": agg.error_rate_pct <= config.sla_error_rate_pct,
        })

    # Test configuration summary (for report card)
    test_config_summary = {
        "users": config.users,
        "duration_seconds": config.duration_seconds,
        "ramp_up_seconds": config.ramp_up_seconds,
        "scenario": config.scenario.value,
        "think_time_ms": config.think_time_ms,
        "sla_p95_ms": config.sla_p95_ms,
        "sla_p99_ms": config.sla_p99_ms,
        "sla_error_rate_pct": config.sla_error_rate_pct,
    }

    # Trend comment: first half vs second half TPS (report-time only; time_series already computed)
    trend_comment: str | None = None
    if len(time_series) >= 4:
        mid = len(time_series) // 2
        tps_first = sum(p.tps for p in time_series[:mid]) / mid if mid else 0
        tps_second = sum(p.tps for p in time_series[mid:]) / (len(time_series) - mid) if (len(time_series) - mid) else 0
        if tps_second > tps_first * 1.1:
            trend_comment = f"TPS increased in second half (avg {tps_second:.1f} vs {tps_first:.1f} in first half); load may still be ramping."
        elif tps_second < tps_first * 0.9:
            trend_comment = f"TPS decreased in second half (avg {tps_second:.1f} vs {tps_first:.1f} in first half); possible degradation or throttling."

    # Short test interpretation (verdict + summary)
    if agg.total_requests == 0:
        test_verdict = "No data"
        test_summary = "No requests were recorded."
    else:
        if violations:
            test_verdict = "SLA violations detected"
            test_summary = f"Success rate {agg.success_rate_pct:.1f}%, P95 {agg.p95_ms:.1f} ms. {len(violations)} SLA violation(s)."
        elif agg.success_rate_pct >= 99 and agg.error_rate_pct < 1:
            test_verdict = "Excellent"
            test_summary = f"Success rate {agg.success_rate_pct:.1f}%, P95 {agg.p95_ms:.1f} ms. Test passed with high stability."
        elif agg.success_rate_pct >= 95:
            test_verdict = "Good"
            test_summary = f"Success rate {agg.success_rate_pct:.1f}%, P95 {agg.p95_ms:.1f} ms. Minor errors ({agg.error_rate_pct:.1f}%)."
        elif agg.success_rate_pct >= 80:
            test_verdict = "Acceptable"
            test_summary = f"Success rate {agg.success_rate_pct:.1f}%, P95 {agg.p95_ms:.1f} ms. Review error rate ({agg.error_rate_pct:.1f}%)."
        else:
            test_verdict = "Needs attention"
            test_summary = f"Success rate {agg.success_rate_pct:.1f}%, error rate {agg.error_rate_pct:.1f}%. Investigate failures."
    test_verdict_class = "danger" if violations or agg.success_rate_pct < 80 else ("warning" if agg.success_rate_pct < 95 else "success")

    # Executive summary narrative (high-level, non-technical for CISO/management)
    if agg.total_requests == 0:
        executive_summary = (
            "No load test data was recorded. Verify target availability and test configuration."
        )
    elif violations:
        executive_summary = (
            f"This load test ran with {config.users} virtual users for {config.duration_seconds:.0f} seconds "
            f"({config.scenario.value} scenario). The system processed {agg.total_requests:,} requests at "
            f"{agg.tps:.1f} TPS with {agg.success_rate_pct:.1f}% success rate. "
            f"SLA thresholds were exceeded in {len(violations)} area(s); review the SLA Violations section "
            "and consider capacity or optimization actions."
        )
    elif agg.success_rate_pct >= 99:
        executive_summary = (
            f"This load test ran with {config.users} virtual users for {config.duration_seconds:.0f} seconds "
            f"({config.scenario.value} scenario). The system demonstrated strong stability: {agg.total_requests:,} requests "
            f"at {agg.tps:.1f} TPS with {agg.success_rate_pct:.1f}% success rate and P95 latency {agg.p95_ms:.1f} ms. "
            "No SLA violations were observed. Results are suitable for baseline and capacity planning."
        )
    else:
        executive_summary = (
            f"This load test ran with {config.users} virtual users for {config.duration_seconds:.0f} seconds "
            f"({config.scenario.value} scenario). The system processed {agg.total_requests:,} requests at "
            f"{agg.tps:.1f} TPS with {agg.success_rate_pct:.1f}% success rate and P95 latency {agg.p95_ms:.1f} ms. "
            "Review the metrics and error rate sections for any follow-up actions."
        )

    # Endpoint table data (mask URLs in endpoint key for display)
    endpoint_rows = []
    for key, ep_agg in sorted(by_endpoint.items(), key=lambda x: -x[1].total_requests):
        # key is "METHOD URL"; mask URL part
        parts = key.split(" ", 1)
        display_key = f"{parts[0]} {mask_url(parts[1])}" if len(parts) == 2 else key
        endpoint_rows.append({
            "endpoint": display_key,
            "total": ep_agg.total_requests,
            "success": ep_agg.successful_requests,
            "failed": ep_agg.failed_requests,
            "tps": round(ep_agg.tps, 2),
            "avg_ms": round(ep_agg.avg_response_time_ms, 2),
            "p95_ms": round(ep_agg.p95_ms, 2),
            "p99_ms": round(ep_agg.p99_ms, 2),
            "error_pct": round(ep_agg.error_rate_pct, 2),
        })

    # Method distribution (GET, POST, etc.) and status distribution (200, 404, ...)
    from collections import defaultdict
    method_counts: dict[str, int] = defaultdict(int)
    for r in collector.results:
        method_counts[r.method or "?"] += 1
    method_distribution = [
        {"method": m, "count": c}
        for m, c in sorted(method_counts.items(), key=lambda x: -x[1])
    ]
    status_distribution = [
        {"status": k, "count": v}
        for k, v in sorted(status_code_counts.items(), key=lambda x: -x[1])
    ]

    # Test result assessments and comments
    test_assessments = _build_test_assessments(agg, config, violations)

    # Write full raw request data to a separate JSON file (no limit)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_json_path = out_path.parent / (out_path.stem + RAW_DATA_JSON_SUFFIX)
    raw_payload = [
        {
            "request_name": r.request_name,
            "folder_path": r.folder_path,
            "method": r.method,
            "url": mask_url(r.url, 120),
            "status_code": r.status_code,
            "response_time_ms": round(r.response_time_ms, 2),
            "success": r.success,
            "error": mask_error_message(r.error, 200),
        }
        for r in collector.results
    ]
    raw_json_path.write_bytes(orjson.dumps(raw_payload, option=orjson.OPT_INDENT_2))
    raw_data_json_filename = raw_json_path.name

    method_distribution_json = _serialize(method_distribution)
    status_distribution_json = _serialize(status_distribution)

    env = Environment(
        loader=PackageLoader("deli", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    scenario_display = scenario_label if scenario_label is not None else config.scenario.value
    template = env.get_template("report.html")
    html = template.render(
        collection_name=collection_name,
        scenario=scenario_display,
        users=config.users,
        duration_seconds=config.duration_seconds,
        ramp_up_seconds=config.ramp_up_seconds,
        total_requests=agg.total_requests,
        successful_requests=agg.successful_requests,
        failed_requests=agg.failed_requests,
        tps=round(agg.tps, 2),
        avg_response_time_ms=round(agg.avg_response_time_ms, 2),
        p50_ms=round(agg.p50_ms, 2),
        p95_ms=round(agg.p95_ms, 2),
        p99_ms=round(agg.p99_ms, 2),
        error_rate_pct=round(agg.error_rate_pct, 2),
        success_rate_pct=round(agg.success_rate_pct, 2),
        sla_violations=violations,
        tps_labels=_serialize(tps_labels),
        tps_values=_serialize(tps_values),
        avg_rt_values=_serialize(avg_rt_values),
        p95_rt_values=_serialize(p95_rt_values),
        error_rate_values=_serialize(error_rate_values),
        executive_summary=executive_summary,
        dist_labels=_serialize(dist_labels),
        dist_values=_serialize(dist_values),
        status_pie_data=_serialize(status_pie_data),
        success_fail_donut=_serialize(success_fail_donut),
        success_rate_pct_value=round(agg.success_rate_pct, 1),
        apdex_score=round(agg.apdex_score, 2),
        top_error_labels=_serialize(top_error_labels),
        top_error_values=_serialize(top_error_values),
        percentile_names=_serialize(percentile_names),
        percentile_values=_serialize(percentile_values),
        test_verdict=test_verdict,
        test_summary=test_summary,
        test_verdict_class=test_verdict_class,
        endpoint_rows=endpoint_rows,
        method_distribution_json=method_distribution_json,
        status_distribution_json=status_distribution_json,
        test_assessments=test_assessments,
        raw_data_json_filename=raw_data_json_filename,
        raw_total=len(collector.results),
        min_rt_ms=min_rt_ms,
        max_rt_ms=max_rt_ms,
        std_rt_ms=std_rt_ms,
        sla_summary=sla_summary,
        test_config_summary=test_config_summary,
        trend_comment=trend_comment,
        developer_info={
            "deli_version": deli_version,
            "report_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
        footer_developer={
            "author_name": deli_author,
            "author_email": deli_email,
            "linkedin_url": FOOTER_LINKEDIN_URL,
            "github_repo_url": FOOTER_GITHUB_REPO_URL,
        },
        echarts_script=_get_echarts_script(),
        start_datetime_str=start_dt.strftime("%Y-%m-%d %H:%M:%S UTC") if start_dt else "",
        end_datetime_str=end_dt.strftime("%Y-%m-%d %H:%M:%S UTC") if end_dt else "",
    )

    out_path.write_text(html, encoding="utf-8")


def generate_junit_report(
    output_path: str | Path,
    collector: MetricsCollector,
    config: RunConfig,
    collection_name: str = "Load Test",
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    scenario_label: str | None = None,
) -> None:
    """Write JUnit XML report for CI (e.g. Jenkins, GitLab). SLA violations become failed testcases."""
    import xml.etree.ElementTree as ET
    from xml.dom import minidom

    agg = collector.full_aggregate()
    violations = collector.sla_violations(config)
    scenario_display = scenario_label if scenario_label else getattr(config, "scenario", None)
    scenario_str = scenario_display.value if hasattr(scenario_display, "value") else str(scenario_display)

    testsuite = ET.Element(
        "testsuite",
        name=f"deli.{collection_name}",
        tests="1",
        failures=str(1 if violations else 0),
        errors="0",
        skipped="0",
        time=f"{(agg.total_duration_ms or 0) / 1000:.3f}",
    )
    if start_dt:
        testsuite.set("timestamp", start_dt.strftime("%Y-%m-%dT%H:%M:%S"))
    testcase = ET.SubElement(
        testsuite,
        "testcase",
        name=f"load_test_{scenario_str}",
        classname=f"deli.{collection_name}",
        time=f"{(agg.total_duration_ms or 0) / 1000:.3f}",
    )
    if violations:
        failure = ET.SubElement(testcase, "failure", message="SLA violation(s)")
        failure.text = "\n".join(violations)
    system_out = ET.SubElement(testcase, "system-out")
    system_out.text = (
        f"total_requests={agg.total_requests} tps={agg.tps:.2f} "
        f"p95_ms={agg.p95_ms:.2f} error_rate_pct={agg.error_rate_pct:.2f}"
    )

    tree = ET.ElementTree(ET.Element("testsuites"))
    root = tree.getroot()
    root.append(testsuite)
    xml_str = minidom.parseString(ET.tostring(root, encoding="unicode", method="xml")).toprettyxml(indent="  ")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml_str, encoding="utf-8")


def generate_json_report(
    output_path: str | Path,
    collector: MetricsCollector,
    config: RunConfig,
    collection_name: str = "Load Test",
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    scenario_label: str | None = None,
) -> None:
    """Write machine-readable JSON report with aggregate metrics and SLA violations."""
    agg = collector.full_aggregate()
    violations = collector.sla_violations(config)
    scenario_display = scenario_label if scenario_label else getattr(config, "scenario", None)
    scenario_str = scenario_display.value if hasattr(scenario_display, "value") else str(scenario_display)

    payload: dict[str, Any] = {
        "collection_name": collection_name,
        "scenario": scenario_str,
        "users": getattr(config, "users", 0),
        "duration_seconds": getattr(config, "duration_seconds", 0),
        "start_datetime": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if start_dt else None,
        "end_datetime": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if end_dt else None,
        "total_requests": agg.total_requests,
        "successful_requests": agg.successful_requests,
        "failed_requests": agg.failed_requests,
        "tps": round(agg.tps, 4),
        "avg_response_time_ms": round(agg.avg_response_time_ms, 4),
        "p50_ms": round(agg.p50_ms, 4),
        "p95_ms": round(agg.p95_ms, 4),
        "p99_ms": round(agg.p99_ms, 4),
        "error_rate_pct": round(agg.error_rate_pct, 4),
        "success_rate_pct": round(agg.success_rate_pct, 4),
        "sla_violations": violations,
        "passed": len(violations) == 0,
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
