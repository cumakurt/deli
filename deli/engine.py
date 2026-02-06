"""Lightweight async execution engine. Speed and minimal overhead first.

This module provides the core HTTP request execution logic:
- execute_request: Single request execution with timing
- run_worker: Continuous request loop until stop event
- create_client: Shared async HTTP client factory
- collect_results: Async generator for consuming results from queue

Performance optimizations:
- Body bytes cached per ParsedRequest (avoid repeated encode())
- perf_counter_ns for timing (faster than perf_counter)
- Minimal object allocation in hot path
- Queue.put_nowait when possible to avoid await overhead
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, TYPE_CHECKING

import httpx

from .models import ParsedRequest, RequestResult

if TYPE_CHECKING:
    pass

# Tuned for throughput: high connection limits, shared client, no per-request allocation beyond result.
DEFAULT_MAX_CONNECTIONS = 1000
DEFAULT_MAX_KEEPALIVE = 200
DEFAULT_KEEPALIVE_EXPIRY = 30.0
# Default timeout for HTTP requests (seconds)
DEFAULT_TIMEOUT_SEC = 30.0
# Sleep interval when requests list is empty (seconds)
EMPTY_REQUESTS_SLEEP_SEC = 0.1
# Nanoseconds to milliseconds conversion
NS_TO_MS = 1_000_000

# Body bytes cache: avoid repeated .encode() for same body
_body_cache: dict[int, bytes] = {}


def _get_body_bytes(req: ParsedRequest) -> bytes | None:
    """Get body bytes with caching. Avoids repeated encode() calls."""
    if req.body is None:
        return None
    # Use id() as key since ParsedRequest instances are reused
    req_id = id(req)
    cached = _body_cache.get(req_id)
    if cached is not None:
        return cached
    body_bytes = req.body.encode("utf-8")
    _body_cache[req_id] = body_bytes
    return body_bytes


async def execute_request(
    client: httpx.AsyncClient,
    req: ParsedRequest,
    think_time_ms: float,
) -> RequestResult:
    """Execute a single HTTP request and return result with timing.
    
    Args:
        client: Shared async HTTP client
        req: Parsed request with URL, method, headers, body
        think_time_ms: Delay before executing (simulates user think time)
    
    Returns:
        RequestResult with timing, status code, and success/failure info
    
    Note:
        This never raises - all errors are captured in the RequestResult.
        Uses perf_counter_ns for precise, low-overhead timing.
    """
    if think_time_ms > 0:
        await asyncio.sleep(think_time_ms / 1000.0)

    # Use cached prepared headers and body bytes
    headers = req.get_prepared_headers()
    body_bytes = _get_body_bytes(req)
    
    # perf_counter_ns is faster than perf_counter (no float conversion)
    start_ns = time.perf_counter_ns()
    try:
        r = await client.request(
            req.method,
            req.url,
            headers=headers,
            content=body_bytes,
        )
        elapsed_ms = (time.perf_counter_ns() - start_ns) / NS_TO_MS
        success = 200 <= r.status_code < 400
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=r.status_code,
            response_time_ms=elapsed_ms,
            success=success,
            error=None,
            timestamp=start_ns / 1_000_000_000,  # Convert to seconds
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (time.perf_counter_ns() - start_ns) / NS_TO_MS
        return RequestResult(
            request_name=req.name,
            folder_path=req.folder_path,
            method=req.method,
            url=req.url,
            status_code=None,
            response_time_ms=elapsed_ms,
            success=False,
            error=str(e),
            timestamp=start_ns / 1_000_000_000,
        )


async def run_worker(
    client: httpx.AsyncClient,
    requests: list[ParsedRequest],
    think_time_ms: float,
    result_queue: asyncio.Queue[RequestResult | None],
    stop_event: asyncio.Event,
    iterations: int,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    """
    Single worker: repeatedly executes requests in order until stop_event.
    
    Args:
        client: Shared async HTTP client
        requests: List of requests to cycle through
        think_time_ms: Delay between requests
        result_queue: Queue to put results into
        stop_event: Event to signal worker termination
        iterations: 0 = infinite until stop; >0 = run this many full cycles then exit
        semaphore: Optional limit on in-flight requests (backpressure)
    
    Note:
        Always sends None sentinel to result_queue when exiting.
        Uses put_nowait when queue has space for lower latency.
    """
    idx = 0
    cycle = 0
    num_requests = len(requests)
    
    # Local references for faster access in hot loop
    is_set = stop_event.is_set
    queue_put = result_queue.put
    queue_put_nowait = result_queue.put_nowait
    queue_full = result_queue.full
    
    try:
        while not is_set():
            if num_requests == 0:
                await asyncio.sleep(EMPTY_REQUESTS_SLEEP_SEC)
                continue
            
            req = requests[idx]
            
            if semaphore is not None:
                async with semaphore:
                    result = await execute_request(client, req, think_time_ms)
            else:
                result = await execute_request(client, req, think_time_ms)
            
            # Use put_nowait when possible for lower latency
            if not queue_full():
                queue_put_nowait(result)
            else:
                await queue_put(result)
            
            idx += 1
            if idx >= num_requests:
                idx = 0
                cycle += 1
                if iterations > 0 and cycle >= iterations:
                    break
    except asyncio.CancelledError:
        pass
    finally:
        await queue_put(None)


async def create_client(
    http2: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncClient:
    """Create shared async HTTP client.
    
    Uses high connection limits for throughput. Single client per run.
    
    Args:
        http2: Enable HTTP/2 protocol (recommended for multiplexing)
        timeout: Request timeout in seconds
        limits: Custom connection limits (uses high defaults if not specified)
    
    Returns:
        Configured AsyncClient ready for use as async context manager
    """
    limits = limits or httpx.Limits(
        max_connections=DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections=DEFAULT_MAX_KEEPALIVE,
        keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY,
    )
    return httpx.AsyncClient(
        http2=http2,
        timeout=timeout,
        limits=limits,
    )


async def collect_results(
    result_queue: asyncio.Queue[RequestResult | None],
    num_workers: int,
) -> AsyncIterator[RequestResult]:
    """Consume queue until all workers send sentinel.
    
    Args:
        result_queue: Queue to consume from
        num_workers: Expected number of sentinel (None) values
    
    Yields:
        RequestResult objects as they arrive
    """
    done = 0
    while done < num_workers:
        item = await result_queue.get()
        if item is None:
            done += 1
            continue
        yield item
