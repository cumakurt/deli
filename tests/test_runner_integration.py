"""Integration tests for runner (with mocked HTTP)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from deli.exceptions import DeliRunnerError
from deli.models import RequestResult
from deli.runner import run_manual_test, run_postman_test_mode, run_test


@pytest.fixture
def minimal_config_path(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(
        "users: 2\nramp_up_seconds: 0\nduration_seconds: 1\niterations: 1\nscenario: constant\n"
    )
    return tmp_path / "config.yaml"


def test_run_manual_test_integration(minimal_config_path: Path, tmp_path: Path) -> None:
    """Run manual test with mocked execute_request (no real HTTP)."""
    report_path = tmp_path / "report.html"
    call_count = 0

    async def fake_execute(client, req, think_time_ms):
        nonlocal call_count
        call_count += 1
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=200,
            response_time_ms=50,
            success=True,
            timestamp=time.perf_counter(),
        )

    with patch("deli.engine.execute_request", side_effect=fake_execute):
        asyncio.run(
            run_manual_test(
                "https://httpbin.org/get",
                report_path,
                config_path=minimal_config_path,
                live=False,
            )
        )
    assert report_path.exists()
    assert call_count >= 1
    content = report_path.read_text(encoding="utf-8")
    assert "Load" in content or "deli" in content or "report" in content.lower()


def test_run_manual_test_without_config_file(tmp_path: Path) -> None:
    """Run manual test without -f: config from CLI args only (defaults + --users, --duration)."""
    from deli.models import LoadScenario, RunConfig
    from deli.runner import run_manual_test

    report_path = tmp_path / "report.html"
    config = RunConfig(
        users=2,
        ramp_up_seconds=0,
        duration_seconds=1,
        iterations=1,
        think_time_ms=0,
        scenario=LoadScenario.CONSTANT,
    )

    async def fake_execute(client, req, think_time_ms):
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=200,
            response_time_ms=50,
            success=True,
            timestamp=time.perf_counter(),
        )

    with patch("deli.engine.execute_request", side_effect=fake_execute):
        asyncio.run(
            run_manual_test(
                "https://httpbin.org/get",
                report_path,
                config_path=None,
                config_override=config,
                live=False,
            )
        )
    assert report_path.exists()


def test_run_test_no_requests_raises(minimal_config_path: Path, tmp_path: Path) -> None:
    """Empty collection raises DeliRunnerError."""
    empty_collection = tmp_path / "empty.json"
    empty_collection.write_text(
        '{"info":{"name":"E","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},'
        '"item":[]}'
    )
    with pytest.raises(DeliRunnerError, match="No requests found"):
        asyncio.run(
            run_test(
                empty_collection,
                tmp_path / "out.html",
                config_path=minimal_config_path,
                live=False,
            )
        )


def test_run_postman_test_mode_with_environment(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{"name": "Get", "request": {"method": "GET", "url": "{{base_url}}/ping"}}]
        }""",
        encoding="utf-8",
    )
    environment = tmp_path / "environment.json"
    environment.write_text(
        """{"values": [{"key": "base_url", "value": "https://api.example.com", "enabled": true}]}""",
        encoding="utf-8",
    )
    report_path = tmp_path / "test_report.html"
    seen_urls: list[str] = []

    async def fake_execute(client, req, think_time_ms):
        seen_urls.append(req.url)
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=200,
            response_time_ms=25,
            success=True,
            timestamp=time.perf_counter(),
        )

    with patch("deli.engine.execute_request", side_effect=fake_execute):
        agg = asyncio.run(
            run_postman_test_mode(
                collection,
                report_path,
                environment_path=environment,
                live=False,
            )
        )

    assert agg.total_requests == 5
    assert agg.failed_requests == 0
    assert seen_urls == ["https://api.example.com/ping"] * 5
    assert report_path.exists()


def test_run_postman_test_mode_rejects_unresolved_variables(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{"name": "Get", "request": {"method": "GET", "url": "{{base_url}}/ping"}}]
        }""",
        encoding="utf-8",
    )

    with patch("deli.engine.execute_request") as execute_request:
        with pytest.raises(DeliRunnerError, match="Refusing to continue"):
            asyncio.run(
                run_postman_test_mode(
                    collection,
                    tmp_path / "test_report.html",
                    live=False,
                )
            )

    execute_request.assert_not_called()


def test_run_postman_test_mode_can_continue_after_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{"name": "Get", "request": {"method": "GET", "url": "{{base_url}}/ping"}}]
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen_urls: list[str] = []

    async def fake_execute(client, req, think_time_ms):
        seen_urls.append(req.url)
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=200,
            response_time_ms=25,
            success=True,
            timestamp=time.perf_counter(),
        )

    with patch("builtins.input", return_value="y"):
        with patch("deli.engine.execute_request", side_effect=fake_execute):
            agg = asyncio.run(
                run_postman_test_mode(
                    collection,
                    tmp_path / "test_report.html",
                    live=False,
                )
            )

    assert agg.total_requests == 5
    assert seen_urls == ["{{base_url}}/ping"] * 5
