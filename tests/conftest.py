"""Pytest fixtures for deli tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path_config_constant() -> Path:
    """Write a minimal valid load config (constant) to a temp file."""
    content = """
users: 10
ramp_up_seconds: 5
duration_seconds: 60
scenario: constant
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def tmp_path_config_spike() -> Path:
    """Write a spike scenario config to a temp file."""
    content = """
users: 20
ramp_up_seconds: 10
duration_seconds: 120
scenario: spike
spike_users: 30
spike_duration_seconds: 15
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def tmp_path_stress_config() -> Path:
    """Write a minimal stress config to a temp file."""
    content = """
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
initial_users: 5
step_users: 5
step_interval_seconds: 30
max_users: 100
scenario: linear_overload
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(content)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def sample_postman_collection_path(tmp_path: Path) -> Path:
    """Minimal Postman v2.1 collection JSON file."""
    content = """{
  "info": { "name": "Test", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json" },
  "item": [
    {
      "name": "Get",
      "request": {
        "method": "GET",
        "url": "https://httpbin.org/get"
      }
    }
  ]
}
"""
    p = tmp_path / "collection.json"
    p.write_text(content, encoding="utf-8")
    return p
