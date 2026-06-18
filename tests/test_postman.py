"""Unit tests for Postman collection parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from deli.exceptions import DeliCollectionError
from deli.postman import (
    _build_url_from_object,
    _parse_body,
    _parse_headers,
    _url_host,
    apply_post_response_assignments,
    build_runtime_env,
    load_collection,
    load_environment,
    order_requests_for_runtime_dependencies,
    produced_runtime_variables,
    render_runtime_request,
    resolve_vars,
    set_env_from_dict,
    unresolved_variables_in_requests,
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
    assert requests[0].headers["User-Agent"].startswith("PostmanRuntime/")
    assert requests[0].headers["Accept"] == "*/*"


def test_load_collection_with_env_override(sample_postman_collection_path: Path) -> None:
    # Collection has https://httpbin.org/get; override with env
    requests = load_collection(
        sample_postman_collection_path,
        env_override={"base": "https://api.test.com"},
    )
    assert len(requests) == 1
    # URL in collection is literal https://httpbin.org/get so no {{base}} to replace
    assert requests[0].url == "https://httpbin.org/get"


def test_load_collection_with_environment_file(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{
            "name": "Env Request",
            "request": {
              "method": "POST",
              "url": "{{base_url}}/users/{{user_id}}",
              "header": [{"key": "Authorization", "value": "Bearer {{token}}"}],
              "body": {"mode": "raw", "raw": "{\\"name\\": \\"{{name}}\\"}"}
            }
          }]
        }""",
        encoding="utf-8",
    )
    environment = tmp_path / "environment.json"
    environment.write_text(
        """{
          "name": "Test Env",
          "values": [
            {"key": "base_url", "value": "https://api.example.com", "enabled": true},
            {"key": "user_id", "value": "42", "enabled": true},
            {"key": "token", "value": "secret", "enabled": true},
            {"key": "name", "value": "alice", "enabled": true},
            {"key": "disabled", "value": "skip", "enabled": false}
          ]
        }""",
        encoding="utf-8",
    )

    requests = load_collection(collection, environment_path=environment)

    assert len(requests) == 1
    assert requests[0].url == "https://api.example.com/users/42"
    assert requests[0].headers["Authorization"] == "Bearer secret"
    assert requests[0].body == '{"name": "alice"}'


def test_load_collection_env_override_wins_over_environment_file(tmp_path: Path) -> None:
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
        """{"values": [{"key": "base_url", "value": "https://file.example.com", "enabled": true}]}""",
        encoding="utf-8",
    )

    requests = load_collection(
        collection,
        environment_path=environment,
        env_override={"base_url": "https://override.example.com"},
    )

    assert requests[0].url == "https://override.example.com/ping"


def test_load_environment_file_not_found() -> None:
    with pytest.raises(DeliCollectionError, match="Environment file not found"):
        load_environment("/nonexistent/environment.json")


def test_unresolved_variables_in_requests(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{
            "name": "Needs Env",
            "request": {
              "method": "GET",
              "url": "{{base_url}}/ping",
              "header": [{"key": "Authorization", "value": "Bearer {{token}}"}]
            }
          }]
        }""",
        encoding="utf-8",
    )
    requests = load_collection(
        collection,
        env_override={"base_url": "https://api.example.com"},
    )

    assert unresolved_variables_in_requests(requests) == {"Needs Env": ["token"]}


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


def test_build_url_from_object_host_variable_with_scheme() -> None:
    url = _build_url_from_object(
        {"protocol": "https", "host": ["{{base_url}}"], "path": ["api"]},
        {"base_url": "https://api.example.com"},
    )
    assert url == "https://api.example.com/api"


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
    body = {"mode": "raw", "raw": '{"user": "{{name}}"}'}
    assert _parse_body(body, {"name": "alice"}) == '{"user": "alice"}'


def test_parse_body_non_raw() -> None:
    assert _parse_body({"mode": "graphql"}, {}) is None


def test_parse_body_urlencoded_sets_content_type() -> None:
    headers: dict[str, str] = {}
    body = {
        "mode": "urlencoded",
        "urlencoded": [
            {"key": "username", "value": "{{user}}", "type": "text"},
            {"key": "password", "value": "secret value", "type": "text"},
        ],
    }
    assert _parse_body(body, {"user": "alice@example.com"}, headers) == (
        "username=alice%40example.com&password=secret+value"
    )
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_load_collection_bearer_auth_from_postman_auth(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{
            "name": "Authed",
            "request": {
              "method": "GET",
              "url": "https://api.example.com/ping",
              "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]
              }
            }
          }]
        }""",
        encoding="utf-8",
    )
    requests = load_collection(collection, env_override={"token": "abc"})
    assert requests[0].headers["Authorization"] == "Bearer abc"


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


def test_load_collection_parses_postman_environment_set_script(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [{
            "name": "Get Token",
            "event": [{
              "listen": "test",
              "script": {"exec": [
                "var jsonData = pm.response.json();",
                "pm.environment.set(\\"access_token\\", jsonData.access_token);"
              ]}
            }],
            "request": {"method": "POST", "url": "https://api.example.com/token"}
          }]
        }""",
        encoding="utf-8",
    )

    requests = load_collection(collection)

    assert len(requests[0].post_response_assignments) == 1
    assert requests[0].post_response_assignments[0].variable == "access_token"
    assert requests[0].post_response_assignments[0].expression == "jsonData.access_token"


def test_runtime_assignment_updates_rendered_request(tmp_path: Path) -> None:
    collection = tmp_path / "collection.json"
    collection.write_text(
        """{
          "info": {"name": "T", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
          "item": [
            {
              "name": "Use Token",
              "request": {
                "method": "GET",
                "url": "https://api.example.com/users/me",
                "header": [{"key": "Authorization", "value": "Bearer {{access_token}}"}]
              }
            },
            {
              "name": "Get Token",
              "event": [{
                "listen": "test",
                "script": {"exec": ["pm.environment.set(\\"access_token\\", jsonData.access_token);"]}
              }],
              "request": {"method": "POST", "url": "https://api.example.com/token"}
            }
          ]
        }""",
        encoding="utf-8",
    )

    requests = order_requests_for_runtime_dependencies(load_collection(collection))
    runtime_env = build_runtime_env(requests)
    assert runtime_env is not None
    assert [r.name for r in requests] == ["Get Token", "Use Token"]

    apply_post_response_assignments(
        requests[0],
        '{"access_token":"fresh-token"}',
        runtime_env,
    )
    _, headers, _ = render_runtime_request(requests[1], runtime_env)

    assert headers["Authorization"] == "Bearer fresh-token"
    assert produced_runtime_variables(requests) == {"access_token"}
    assert unresolved_variables_in_requests(
        requests,
        ignore_variables=produced_runtime_variables(requests),
    ) == {}
