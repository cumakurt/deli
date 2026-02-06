"""Unit tests for engine (execute_request, run_worker, create_client, collect_results)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deli.engine import (
    create_client,
    execute_request,
    run_worker,
    collect_results,
)
from deli.models import ParsedRequest, RequestResult


def test_get_prepared_headers_adds_content_type_when_body() -> None:
    """Test that Content-Type is added when body is present but no Content-Type header."""
    req = ParsedRequest(
        name="R", method="POST", url="https://example.com",
        headers={}, body='{"x":1}',
    )
    h = req.get_prepared_headers()
    assert "content-type" in [k.lower() for k in h]
    assert "application/json" in h.values()


def test_get_prepared_headers_preserves_existing_content_type() -> None:
    """Test that existing Content-Type header is not overwritten."""
    req = ParsedRequest(
        name="R", method="POST", url="https://example.com",
        headers={"Content-Type": "text/plain"}, body="raw",
    )
    h = req.get_prepared_headers()
    assert h.get("Content-Type") == "text/plain"


def test_get_prepared_headers_caches_result() -> None:
    """Test that get_prepared_headers() returns cached result on subsequent calls."""
    req = ParsedRequest(
        name="R", method="POST", url="https://example.com",
        headers={}, body='{"x":1}',
    )
    h1 = req.get_prepared_headers()
    h2 = req.get_prepared_headers()
    # Should be the same object (cached)
    assert h1 is h2


def test_execute_request_success() -> None:
    req = ParsedRequest(name="R", method="GET", url="https://httpbin.org/get")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    result = asyncio.run(execute_request(mock_client, req, 0))
    assert result.success is True
    assert result.status_code == 200
    assert result.request_name == "R"
    assert result.response_time_ms >= 0


def test_execute_request_4xx_failure() -> None:
    req = ParsedRequest(name="R", method="GET", url="https://example.com")
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    result = asyncio.run(execute_request(mock_client, req, 0))
    assert result.success is False
    assert result.status_code == 404


def test_execute_request_network_error() -> None:
    req = ParsedRequest(name="R", method="GET", url="https://example.com")
    mock_client = MagicMock()
    mock_client.request = AsyncMock(side_effect=ConnectionError("failed"))
    result = asyncio.run(execute_request(mock_client, req, 0))
    assert result.success is False
    assert result.status_code is None
    assert result.error == "failed"


def test_execute_request_think_time() -> None:
    req = ParsedRequest(name="R", method="GET", url="https://example.com")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    import time
    t0 = time.perf_counter()
    asyncio.run(execute_request(mock_client, req, 20))
    elapsed = (time.perf_counter() - t0) * 1000
    assert elapsed >= 15


def test_run_worker_puts_results_and_sentinel() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    req = ParsedRequest(name="R", method="GET", url="https://x.com")
    mock_result = RequestResult(
        request_name="R", folder_path="", method="GET", url="https://x.com",
        status_code=200, response_time_ms=1, success=True, timestamp=0,
    )
    mock_client = MagicMock()
    call_count = 0

    async def fake_execute(client, r, think_ms):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            stop.set()
        return mock_result

    with patch("deli.engine.execute_request", side_effect=fake_execute):
        asyncio.run(run_worker(mock_client, [req], 0, queue, stop, 0))
    items = []
    while not queue.empty():
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert any(r is not None for r in items)
    assert None in items


def test_run_worker_iterations_limit() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    req = ParsedRequest(name="R", method="GET", url="https://x.com")
    mock_result = RequestResult(
        request_name="R", folder_path="", method="GET", url="https://x.com",
        status_code=200, response_time_ms=1, success=True, timestamp=0,
    )
    mock_client = MagicMock()
    with patch("deli.engine.execute_request", AsyncMock(return_value=mock_result)):
        asyncio.run(run_worker(mock_client, [req], 0, queue, stop, iterations=2))
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert None in items
    assert sum(1 for x in items if x is not None) == 2


def test_run_worker_semaphore_limits_concurrency() -> None:
    """With semaphore(1), at most one execute_request is in flight at a time."""
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    req = ParsedRequest(name="R", method="GET", url="https://x.com")
    mock_result = RequestResult(
        request_name="R", folder_path="", method="GET", url="https://x.com",
        status_code=200, response_time_ms=1, success=True, timestamp=0,
    )
    mock_client = MagicMock()
    in_flight = 0
    max_in_flight = 0

    async def fake_execute(client, r, think_ms):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        if in_flight > max_in_flight:
            max_in_flight = in_flight
        await asyncio.sleep(0.02)
        in_flight -= 1
        return mock_result

    sem = asyncio.Semaphore(1)
    with patch("deli.engine.execute_request", side_effect=fake_execute):
        asyncio.run(
            run_worker(mock_client, [req], 0, queue, stop, iterations=3, semaphore=sem)
        )
    assert max_in_flight == 1
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert sum(1 for x in items if x is not None) == 3
    assert None in items


def test_create_client_returns_async_client() -> None:
    async def _run():
        client = await create_client(http2=True, timeout=10)
        assert client is not None
        try:
            async with client:
                pass
        except Exception:
            pass
    asyncio.run(_run())


def test_collect_results_consumes_until_sentinels() -> None:
    async def _run():
        queue = asyncio.Queue()
        r1 = RequestResult("a", "", "GET", "u", 200, 1, True, 0)
        queue.put_nowait(r1)
        queue.put_nowait(None)
        queue.put_nowait(None)
        results = []
        async for r in collect_results(queue, 2):
            results.append(r)
        return results
    results = asyncio.run(_run())
    assert len(results) == 1
    assert results[0].request_name == "a"
    assert results[0].status_code == 200
