"""Unit tests for runner helpers (_resolve_report_path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.runner import _resolve_report_path


def test_resolve_report_path_html_suffix_unchanged() -> None:
    """Path with .html suffix is returned as-is (resolved)."""
    p = _resolve_report_path("out/report.html")
    assert p.suffix.lower() == ".html"
    assert p.name == "report.html"


def test_resolve_report_path_path_object_html() -> None:
    """Path object with .html is accepted."""
    p = _resolve_report_path(Path("dir/report.HTML"))
    assert p.suffix.lower() == ".html"
    assert p.name.lower() == "report.html"


def test_resolve_report_path_no_suffix_append_report_html() -> None:
    """Path with no suffix gets report.html appended."""
    p = _resolve_report_path("output")
    assert p.name == "report.html"
    assert p.parent.name == "output" or str(p).endswith("output/report.html")


def test_resolve_report_path_other_suffix_replaced() -> None:
    """Path with non-html suffix gets .html replacement."""
    p = _resolve_report_path("report.json")
    assert p.suffix.lower() == ".html"
    assert p.stem == "report"


def test_resolve_report_path_dir_like_append_report_html() -> None:
    """Path that looks like a directory (trailing slash or no suffix) gets report.html."""
    p = _resolve_report_path("reports/")
    assert p.name == "report.html"
    assert "reports" in str(p)
