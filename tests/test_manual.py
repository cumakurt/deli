"""Unit tests for manual URL target module."""

from __future__ import annotations

import pytest

from deli.exceptions import DeliRunnerError
from deli.manual import build_manual_requests, manual_report_name


def test_build_manual_requests_valid() -> None:
    requests = build_manual_requests("https://api.example.com/health")
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url == "https://api.example.com/health"
    assert requests[0].name == "Manual Target"


def test_build_manual_requests_with_method_and_headers() -> None:
    requests = build_manual_requests(
        "https://api.example.com/post",
        method="POST",
        headers={"X-Custom": "value"},
    )
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].headers.get("X-Custom") == "value"


def test_build_manual_requests_empty_url() -> None:
    with pytest.raises(DeliRunnerError, match="Manual URL must not be empty"):
        build_manual_requests("")
    with pytest.raises(DeliRunnerError, match="Manual URL must not be empty"):
        build_manual_requests("   ")


def test_build_manual_requests_invalid_url() -> None:
    with pytest.raises(DeliRunnerError, match="Invalid manual URL"):
        build_manual_requests("not-a-url")
    with pytest.raises(DeliRunnerError, match="Invalid manual URL"):
        build_manual_requests("http://")  # no host


def test_manual_report_name() -> None:
    assert manual_report_name("https://api.example.com/health") == "api.example.com"
    assert manual_report_name("https://localhost:8080/path") == "localhost:8080"
