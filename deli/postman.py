"""Postman Collection v2.1 parser with folder structure and environment variable resolution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import orjson

from .exceptions import DeliCollectionError
from .logging_config import get_logger
from .models import ParsedRequest

logger = get_logger("postman")

# Postman v2.1 variable syntax: {{variableName}}
VAR_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def load_collection(
    path: str | Path,
    env_override: dict[str, str] | None = None,
) -> list[ParsedRequest]:
    """
    Load Postman Collection v2.1 JSON and return flat list of ParsedRequest
    preserving folder path for each item. env_override is merged at runtime.
    Raises DeliCollectionError on invalid collection or file error.
    """
    p = Path(path)
    if not p.exists():
        raise DeliCollectionError(f"Collection file not found: {path}")

    try:
        raw = orjson.loads(p.read_bytes())
    except orjson.JSONDecodeError as e:
        logger.exception("Invalid JSON in collection file")
        raise DeliCollectionError(f"Invalid JSON in collection: {e}") from e
    except OSError as e:
        logger.exception("Failed to read collection file")
        raise DeliCollectionError(f"Cannot read collection file: {e}") from e

    if not isinstance(raw, dict):
        raise DeliCollectionError("Collection must be a JSON object")

    info = raw.get("info", {}) or {}
    if isinstance(info.get("schema"), str) and "2.1" not in info["schema"]:
        pass  # Still try to parse; v2.0 is similar

    items = raw.get("item") or []
    env: dict[str, str] = {}
    # Load env from optional _env.json (Postman export format)
    env_path = p.parent / (p.stem + "_env.json")
    if env_path.exists():
        try:
            env_raw = orjson.loads(env_path.read_bytes())
            if isinstance(env_raw, dict) and "values" in env_raw:
                for v in env_raw.get("values", []):
                    if isinstance(v, dict) and "key" in v:
                        env[v["key"]] = str(v.get("value", ""))
        except (orjson.JSONDecodeError, OSError):
            logger.debug("Could not load env file %s, using overrides only", env_path)
    # Runtime override wins
    if env_override:
        env.update(env_override)

    requests: list[ParsedRequest] = []
    _walk_items(items, "", env, requests)
    return requests


def _walk_items(
    items: list[Any],
    folder_path: str,
    env: dict[str, str],
    out: list[ParsedRequest],
) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "Unnamed"
        if "request" in item:
            req = _parse_request_item(item, folder_path, env)
            if req:
                out.append(req)
        if "item" in item:
            sub = item.get("item") or []
            new_path = f"{folder_path}/{name}".strip("/") if folder_path else name
            _walk_items(sub, new_path, env, out)


def _parse_request_item(
    item: dict[str, Any],
    folder_path: str,
    env: dict[str, str],
) -> ParsedRequest | None:
    req = item.get("request")
    if not isinstance(req, dict):
        return None

    url_raw = req.get("url")
    if isinstance(url_raw, str):
        url = resolve_vars(url_raw, env)
    elif isinstance(url_raw, dict):
        # Postman URL object
        protocol = url_raw.get("protocol") or "https"
        host = _url_host(url_raw)
        path = "/".join(
            p for p in (url_raw.get("path") or []) if isinstance(p, str)
        )
        path = "/" + path if path and not path.startswith("/") else path or ""
        raw_url = f"{protocol}://{host}{path}"
        query = url_raw.get("query") or []
        if query:
            qs = "&".join(
                f"{q.get('key', '')}={q.get('value', '')}"
                for q in query
                if isinstance(q, dict)
            )
            raw_url = f"{raw_url}?{qs}" if qs else raw_url
        url = resolve_vars(raw_url, env)
    else:
        return None

    method = (req.get("method") or "GET").strip().upper()
    headers = _parse_headers(req.get("header") or [], env)
    body = _parse_body(req.get("body"), env)

    return ParsedRequest(
        name=item.get("name") or "Unnamed",
        method=method,
        url=url,
        headers=headers,
        body=body,
        folder_path=folder_path,
    )


def _url_host(url_obj: dict[str, Any]) -> str:
    host = url_obj.get("host") or []
    if isinstance(host, str):
        return host
    return ".".join(h for h in host if isinstance(h, str))


def _parse_headers(headers: list[Any], env: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for h in headers:
        if not isinstance(h, dict):
            continue
        key = h.get("key")
        if not key or h.get("disabled"):
            continue
        value = h.get("value") or ""
        result[key.strip()] = resolve_vars(str(value), env)
    return result


def _parse_body(body: Any, env: dict[str, str]) -> str | None:
    if body is None:
        return None
    if isinstance(body, dict):
        mode = body.get("mode")
        if mode == "raw":
            raw = body.get("raw")
            if raw is not None:
                return resolve_vars(str(raw), env)
        # formdata, urlencoded: could be implemented similarly
    return None


def resolve_vars(text: str, env: dict[str, str]) -> str:
    """Replace {{variableName}} with values from env. Env can be augmented at runtime."""
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return env.get(key, match.group(0))
    return VAR_PATTERN.sub(repl, text)


def set_env_from_dict(env: dict[str, str], values: dict[str, str]) -> None:
    """Merge runtime environment values into env (in-place)."""
    env.update(values)
