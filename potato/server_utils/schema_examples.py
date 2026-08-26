"""
Worked `annotation_schemes` examples for each registered annotation type.

Every type has ~10 optional fields and no per-field prose anywhere, so telling
someone -- or something -- what a `constant_sum` scheme looks like meant either
writing 600 field descriptions by hand or shipping examples that drift.

Neither is necessary. `docs/annotation-types/schemas_and_templates.md` already
maps every registered type to an example directory, and
`tests/unit/test_schema_registry_docs_sync.py` already proves those directories
exist and really use the type they claim. So the example is extracted from the
config that is known to work, rather than written down a second time.

Consumers:

    config_schema._annotation_schemes_schema()  -> `examples` on the per-type branch
    scripts/generate_config_reference.py        -> the per-type YAML block
    potato/mcp_server/                          -> describe_annotation_type

Falls back to `None` rather than raising: the docs tree is absent from an
installed wheel (`MANIFEST.in` ships neither `docs/` nor `examples/`), so
callers must treat a missing example as normal.

Usage:
    from potato.server_utils.schema_examples import example_scheme_for
    scheme = example_scheme_for("bws")
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Dict, Optional, Tuple

# `| `type_name` | Description | Details link | `examples/dir/` |`
_ROW = re.compile(
    r"^\|\s*`([a-z_0-9]+)`\s*\|[^|]*\|[^|]*\|\s*`?([^|`]*?)`?\s*\|\s*$",
    flags=re.MULTILINE,
)

# Fields the server writes onto a scheme before rendering. They are not config,
# so they must not appear in an example someone copies.
_SERVER_WRITTEN = {"annotation_id", "_allocated_keys", "label2value", "codebook_guidance"}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _doc_path() -> str:
    return os.path.join(
        _repo_root(), "docs", "annotation-types", "schemas_and_templates.md"
    )


@lru_cache(maxsize=1)
def example_dirs() -> Dict[str, str]:
    """Map annotation type -> example directory, from the reference table."""
    path = _doc_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}

    out: Dict[str, str] = {}
    for match in _ROW.finditer(text):
        type_name, example = match.group(1), match.group(2).strip()
        if example.startswith("examples/"):
            out[type_name] = example.rstrip("/")
    return out


@lru_cache(maxsize=None)
def _schemes_in(config_dir: str) -> Tuple[dict, ...]:
    """Every annotation scheme in one example config, top-level and per-phase."""
    import yaml

    config_path = os.path.join(_repo_root(), config_dir, "config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return ()
    if not isinstance(config, dict):
        return ()

    schemes = list(config.get("annotation_schemes") or [])

    phases = config.get("phases")
    if isinstance(phases, list):
        for phase in phases:
            if isinstance(phase, dict):
                schemes.extend(phase.get("annotation_schemes") or [])
    elif isinstance(phases, dict):
        for name, phase in phases.items():
            if name != "order" and isinstance(phase, dict):
                schemes.extend(phase.get("annotation_schemes") or [])

    return tuple(s for s in schemes if isinstance(s, dict))


def example_scheme_for(type_name: str) -> Optional[dict]:
    """A working `annotation_schemes` entry for one type, or None.

    Returns the first scheme of that type in the example config the docs table
    links to, with any server-written fields stripped.
    """
    config_dir = example_dirs().get(type_name)
    if not config_dir:
        return None

    for scheme in _schemes_in(config_dir):
        if scheme.get("annotation_type") == type_name:
            return {k: v for k, v in scheme.items() if k not in _SERVER_WRITTEN}
    return None


def example_source_for(type_name: str) -> Optional[str]:
    """Repo-relative path of the config an example was taken from."""
    config_dir = example_dirs().get(type_name)
    return f"{config_dir}/config.yaml" if config_dir else None


def clear_cache() -> None:
    """Drop memoized reads. For tests that write example configs."""
    example_dirs.cache_clear()
    _schemes_in.cache_clear()
