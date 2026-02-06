"""Unit tests for Postman collection parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.exceptions import DeliCollectionError
from deli.postman import (
    load_collection,
    resolve_vars,
    set_env_from_dict,
    _url_host,
    _parse_headers,
    _parse_body,
)


def test_resolve_vars_empty_env() -> None:
    assert resolve_vars("https://{{host}}/path", {}) == "https://{{host}}/path"
    assert resolve_vars("no vars", {}) == "no vars"


def test_resolve_vars_with_env() -> None:
    env = {"host": "api.example.com", "token": "secret123"}
    assert resolve_vars("https://{{host}}/api", env) == "https://api.example.com/api"
    assert resolve_vars("Bearer {{token}}", env) == "Bearer secret123"


def test_load_collection_file_not_found() -> None:
    with pytest.raises(DeliCollectionError, match="Collection file not found"):
        load_collection("/nonexistent/collection.json")


def test_load_collection_valid(sample_postman_collection_path: Path) -> None:
    requests = load_collection(sample_postman_collection_path)
    assert len(requests) == 1
    assert requests[0].name == "Get"
    assert requests[0].method == "GET"
    assert "httpbin.org" in requests[0].url


def test_load_collection_with_env_override(sample_postman_collection_path: Path) -> None:
    # Collection has https://httpbin.org/get; override with env
    requests = load_collection(
        sample_postman_collection_path,
        env_override={"base": "https://api.test.com"},
    )
    assert len(requests) == 1
    # URL in collection is literal https://httpbin.org/get so no {{base}} to replace
    assert requests[0].url == "https://httpbin.org/get"


def test_load_collection_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {")
    with pytest.raises(DeliCollectionError, match="Invalid JSON"):
        load_collection(bad)


def test_load_collection_not_object(tmp_path: Path) -> None:
    bad = tmp_path / "array.json"
    bad.write_text("[]")
    with pytest.raises(DeliCollectionError, match="Collection must be a JSON object"):
        load_collection(bad)


def test_url_host_string() -> None:
    assert _url_host({"host": "api.example.com"}) == "api.example.com"


def test_url_host_array() -> None:
    assert _url_host({"host": ["api", "example", "com"]}) == "api.example.com"


def test_parse_headers_empty() -> None:
    assert _parse_headers([], {}) == {}


def test_parse_headers_with_vars() -> None:
    headers = [{"key": "Authorization", "value": "Bearer {{token}}", "disabled": False}]
    assert _parse_headers(headers, {"token": "secret"}) == {"Authorization": "Bearer secret"}


def test_parse_headers_disabled_skipped() -> None:
    headers = [{"key": "X-Skip", "value": "v", "disabled": True}]
    assert _parse_headers(headers, {}) == {}


def test_parse_body_none() -> None:
    assert _parse_body(None, {}) is None


def test_parse_body_raw_with_vars() -> None:
    body = {"mode": "raw", "raw": "{\"user\": \"{{name}}\"}"}
    assert _parse_body(body, {"name": "alice"}) == "{\"user\": \"alice\"}"


def test_parse_body_non_raw() -> None:
    assert _parse_body({"mode": "urlencoded"}, {}) is None


def test_set_env_from_dict() -> None:
    env = {"a": "1"}
    set_env_from_dict(env, {"b": "2", "a": "overridden"})
    assert env == {"a": "overridden", "b": "2"}


def test_load_collection_url_object_and_raw_body(tmp_path: Path) -> None:
    """Collection with Postman URL object and raw JSON body."""
    content = """{
      "info": { "name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json" },
      "item": [{
        "name": "Post JSON",
        "request": {
          "method": "POST",
          "url": {
            "protocol": "https",
            "host": ["httpbin", "org"],
            "path": ["post"]
          },
          "header": [{"key": "Content-Type", "value": "application/json"}],
          "body": { "mode": "raw", "raw": "{\\"key\\": \\"{{val}}\\"}" }
        }
      }]
    }"""
    (tmp_path / "col.json").write_text(content)
    requests = load_collection(tmp_path / "col.json", env_override={"val": "hello"})
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url == "https://httpbin.org/post"
    assert "hello" in (requests[0].body or "")
    assert requests[0].headers.get("Content-Type") == "application/json"
