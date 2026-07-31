"""
Build an OpenAPI 3.1 description of Potato's HTTP surface.

The spec is *derived* from the live Flask app rather than hand-written, because
the hand-written reference could not keep up: `docs/api-reference/api_reference.md`
documents roughly 84 endpoints against 400+ registered rules, and the gap grew
with every release.

Two things make this non-trivial and are handled explicitly:

1. **Config-gated blueprints.** `create_app()` only registers datasets, arena,
   automation, curation, corpus-map, and the live-agent families when the
   relevant config flag or display type is present. Enumerating only the default
   app would silently omit them, so each optional blueprint is registered onto a
   scratch app and its routes are tagged with the config that switches them on
   (`x-potato-requires-config`).

2. **Auth.** Auth is applied by per-blueprint decorators (`@admin_required`,
   `@api_login_required`, `@same_origin_required`, `@login_required`) rather than
   a central table. Those decorators use `functools.wraps`, so the runtime view
   function keeps its original `__module__`/`__name__`; an AST scan of the source
   recovers which decorators were applied and the result is attached as
   `x-potato-auth`.

Usage:
    from potato.server_utils.openapi_spec import build_openapi_spec
    spec = build_openapi_spec()
"""

import ast
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Decorators that say something about who may call an endpoint.
AUTH_DECORATORS = {
    "admin_required": "admin",
    "_admin_required": "admin",
    "api_login_required": "login",
    "login_required": "login",
    "_login_required": "login",
    "same_origin_required": "same-origin",
}

# Blueprints create_app() registers conditionally, with the config that enables
# them. Kept explicit (rather than inferred) so the gate text stays readable;
# tests/unit/test_openapi_drift.py fails if one of these stops importing.
#
# module path, blueprint attr, config gate
OPTIONAL_BLUEPRINTS: List[Tuple[str, str, str]] = [
    ("potato.eval_datasets.routes", "datasets_bp", "datasets.enabled: true"),
    ("potato.eval_datasets.eval_admin", "eval_admin_bp", "datasets.enabled: true"),
    ("potato.automation.routes", "automation_bp", "automation.enabled: true"),
    ("potato.curation.routes", "curation_bp", "curation.enabled: true"),
    ("potato.arena.routes", "arena_bp", "arena.enabled: true"),
    ("potato.event_registry.routes", "event_registry_bp",
     "event_template.enabled: true or corpus_map.enabled: true"),
    ("potato.corpus_map.routes", "corpus_map_bp", "corpus_map.enabled: true"),
    ("potato.routes_web_agent", "web_agent_bp",
     "instance_display field of type web_agent_trace or web_agent_recorder"),
    ("potato.web_proxy", "web_proxy_bp",
     "instance_display field of type web_agent_trace or web_agent_recorder"),
    ("potato.routes_live_agent", "live_agent_bp",
     "instance_display field of type live_agent"),
    ("potato.routes_live_coding_agent", "live_coding_agent_bp",
     "instance_display field of type live_coding_agent"),
    ("potato.routes_trace_ingestion", "trace_ingestion_bp",
     "trace_ingestion configured"),
]

# Flask converter -> (OpenAPI type, format)
_CONVERTER_TYPES = {
    "int": ("integer", None),
    "float": ("number", None),
    "path": ("string", "path"),
    "uuid": ("string", "uuid"),
    "string": ("string", None),
    "default": ("string", None),
}

_RULE_ARG = re.compile(r"<(?:(?P<conv>[a-zA-Z_]+)(?:\([^>]*\))?:)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")


def _package_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scan_auth_decorators() -> Dict[Tuple[str, str], List[str]]:
    """
    Map (module, function name) -> applied auth decorator names.

    Parses source rather than unwrapping at runtime: the decorators use
    functools.wraps, which makes the wrapper indistinguishable from the view at
    runtime but leaves the source unambiguous.
    """
    found: Dict[Tuple[str, str], List[str]] = {}
    root = _package_root()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "static", "templates"}]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, os.path.dirname(root))
            module = rel[:-3].replace(os.sep, ".")
            if module.endswith(".__init__"):
                module = module[: -len(".__init__")]
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                names = []
                for dec in node.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    name = getattr(target, "attr", None) or getattr(target, "id", None)
                    if name in AUTH_DECORATORS:
                        names.append(name)
                if names:
                    found.setdefault((module, node.name), [])
                    for name in names:
                        if name not in found[(module, node.name)]:
                            found[(module, node.name)].append(name)
    return found


def _flask_path_to_openapi(rule: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Convert '/item/<int:id>' to '/item/{id}' plus its parameter objects."""
    params: List[Dict[str, Any]] = []

    def replace(match):
        conv = match.group("conv") or "default"
        name = match.group("name")
        type_name, fmt = _CONVERTER_TYPES.get(conv, ("string", None))
        schema: Dict[str, Any] = {"type": type_name}
        if fmt:
            schema["format"] = fmt
        params.append({
            "name": name,
            "in": "path",
            "required": True,
            "schema": schema,
        })
        return "{" + name + "}"

    return _RULE_ARG.sub(replace, rule), params


def _summary(view_func) -> Optional[str]:
    doc = (view_func.__doc__ or "").strip()
    if not doc:
        return None
    first = doc.splitlines()[0].strip()
    return first or None


def _unique_operation_id(base: str, path: str, used: set) -> str:
    """
    Return an unused operationId.

    Flask lets one endpoint serve several rules (e.g. an aliased path), which
    would otherwise emit the same operationId twice — invalid OpenAPI. Collisions
    are disambiguated with a slug of the path so the id stays stable across runs
    rather than depending on iteration order.
    """
    if base not in used:
        used.add(base)
        return base
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
    candidate = f"{base}__{slug}"
    suffix = 2
    while candidate in used:
        candidate = f"{base}__{slug}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _collect(app, auth_map, gate=None, seen=None, used_ids=None) -> Dict[str, Dict[str, Any]]:
    """Turn a Flask app's url_map into OpenAPI path items."""
    paths: Dict[str, Dict[str, Any]] = {}
    seen = seen if seen is not None else set()
    used_ids = used_ids if used_ids is not None else set()

    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        if rule.endpoint == "static":
            continue
        methods = sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})
        if not methods:
            continue

        path, params = _flask_path_to_openapi(str(rule))
        view_func = app.view_functions.get(rule.endpoint)
        auth = auth_map.get(
            (getattr(view_func, "__module__", ""), getattr(view_func, "__name__", "")),
            [],
        )
        tag = rule.endpoint.split(".")[0] if "." in rule.endpoint else "core"

        for method in methods:
            key = (path, method.lower())
            if key in seen:
                continue
            seen.add(key)

            operation: Dict[str, Any] = {
                "operationId": _unique_operation_id(
                    f"{method.lower()}_{rule.endpoint.replace('.', '_')}",
                    path,
                    used_ids,
                ),
                "tags": [tag],
                "responses": {"200": {"description": "Success"}},
            }
            summary = _summary(view_func) if view_func else None
            if summary:
                operation["summary"] = summary
            if params:
                operation["parameters"] = params
            if auth:
                operation["x-potato-auth"] = auth
                levels = {AUTH_DECORATORS[a] for a in auth}
                operation["responses"]["401"] = {"description": "Authentication required"}
                if "admin" in levels:
                    operation["responses"]["403"] = {"description": "Admin role required"}
            if gate:
                operation["x-potato-requires-config"] = gate

            paths.setdefault(path, {})[method.lower()] = operation

    return paths


def build_openapi_spec(version: str = "") -> Dict[str, Any]:
    """Return the OpenAPI 3.1 spec for Potato's HTTP API as a plain dict."""
    import logging
    import warnings

    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore")

    from flask import Flask

    from potato.flask_server import create_app

    auth_map = scan_auth_decorators()

    seen: set = set()
    used_ids: set = set()
    paths = _collect(create_app(), auth_map, seen=seen, used_ids=used_ids)

    skipped: List[str] = []
    for module_path, attr, gate in OPTIONAL_BLUEPRINTS:
        try:
            module = __import__(module_path, fromlist=[attr])
            blueprint = getattr(module, attr)
            scratch = Flask(f"_probe_{attr}")
            scratch.register_blueprint(blueprint)
        except Exception as exc:  # pragma: no cover - reported, not fatal
            skipped.append(f"{module_path}.{attr}: {type(exc).__name__}")
            continue
        collected = _collect(scratch, auth_map, gate=gate, seen=seen, used_ids=used_ids)
        for path, ops in collected.items():
            paths.setdefault(path, {}).update(ops)

    spec: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Potato HTTP API",
            "description": (
                "Generated from the live Flask url_map — see "
                "potato/server_utils/openapi_spec.py.\n\n"
                "Most endpoints are session-authenticated: POST /auth with "
                "`username` and `password` as form data, then reuse the session "
                "cookie. `x-potato-auth` records the decorators guarding an "
                "operation, and `x-potato-requires-config` marks operations that "
                "only exist when the named config is enabled.\n\n"
                "Response schemas are intentionally not modelled; this spec is an "
                "authoritative index of what exists, not a payload contract."
            ),
            "version": version or "unknown",
        },
        "servers": [{"url": "http://localhost:8000"}],
        "paths": dict(sorted(paths.items())),
    }
    if skipped:
        spec["info"]["x-potato-unavailable-blueprints"] = sorted(skipped)
    return spec
