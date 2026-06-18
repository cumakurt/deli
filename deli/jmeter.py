"""Apache JMeter JMX parser for HTTP sampler execution."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote_plus, urlencode, urlparse, urlunparse

from .exceptions import DeliCollectionError
from .models import LoadScenario, ParsedRequest, RunConfig

JMETER_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")
HTTP_SAMPLER_TAG = "HTTPSamplerProxy"
HEADER_MANAGER_TAG = "HeaderManager"
CONFIG_TEST_ELEMENT_TAG = "ConfigTestElement"
ARGUMENTS_TAG = "Arguments"
HASH_TREE_TAG = "hashTree"
DEFAULT_JMETER_HEADERS = {
    "User-Agent": "Apache-HttpClient/4.5.14 (Java/17)",
}
DEFAULT_JMETER_DURATION_SECONDS = 60.0


def load_jmx(
    path: str | Path,
    env_override: dict[str, str] | None = None,
) -> list[ParsedRequest]:
    """Load a JMeter JMX file and return HTTP samplers as ParsedRequest objects."""
    p = Path(path)
    if not p.exists():
        raise DeliCollectionError(f"JMeter JMX file not found: {path}")

    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        raise DeliCollectionError(f"Invalid JMeter JMX XML: {e}") from e
    except OSError as e:
        raise DeliCollectionError(f"Cannot read JMeter JMX file: {e}") from e

    env = _collect_user_defined_variables(root)
    if env_override:
        env.update(env_override)

    requests: list[ParsedRequest] = []
    for sampler, sampler_tree in _iter_hash_tree_elements(root, HTTP_SAMPLER_TAG):
        req = _parse_http_sampler(sampler, sampler_tree, root, env)
        if req is not None:
            requests.append(req)
    return requests


def load_jmx_run_config(
    path: str | Path,
    env_override: dict[str, str] | None = None,
) -> RunConfig:
    """Load basic ThreadGroup settings from a JMeter JMX file."""
    p = Path(path)
    if not p.exists():
        raise DeliCollectionError(f"JMeter JMX file not found: {path}")

    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        raise DeliCollectionError(f"Invalid JMeter JMX XML: {e}") from e
    except OSError as e:
        raise DeliCollectionError(f"Cannot read JMeter JMX file: {e}") from e

    env = _collect_user_defined_variables(root)
    if env_override:
        env.update(env_override)

    thread_group = next(root.iter("ThreadGroup"), None)
    if thread_group is None:
        return RunConfig(
            users=1,
            ramp_up_seconds=0.0,
            duration_seconds=DEFAULT_JMETER_DURATION_SECONDS,
            iterations=1,
            think_time_ms=0.0,
            scenario=LoadScenario.CONSTANT,
        )

    users = _int_value(_string_prop(thread_group, "ThreadGroup.num_threads"), env, default=1)
    ramp = _float_value(_string_prop(thread_group, "ThreadGroup.ramp_time"), env, default=0.0)
    duration = _float_value(
        _string_prop(thread_group, "ThreadGroup.duration"),
        env,
        default=DEFAULT_JMETER_DURATION_SECONDS,
    )
    iterations = _loop_iterations(thread_group, env)

    return RunConfig(
        users=users,
        ramp_up_seconds=ramp,
        duration_seconds=duration,
        iterations=iterations,
        think_time_ms=0.0,
        scenario=LoadScenario.CONSTANT,
    )


def _iter_hash_tree_elements(
    root: ET.Element,
    tag: str,
) -> list[tuple[ET.Element, ET.Element | None]]:
    matches: list[tuple[ET.Element, ET.Element | None]] = []
    for hash_tree in root.iter(HASH_TREE_TAG):
        children = list(hash_tree)
        idx = 0
        while idx < len(children):
            element = children[idx]
            subtree = children[idx + 1] if idx + 1 < len(children) else None
            if element.tag == tag:
                matches.append((element, subtree if subtree is not None else None))
            idx += 2 if subtree is not None and subtree.tag == HASH_TREE_TAG else 1
    return matches


def _parse_http_sampler(
    sampler: ET.Element,
    sampler_tree: ET.Element | None,
    root: ET.Element,
    env: dict[str, str],
) -> ParsedRequest | None:
    defaults = _collect_http_request_defaults(root)
    headers = DEFAULT_JMETER_HEADERS | _collect_header_managers(root)
    if sampler_tree is not None:
        headers.update(_collect_header_managers(sampler_tree))

    method = _resolve_vars(
        _string_prop(sampler, "HTTPSampler.method")
        or defaults.get("method")
        or "GET",
        env,
    ).strip().upper()
    url = _build_sampler_url(sampler, defaults, env)
    if not url:
        return None

    arguments = _sampler_arguments(sampler, env)
    post_body_raw = _bool_prop(sampler, "HTTPSampler.postBodyRaw")
    body: str | None = None

    if arguments:
        if post_body_raw:
            body = "".join(value for _, value in arguments)
        elif method in {"GET", "DELETE", "HEAD"}:
            url = _append_query(url, arguments)
        else:
            body = urlencode(arguments)
            _set_header_default(headers, "Content-Type", "application/x-www-form-urlencoded")

    resolved_headers = {
        key: _resolve_vars(value, env)
        for key, value in headers.items()
        if key.strip()
    }

    return ParsedRequest(
        name=sampler.get("testname") or "JMeter HTTP Request",
        method=method,
        url=url,
        headers=resolved_headers,
        body=body,
        folder_path="",
    )


def _collect_http_request_defaults(root: ET.Element) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for element in root.iter(CONFIG_TEST_ELEMENT_TAG):
        testname = (element.get("testname") or "").lower()
        has_http_props = any(
            child.get("name", "").startswith("HTTPSampler.")
            for child in element
            if child.tag == "stringProp"
        )
        if "http request defaults" not in testname and not has_http_props:
            continue
        _merge_default_if_present(defaults, "protocol", element, "HTTPSampler.protocol")
        _merge_default_if_present(defaults, "domain", element, "HTTPSampler.domain")
        _merge_default_if_present(defaults, "port", element, "HTTPSampler.port")
        _merge_default_if_present(defaults, "path", element, "HTTPSampler.path")
        _merge_default_if_present(defaults, "method", element, "HTTPSampler.method")
    return defaults


def _merge_default_if_present(
    defaults: dict[str, str],
    key: str,
    element: ET.Element,
    prop_name: str,
) -> None:
    value = _string_prop(element, prop_name)
    if value:
        defaults[key] = value


def _collect_header_managers(root: ET.Element) -> dict[str, str]:
    headers: dict[str, str] = {}
    for manager in root.iter(HEADER_MANAGER_TAG):
        collection = _child_prop(manager, "HeaderManager.headers")
        if collection is None:
            continue
        for header in collection.iter("elementProp"):
            name = _string_prop(header, "Header.name")
            value = _string_prop(header, "Header.value")
            if name:
                headers[name] = value or ""
    return headers


def _collect_user_defined_variables(root: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for element in root.iter():
        if _is_user_defined_variables(element):
            values.update(_arguments_from_container(element, resolve_env={}))
    return values


def _is_user_defined_variables(element: ET.Element) -> bool:
    if element.tag == ARGUMENTS_TAG:
        return True
    if element.tag == "elementProp" and element.get("name") == "TestPlan.user_defined_variables":
        return True
    return False


def _sampler_arguments(
    sampler: ET.Element,
    env: dict[str, str],
) -> list[tuple[str, str]]:
    container = _child_prop(sampler, "HTTPsampler.Arguments")
    if container is None:
        return []
    parsed = _arguments_from_container(container, resolve_env=env)
    return list(parsed.items())


def _arguments_from_container(
    container: ET.Element,
    resolve_env: dict[str, str],
) -> dict[str, str]:
    args: dict[str, str] = {}
    collection = _child_prop(container, "Arguments.arguments")
    if collection is None and container.tag == "collectionProp":
        collection = container
    if collection is None:
        return args

    for arg in collection:
        if arg.tag != "elementProp":
            continue
        name = _string_prop(arg, "Argument.name") or arg.get("name") or ""
        value = _string_prop(arg, "Argument.value") or ""
        args[_resolve_vars(name, resolve_env)] = _resolve_vars(value, resolve_env)
    return args


def _build_sampler_url(
    sampler: ET.Element,
    defaults: dict[str, str],
    env: dict[str, str],
) -> str:
    raw_path = _resolve_vars(
        _string_prop(sampler, "HTTPSampler.path") or defaults.get("path", ""),
        env,
    )
    if raw_path.startswith(("http://", "https://")):
        return raw_path

    protocol = _resolve_vars(
        _string_prop(sampler, "HTTPSampler.protocol") or defaults.get("protocol", "http"),
        env,
    ).strip() or "http"
    domain = _resolve_vars(
        _string_prop(sampler, "HTTPSampler.domain") or defaults.get("domain", ""),
        env,
    ).strip()
    port = _resolve_vars(
        _string_prop(sampler, "HTTPSampler.port") or defaults.get("port", ""),
        env,
    ).strip()

    if domain.startswith(("http://", "https://")):
        parsed = urlparse(domain)
        protocol = parsed.scheme or protocol
        domain = parsed.netloc or parsed.path

    if not domain:
        return ""

    netloc = domain
    if port and port not in {"80", "443"} and ":" not in netloc:
        netloc = f"{netloc}:{port}"
    path = raw_path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return urlunparse((protocol, netloc, path, "", "", ""))


def _append_query(url: str, arguments: list[tuple[str, str]]) -> str:
    if not arguments:
        return url
    parsed = urlparse(url)
    query = urlencode(arguments)
    if parsed.query:
        query = f"{parsed.query}&{query}"
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def unresolved_variables_in_requests(requests: list[ParsedRequest]) -> dict[str, list[str]]:
    unresolved: dict[str, list[str]] = {}
    for req in requests:
        values = [req.url, *(req.headers.values())]
        if req.body:
            values.append(req.body)
        names: set[str] = set()
        for value in values:
            names.update(match.group(1).strip() for match in JMETER_VAR_PATTERN.finditer(value))
            names.update(
                match.group(1).strip()
                for match in JMETER_VAR_PATTERN.finditer(unquote_plus(value))
            )
        if names:
            unresolved[req.name] = sorted(names)
    return unresolved


def _resolve_vars(text: str, env: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return env.get(key, match.group(0))

    return JMETER_VAR_PATTERN.sub(repl, text)


def _string_prop(element: ET.Element, name: str) -> str | None:
    prop = _child_prop(element, name)
    if prop is None:
        return None
    return prop.text or ""


def _bool_prop(element: ET.Element, name: str) -> bool:
    prop = _child_prop(element, name)
    if prop is None:
        return False
    return (prop.text or "").strip().lower() == "true"


def _child_prop(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if child.get("name") == name:
            return child
    return None


def _set_header_default(headers: dict[str, str], name: str, value: str) -> None:
    if not any(existing.lower() == name.lower() for existing in headers):
        headers[name] = value


def _loop_iterations(thread_group: ET.Element, env: dict[str, str]) -> int:
    controller = _child_prop(thread_group, "ThreadGroup.main_controller")
    if controller is None:
        return 1
    if _bool_prop(controller, "LoopController.continue_forever"):
        return 0
    return _int_value(_string_prop(controller, "LoopController.loops"), env, default=1)


def _int_value(value: str | None, env: dict[str, str], default: int) -> int:
    try:
        return int(float(_resolve_vars(value or "", env).strip()))
    except ValueError:
        return default


def _float_value(value: str | None, env: dict[str, str], default: float) -> float:
    try:
        return float(_resolve_vars(value or "", env).strip())
    except ValueError:
        return default
