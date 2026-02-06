"""
Manual URL target module — load test a single URL without Postman.

When -m URL is used, this module builds the request list from scratch.
No dependency on Postman collection or parser. Uses the same ParsedRequest
model so the rest of the pipeline (engine, scenarios, report) works unchanged.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .exceptions import DeliRunnerError
from .models import ParsedRequest


MANUAL_REQUEST_NAME = "Manual Target"
MANUAL_FOLDER_PATH = ""


def build_manual_requests(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> list[ParsedRequest]:
    """
    Build a single-request list for load testing the given URL.

    Used when -m URL is passed: no Postman, no collection. The same
    URL is hit repeatedly according to config (users, duration, scenario).

    Args:
        url: Full target URL (e.g. https://api.example.com/health).
        method: HTTP method (default GET).
        headers: Optional request headers.

    Returns:
        List with one ParsedRequest, for use with engine/scenarios.

    Raises:
        DeliRunnerError: If URL is empty or invalid.
    """
    url = url.strip()
    if not url:
        raise DeliRunnerError("Manual URL must not be empty")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise DeliRunnerError(f"Invalid manual URL: {url}")

    req = ParsedRequest(
        name=MANUAL_REQUEST_NAME,
        method=method.strip().upper() or "GET",
        url=url,
        headers=dict(headers or {}),
        body=None,
        folder_path=MANUAL_FOLDER_PATH,
    )
    return [req]


def manual_report_name(url: str) -> str:
    """Short label for report title when using manual URL (e.g. host only)."""
    parsed = urlparse(url.strip())
    return parsed.netloc or "manual"
