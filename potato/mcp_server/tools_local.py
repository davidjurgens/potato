"""
The local half of Potato's MCP surface: everything answerable without a server.

Each function is a thin, JSON-shaped wrapper over machinery that already exists
-- the schema and display registries, `CONFIG_KEY_DOCS`, the packaged JSON
Schema, the examples catalog, `validate_cli`, `preview_cli` and
`preview_render`. Nothing here reimplements validation or rendering, so an agent
asking over MCP and a human running `potato validate` get the same answer from
the same code.

Plain functions rather than decorated MCP tools, so they can be tested and
called directly. `server.py` registers them.

Every function returns a plain dict or list. Errors come back as
`{"error": ...}` rather than as exceptions: a tool call that raises tells the
agent only that something went wrong, while a returned message tells it what to
fix.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# Fields the server writes onto a scheme at render time. They are not config and
# must never appear in an example an agent might copy.
_INTERNAL_SCHEME_FIELDS = {
    "annotation_id", "_allocated_keys", "label2value", "codebook_guidance",
}


# ----------------------------------------------------------------- registries --

def list_annotation_types() -> List[Dict[str, Any]]:
    """Every registered annotation type, with a one-line description.

    The starting point for "what can this thing do".
    """
    from potato.server_utils.schemas.registry import schema_registry

    return [
        {
            "name": s["name"],
            "description": s["description"],
            "required_fields": [
                f for f in s["required_fields"] if f not in ("name", "description")
            ],
            "optional_field_count": len(s["optional_fields"]),
        }
        for s in schema_registry.list_schemas()
    ]


def describe_annotation_type(name: str) -> Dict[str, Any]:
    """Everything needed to write a scheme of this type.

    The worked example is the useful part: it is lifted from the example config
    the docs link to, which CI already proves runs and really uses this type.
    """
    from potato.server_utils.schema_examples import (
        example_scheme_for,
        example_source_for,
    )
    from potato.server_utils.schemas.registry import (
        UNIVERSAL_OPTIONAL_FIELDS,
        UNIVERSAL_REQUIRED_FIELDS,
        schema_registry,
    )

    definition = schema_registry.get(name)
    if definition is None:
        return {
            "error": f"Unknown annotation type: {name!r}",
            "supported_types": schema_registry.get_supported_types(),
        }

    return {
        "name": definition.name,
        "description": definition.description,
        "required_fields": sorted(set(definition.required_fields)),
        "optional_fields": sorted(set(definition.optional_fields)),
        "universal_required_fields": sorted(UNIVERSAL_REQUIRED_FIELDS),
        "universal_optional_fields": sorted(UNIVERSAL_OPTIONAL_FIELDS),
        "supports_keybindings": definition.supports_keybindings,
        # True for the types where several inputs with different label_name
        # values make up one logical answer (radio, likert, confidence).
        "single_select": definition.single_select,
        "example": example_scheme_for(name),
        "example_source": example_source_for(name),
    }


def list_display_types() -> List[Dict[str, Any]]:
    """Every registered `instance_display` field type."""
    from potato.server_utils.displays import display_registry

    return [
        {
            "name": d["name"],
            "description": d.get("description", ""),
            "supports_span_target": d.get("supports_span_target", False),
        }
        for d in display_registry.list_displays()
    ]


def describe_display_type(name: str) -> Dict[str, Any]:
    """Required and optional keys for one `instance_display` field type."""
    from potato.server_utils.displays import display_registry

    definition = display_registry.get(name)
    if definition is None:
        return {
            "error": f"Unknown display type: {name!r}",
            "supported_types": display_registry.get_supported_types(),
        }

    optional = definition.optional_fields
    return {
        "name": definition.name,
        "description": definition.description,
        "required_fields": sorted(definition.required_fields),
        "optional_fields": sorted(optional) if optional else [],
        "supports_span_target": definition.supports_span_target,
    }


# ---------------------------------------------------------------- config keys --

def list_config_keys(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Documented top-level config keys, optionally filtered by category."""
    from potato.server_utils.config_key_docs import UNSET, iter_key_docs

    out = []
    for path, doc in iter_key_docs():
        if "." in path:
            continue
        if category and doc.category != category:
            continue
        entry = {
            "key": path,
            "type": doc.type,
            "summary": doc.summary,
            "required": doc.required,
            "category": doc.category,
        }
        if doc.default is not UNSET:
            entry["default"] = doc.default
        out.append(entry)
    return out


def describe_config_key(path: str) -> Dict[str, Any]:
    """One config key by dotted path, e.g. `attention_checks.frequency`.

    Reports sub-keys for a container, and says plainly when a key is recognized
    but not yet documented -- which is different from not existing, and an agent
    should not conclude the second from the first.
    """
    from potato.server_utils.config_key_docs import UNSET, get_key_doc
    from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

    node: Any = KNOWN_CONFIG_KEYS
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, set) and part in node:
            node = None
        else:
            return {
                "error": f"Not a recognized config key: {path!r}",
                "hint": "Use list_config_keys() to see the documented keys.",
            }

    result: Dict[str, Any] = {"key": path, "recognized": True}
    if isinstance(node, dict):
        result["sub_keys"] = sorted(node)
    elif isinstance(node, set):
        result["sub_keys"] = sorted(node)

    doc = get_key_doc(path)
    if doc is None:
        result["documented"] = False
        result["note"] = (
            "This key is accepted by the server but has no entry in "
            "CONFIG_KEY_DOCS yet."
        )
        return result

    result.update({
        "documented": True,
        "type": doc.type,
        "summary": doc.summary,
        "required": doc.required,
        "category": doc.category,
    })
    if doc.default is not UNSET:
        result["default"] = doc.default
    if doc.example is not None:
        result["example"] = doc.example
    if doc.see_also:
        result["see_also"] = list(doc.see_also)
    return result


def get_config_schema() -> Dict[str, Any]:
    """The full config JSON Schema, as published."""
    from potato.server_utils.config_schema import build_config_schema

    return build_config_schema()


# -------------------------------------------------------------------- examples --

def list_examples(
    annotation_type: Optional[str] = None,
    display_type: Optional[str] = None,
    category: Optional[str] = None,
    config_key: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search the catalog of shipped example projects.

    Filters are AND-ed. Copying a working example beats assembling a config from
    field lists, so this is usually the first thing to reach for.
    """
    from potato.server_utils.examples_manifest import search_examples

    results = search_examples(
        annotation_type=annotation_type,
        display_type=display_type,
        category=category,
        config_key=config_key,
        query=query,
        limit=limit,
    )
    return {
        "count": len(results),
        "examples": [
            {
                "dir": r["dir"],
                "path": r["path"],
                "task_name": r["task_name"],
                "annotation_types": r["annotation_types"],
                "display_types": r["display_types"],
                "config_keys": r["config_keys"],
                "run": r["run"],
            }
            for r in results
        ],
    }


def get_example(name: str) -> Dict[str, Any]:
    """The full config text of one example, by directory or path.

    Accepts `classification/check-box`, `examples/classification/check-box`, or
    the path to its config.yaml.
    """
    from potato.server_utils.examples_manifest import load_manifest

    manifest = load_manifest()
    if not manifest:
        return {"error": "The examples catalog is unavailable."}

    wanted = name.rstrip("/")
    candidates = [wanted, f"examples/{wanted}"]
    if wanted.endswith("config.yaml"):
        candidates.append(os.path.dirname(wanted))

    entry = None
    for candidate in candidates:
        for e in manifest["examples"]:
            if e["dir"] == candidate or e["path"] == candidate:
                entry = e
                break
        if entry:
            break

    if entry is None:
        return {
            "error": f"No example named {name!r}",
            "hint": "Use list_examples() to find one.",
        }

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    config_path = os.path.join(repo_root, entry["path"])
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_text = f.read()
    except OSError:
        # Expected from an installed wheel: `examples/` is not packaged, so the
        # catalog knows the example exists but the file is not on disk.
        return {
            **entry,
            "config_text": None,
            "note": (
                "The catalog entry is packaged but the example files are not. "
                "Read it from the repository: "
                f"https://github.com/davidjurgens/potato/blob/master/{entry['path']}"
            ),
        }

    return {**entry, "config_text": config_text}


# ------------------------------------------------------------------ validation --

def validate_config(
    path: Optional[str] = None, yaml_text: Optional[str] = None
) -> Dict[str, Any]:
    """Run the server's own validator over a config.

    Give either a path or the YAML text. This is the same code path as
    `potato validate`, so an agent that satisfies it has satisfied the server.
    """
    import tempfile

    from potato.validate_cli import validate_config_file

    if not path and not yaml_text:
        return {"error": "Pass either `path` or `yaml_text`."}

    if yaml_text and not path:
        # Written beside the caller's cwd rather than in the system temp dir:
        # `validate_yaml_structure` resolves relative data paths against the
        # config's own directory, and a config in /tmp cannot see them.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", dir=os.getcwd(), delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_text)
            temp_path = f.name
        try:
            report = validate_config_file(temp_path)
        finally:
            os.unlink(temp_path)
        result = report.to_dict()
        result["config_file"] = "<yaml_text>"
        return result

    return validate_config_file(path).to_dict()


def preview_config(path: str) -> Dict[str, Any]:
    """What a config declares: schemes, labels, keybindings and conflicts.

    Answers "did I build the form I meant to" without starting a server.
    """
    from potato.preview_cli import (
        detect_keybinding_conflicts,
        generate_preview_json,
        get_annotation_schemes,
        load_config,
        validate_config as _validate,
    )

    if not os.path.isfile(path):
        return {"error": f"Config file not found: {path}"}

    try:
        config = load_config(path)
        issues = _validate(config, path)
        schemes = get_annotation_schemes(config)
        payload = json.loads(generate_preview_json(config, schemes, issues))
        payload["keybinding_conflicts"] = detect_keybinding_conflicts(schemes)
        return payload
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
