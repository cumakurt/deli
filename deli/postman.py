"""Postman Collection v2.1 parser with folder structure and environment variable resolution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import orjson

from .exceptions import DeliCollectionError
from .logging_config import get_logger
from .models import ParsedRequest

logger = get_logger("postman")

# Postman v2.1 variable syntax: {{variableName}}
VAR_PATTERN = re.compile(r"\{\{([^}]+)\}\}")
DEFAULT_POSTMAN_HEADERS = {
    "User-Agent": "PostmanRuntime/7.43.0",
    "Accept": "*/*",
}


def load_collection(
    path: str | Path,
    env_override: dict[str, str] | None = None,
    environment_path: str | Path | None = None,
    environment_values: dict[str, str] | None = None,
) -> list[ParsedRequest]:
    """
    Load Postman Collection v2.1 JSON and return flat list of ParsedRequest
    preserving folder path for each item. Environment values are resolved from
    an explicit Postman environment JSON file, an optional auto-discovered
    sibling env file, and finally env_override.
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
    if environment_values is not None:
        env.update(environment_values)
    elif environment_path is not None:
        env.update(load_environment(environment_path, required=True))
    else:
        # Backward-compatible auto-discovery for collection-name_env.json.
        env_path = p.parent / (p.stem + "_env.json")
        if env_path.exists():
            try:
                env.update(load_environment(env_path, required=False))
            except DeliCollectionError:
                logger.debug("Could not load env file %s, using overrides only", env_path)
    # Runtime override wins
    if env_override:
        env.update(env_override)

    requests: list[ParsedRequest] = []
    _walk_items(items, "", env, requests)
    return requests


def load_environment(path: str | Path, required: bool = True) -> dict[str, str]:
    """Load a Postman environment JSON export into a variable dictionary."""
    p = Path(path)
    if not p.exists():
        if required:
            raise DeliCollectionError(f"Environment file not found: {path}")
        return {}

    try:
        raw = orjson.loads(p.read_bytes())
    except orjson.JSONDecodeError as e:
        if required:
            raise DeliCollectionError(f"Invalid JSON in environment: {e}") from e
        raise DeliCollectionError(f"Invalid JSON in environment: {e}") from e
    except OSError as e:
        if required:
            raise DeliCollectionError(f"Cannot read environment file: {e}") from e
        raise DeliCollectionError(f"Cannot read environment file: {e}") from e

    if not isinstance(raw, dict):
        if required:
            raise DeliCollectionError("Environment must be a JSON object")
        return {}

    values = raw.get("values")
    if not isinstance(values, list):
        if required:
            raise DeliCollectionError("Environment must contain a values list")
        return {}

    env: dict[str, str] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key or item.get("enabled") is False:
            continue
        env[str(key)] = str(item.get("value", ""))
    return env


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
        raw = url_raw.get("raw")
        if isinstance(raw, str) and raw.strip():
            url = resolve_vars(raw, env)
        else:
            url = _build_url_from_object(url_raw, env)
    else:
        return None

    headers = _parse_headers(req.get("header") or [], env)
    _apply_default_postman_headers(headers)
    headers.update(_parse_auth_headers(req.get("auth"), env, headers))
    method = (req.get("method") or "GET").strip().upper()
    body = _parse_body(req.get("body"), env, headers)

    return ParsedRequest(
        name=item.get("name") or "Unnamed",
        method=method,
        url=url,
        headers=headers,
        body=body,
        folder_path=folder_path,
    )


def _build_url_from_object(url_raw: dict[str, Any], env: dict[str, str]) -> str:
    """Build URL from a Postman URL object."""
    protocol = url_raw.get("protocol") or "https"
    host = resolve_vars(_url_host(url_raw), env)
    path = "/".join(p for p in (url_raw.get("path") or []) if isinstance(p, str))
    path = "/" + path if path and not path.startswith("/") else path or ""

    if host.startswith(("http://", "https://")):
        raw_url = f"{host}{path}"
    else:
        # Postman URL object
        raw_url = f"{protocol}://{host}{path}"

    query = url_raw.get("query") or []
    if query:
        qs = "&".join(
            f"{q.get('key', '')}={q.get('value', '')}" for q in query if isinstance(q, dict)
        )
        raw_url = f"{raw_url}?{qs}" if qs else raw_url
    return resolve_vars(raw_url, env)


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


def _apply_default_postman_headers(headers: dict[str, str]) -> None:
    for name, value in DEFAULT_POSTMAN_HEADERS.items():
        if not _has_header(headers, name):
            headers[name] = value


def _parse_auth_headers(
    auth: Any,
    env: dict[str, str],
    existing_headers: dict[str, str],
) -> dict[str, str]:
    if not isinstance(auth, dict):
        return {}
    if _has_header(existing_headers, "authorization"):
        return {}
    if auth.get("type") != "bearer":
        return {}

    token = _postman_keyed_value(auth.get("bearer"), "token")
    if token is None:
        return {}
    token = resolve_vars(token, env).strip()
    if not token:
        return {}
    return {"Authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}"}


def _postman_keyed_value(items: Any, key: str) -> str | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("key") == key:
            value = item.get("value")
            return "" if value is None else str(value)
    return None


def _has_header(headers: dict[str, str], name: str) -> bool:
    return any(k.lower() == name.lower() for k in headers)


def _set_default_header(headers: dict[str, str] | None, name: str, value: str) -> None:
    if headers is not None and not _has_header(headers, name):
        headers[name] = value


def _parse_body(
    body: Any,
    env: dict[str, str],
    headers: dict[str, str] | None = None,
) -> str | None:
    if body is None:
        return None
    if isinstance(body, dict):
        mode = body.get("mode")
        if mode == "raw":
            raw = body.get("raw")
            if raw is not None:
                return resolve_vars(str(raw), env)
        if mode == "urlencoded":
            encoded = _parse_urlencoded_body(body.get("urlencoded"), env)
            if encoded:
                _set_default_header(headers, "Content-Type", "application/x-www-form-urlencoded")
            return encoded
        if mode == "formdata":
            return _parse_formdata_body(body.get("formdata"), env, headers)
        # formdata, urlencoded: could be implemented similarly
    return None


def _parse_urlencoded_body(items: Any, env: dict[str, str]) -> str | None:
    pairs = _text_body_pairs(items, env)
    return urlencode(pairs) if pairs else None


def _parse_formdata_body(
    items: Any,
    env: dict[str, str],
    headers: dict[str, str] | None,
) -> str | None:
    pairs = _text_body_pairs(items, env)
    if not pairs:
        return None

    boundary = "----deli-postman-boundary"
    lines: list[str] = []
    for key, value in pairs:
        lines.extend(
            [
                f"--{boundary}",
                f'Content-Disposition: form-data; name="{key}"',
                "",
                value,
            ]
        )
    lines.append(f"--{boundary}--")
    lines.append("")
    _set_default_header(headers, "Content-Type", f"multipart/form-data; boundary={boundary}")
    return "\r\n".join(lines)


def _text_body_pairs(items: Any, env: dict[str, str]) -> list[tuple[str, str]]:
    if not isinstance(items, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        key = item.get("key")
        if not key:
            continue
        if item.get("type") == "file":
            continue
        value = item.get("value") or ""
        pairs.append((str(key), resolve_vars(str(value), env)))
    return pairs


def resolve_vars(text: str, env: dict[str, str]) -> str:
    """Replace {{variableName}} with values from env. Env can be augmented at runtime."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return env.get(key, match.group(0))

    return VAR_PATTERN.sub(repl, text)


def unresolved_variables_in_requests(requests: list[ParsedRequest]) -> dict[str, list[str]]:
    """Return unresolved Postman variables grouped by request name."""
    unresolved: dict[str, list[str]] = {}
    for req in requests:
        values = [req.url, *(req.headers.values())]
        if req.body:
            values.append(req.body)
        names: set[str] = set()
        for value in values:
            names.update(match.group(1).strip() for match in VAR_PATTERN.finditer(value))
        if names:
            unresolved[req.name] = sorted(names)
    return unresolved


def set_env_from_dict(env: dict[str, str], values: dict[str, str]) -> None:
    """Merge runtime environment values into env (in-place)."""
    env.update(values)
