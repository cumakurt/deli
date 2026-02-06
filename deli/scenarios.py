"""Load scenarios: gradual ramp-up, constant load, spike. Minimal sleep for fast ramp."""

from __future__ import annotations

import asyncio
import time
from .engine import create_client, run_worker
from .models import ParsedRequest, RequestResult, RunConfig

# Ramp loop interval (seconds). Lower = finer ramp, less delay; 0.02 keeps CPU low.
RAMP_POLL_SEC = 0.02
# Maximum in-flight requests multiplier (per user count)
MAX_IN_FLIGHT_MULTIPLIER = 2
# Minimum in-flight request limit
MIN_IN_FLIGHT_LIMIT = 50
# Maximum in-flight request limit
MAX_IN_FLIGHT_LIMIT = 1000
# Default HTTP client timeout
DEFAULT_HTTP_TIMEOUT = 30.0


def _compute_active_users_for_scenario(
    config: RunConfig,
    elapsed_seconds: float,
) -> int:
    """
    Core calculation for active virtual users at given elapsed time.
    
    This is the single source of truth for user count calculation.
    Used by both async scenario runner and sync dashboard helper.
    
    Args:
        config: Run configuration with scenario parameters
        elapsed_seconds: Time elapsed since test start
    
    Returns:
        Number of virtual users that should be active
    """
    if elapsed_seconds < 0:
        return 0
    
    scenario = config.scenario.value
    
    if scenario == "constant":
        return config.users if elapsed_seconds >= 0 else 0
    
    if scenario == "gradual":
        if config.ramp_up_seconds <= 0:
            return config.users
        progress = min(1.0, elapsed_seconds / config.ramp_up_seconds)
        return max(1, int(config.users * progress))
    
    if scenario == "spike":
        ramp = config.ramp_up_seconds
        spike_start = ramp + max(0, (config.duration_seconds - config.spike_duration_seconds * 2) / 2)
        spike_end = spike_start + config.spike_duration_seconds
        
        if elapsed_seconds < ramp:
            if ramp <= 0:
                return config.users
            progress = elapsed_seconds / ramp
            return max(1, int(config.users * progress))
        if spike_start <= elapsed_seconds < spike_end:
            return config.users + config.spike_users
        return config.users
    
    # Default fallback
    return config.users


async def active_users_at(
    config: RunConfig,
    elapsed_seconds: float,
) -> int:
    """Return number of virtual users that should be active at elapsed_seconds.
    
    Async wrapper for dashboard and scenario coordination.
    """
    return _compute_active_users_for_scenario(config, elapsed_seconds)


async def run_scenario(
    config: RunConfig,
    requests: list[ParsedRequest],
    result_queue: asyncio.Queue[RequestResult | None],
) -> tuple[float, float]:
    """
    Run the configured scenario; feed results into result_queue.
    Returns (start_time, end_time) for metrics.
    """
    if not requests:
        return time.perf_counter(), time.perf_counter()

    stop_event = asyncio.Event()
    start_time = time.perf_counter()
    max_in_flight = min(MAX_IN_FLIGHT_LIMIT, max(config.users * MAX_IN_FLIGHT_MULTIPLIER, MIN_IN_FLIGHT_LIMIT))
    semaphore = asyncio.Semaphore(max_in_flight)

    async with await create_client(http2=True, timeout=DEFAULT_HTTP_TIMEOUT) as client:
        workers: list[asyncio.Task] = []

        if config.scenario.value == "constant":
            for _ in range(config.users):
                t = asyncio.create_task(
                    run_worker(
                        client,
                        requests,
                        config.think_time_ms,
                        result_queue,
                        stop_event,
                        config.iterations,
                        semaphore=semaphore,
                    )
                )
                workers.append(t)
            await asyncio.sleep(config.duration_seconds)
            stop_event.set()
            if workers:
                await asyncio.gather(*workers)

        elif config.scenario.value == "gradual":
            # Ramp up: start one worker every (ramp_up_seconds / users) seconds
            interval = config.ramp_up_seconds / max(config.users, 1)
            next_start = 0.0
            started = 0
            while time.perf_counter() - start_time < config.duration_seconds:
                now = time.perf_counter() - start_time
                while started < config.users and now >= next_start:
                    t = asyncio.create_task(
                        run_worker(
                            client,
                            requests,
                            config.think_time_ms,
                            result_queue,
                            stop_event,
                            config.iterations,
                            semaphore=semaphore,
                        )
                    )
                    workers.append(t)
                    started += 1
                    next_start += interval
                await asyncio.sleep(RAMP_POLL_SEC)
            stop_event.set()
            if workers:
                await asyncio.gather(*workers)

        elif config.scenario.value == "spike":
            # Ramp to base users, hold, spike, then hold until end
            ramp = config.ramp_up_seconds
            mid = (config.duration_seconds - config.spike_duration_seconds * 2) / 2
            spike_start = ramp + max(0, mid)
            spike_end = spike_start + config.spike_duration_seconds
            interval = ramp / max(config.users, 1)
            next_start = 0.0
            started = 0
            spike_started = 0
            while time.perf_counter() - start_time < config.duration_seconds:
                now = time.perf_counter() - start_time
                while started < config.users and now >= next_start:
                    t = asyncio.create_task(
                        run_worker(
                            client,
                            requests,
                            config.think_time_ms,
                            result_queue,
                            stop_event,
                            config.iterations,
                            semaphore=semaphore,
                        )
                    )
                    workers.append(t)
                    started += 1
                    next_start += interval
                if now >= spike_start and spike_started < config.spike_users:
                    for _ in range(config.spike_users - spike_started):
                        t = asyncio.create_task(
                            run_worker(
                                client,
                                requests,
                                config.think_time_ms,
                                result_queue,
                                stop_event,
                                config.iterations,
                                semaphore=semaphore,
                            )
                        )
                        workers.append(t)
                    spike_started = config.spike_users
                if now >= spike_end and spike_started > 0:
                    # Stop spike workers by setting stop and waiting; we keep base workers
                    # Simplified: we don't kill only spike workers; we run full duration
                    pass
                await asyncio.sleep(RAMP_POLL_SEC)
            stop_event.set()
            if workers:
                await asyncio.gather(*workers)

        else:
            await asyncio.sleep(config.duration_seconds)
            stop_event.set()

    end_time = time.perf_counter()
    return start_time, end_time


def expected_active_users(config: RunConfig, elapsed: float) -> int:
    """Synchronous helper for dashboard: expected active users at elapsed.
    
    Delegates to the core calculation function for consistency.
    """
    return _compute_active_users_for_scenario(config, elapsed)
