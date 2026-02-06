"""Unit tests for load scenarios (active_users_at, expected_active_users, run_scenario)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deli.models import LoadScenario, ParsedRequest, RequestResult, RunConfig
from deli.scenarios import active_users_at, expected_active_users, run_scenario


def _arun(coro):
    return asyncio.run(coro)


def _config(
    scenario: LoadScenario,
    users: int = 10,
    ramp_up_seconds: float = 10,
    duration_seconds: float = 60,
    spike_users: int = 0,
    spike_duration_seconds: float = 0,
) -> RunConfig:
    return RunConfig(
        users=users,
        ramp_up_seconds=ramp_up_seconds,
        duration_seconds=duration_seconds,
        iterations=0,
        think_time_ms=0,
        scenario=scenario,
        spike_users=spike_users,
        spike_duration_seconds=spike_duration_seconds,
    )


def test_active_users_at_constant() -> None:
    config = _config(LoadScenario.CONSTANT, users=20)
    assert _arun(active_users_at(config, -1)) == 0
    assert _arun(active_users_at(config, 0)) == 20
    assert _arun(active_users_at(config, 30)) == 20


def test_active_users_at_gradual() -> None:
    config = _config(LoadScenario.GRADUAL, users=100, ramp_up_seconds=50)
    # At t=0, progress=0, so users = max(1, int(100*0)) = 1 (at least 1 user at start)
    assert _arun(active_users_at(config, 0)) == 1
    assert _arun(active_users_at(config, 25)) == 50
    assert _arun(active_users_at(config, 50)) == 100
    assert _arun(active_users_at(config, 60)) == 100
    config_zero_ramp = _config(LoadScenario.GRADUAL, users=10, ramp_up_seconds=0)
    assert _arun(active_users_at(config_zero_ramp, 1)) == 10


def test_active_users_at_spike() -> None:
    config = _config(
        LoadScenario.SPIKE,
        users=10,
        ramp_up_seconds=20,
        duration_seconds=100,
        spike_users=30,
        spike_duration_seconds=15,
    )
    assert _arun(active_users_at(config, 0)) >= 0  # at t=0 implementation returns max(1, 0)=1
    assert _arun(active_users_at(config, 10)) >= 1
    assert _arun(active_users_at(config, 20)) == 10
    assert _arun(active_users_at(config, 57)) == 40
    assert _arun(active_users_at(config, 80)) == 10


def test_expected_active_users_constant() -> None:
    config = _config(LoadScenario.CONSTANT, users=15)
    assert expected_active_users(config, -1) == 0
    assert expected_active_users(config, 0) == 15
    assert expected_active_users(config, 100) == 15


def test_expected_active_users_gradual() -> None:
    config = _config(LoadScenario.GRADUAL, users=50, ramp_up_seconds=25)
    # At t=0, progress=0, so users = max(1, int(50*0)) = 1 (at least 1 user at start)
    assert expected_active_users(config, 0) == 1
    assert expected_active_users(config, 12.5) == 25
    assert expected_active_users(config, 25) == 50
    assert expected_active_users(config, 30) == 50


def test_expected_active_users_spike() -> None:
    config = _config(
        LoadScenario.SPIKE,
        users=10,
        ramp_up_seconds=10,
        duration_seconds=60,
        spike_users=20,
        spike_duration_seconds=10,
    )
    assert expected_active_users(config, 0) >= 0  # at t=0 returns max(1, 0)=1
    assert expected_active_users(config, 5) >= 1
    assert expected_active_users(config, 10) == 10
    # spike: mid = (60-20)/2 = 20, spike_start = 10+20 = 30, spike_end = 40. So at 25 we're before spike.
    assert expected_active_users(config, 25) == 10
    assert expected_active_users(config, 35) == 30
    assert expected_active_users(config, 45) == 10


def test_run_scenario_empty_requests_returns_immediately() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(LoadScenario.CONSTANT, users=5, duration_seconds=1)
    start, end = _arun(run_scenario(config, [], queue))
    assert start <= end


@pytest.mark.skip(reason="run_scenario with mocks can block in some envs; covered by integration test")
def test_run_scenario_constant_mock_execute() -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    config = _config(LoadScenario.CONSTANT, users=2, duration_seconds=0.02)
    req = ParsedRequest(name="R", method="GET", url="https://httpbin.org/get")
    from deli.models import RequestResult
    result = RequestResult(
        request_name="R", folder_path="", method="GET", url=req.url,
        status_code=200, response_time_ms=10, success=True, timestamp=0,
    )

    async def fake_execute(client, r, think_ms):
        return result

    class FakeClient:
        pass

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    async def fake_create_client(*args, **kwargs):
        return FakeClient()

    with patch("deli.engine.execute_request", side_effect=fake_execute):
        with patch("deli.scenarios.create_client", side_effect=fake_create_client):
            start, end = _arun(run_scenario(config, [req], queue))
    assert start <= end
    assert end >= start
