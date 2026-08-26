"""
Build a machine-readable catalog of the example projects under `examples/`.

There are 212 example configs across 17 categories, and the only index was a
hand-written `examples/README.md` that had fallen behind: it listed one of the
58 `agent-traces` examples and omitted `crowdsourcing` and `agent-testing`
entirely. Nothing derived from the configs, so nothing could answer "show me a
`bws` example that also uses images".

Everything here is read out of the configs themselves, so the catalog cannot
drift from what is on disk. `scripts/generate_examples_manifest.py` writes it to
two places and `tests/unit/test_examples_manifest_drift.py` fails if the
checked-in copy stops matching.

Usage:
    from potato.server_utils.examples_manifest import build_manifest, load_manifest
    manifest = load_manifest()          # the packaged copy, works from a wheel
    manifest = build_manifest()         # rebuilt from examples/, needs a checkout
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

MANIFEST_FILENAME = "potato-examples.manifest.json"

# Keys worth advertising in the catalog: the ones that say a config exercises a
# whole subsystem, so "find me an example with quality control" works. Plain
# plumbing (task_dir, port) is deliberately absent.
_NOTABLE_KEYS = (
    "active_learning", "adjudication", "agent_proxy", "ai_support", "arena",
    "attention_checks", "automation", "batch_assignment", "boundary_probing",
    "bws_config", "cases", "chat_support", "codebook", "corpus_map",
    "crowdsourcing", "curation", "data_directory", "data_sources", "datasets",
    "diversity_ordering", "event_template", "gold_standards", "ibws_config",
    "icl_labeling", "keystroke_logging", "keyword_highlights_file", "layout",
    "llm_labeling", "mace", "phases", "pocket", "pre_annotation",
    "psychometrics", "qda_mode", "quality_control", "rooms", "search",
    "surveyflow", "task_layout", "thinkaloud", "trace_ingestion", "training",
    "truth_serum",
)

_MODELINE = "yaml-language-server: $schema="


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _schemes(config: Dict[str, Any]) -> List[dict]:
    """Annotation schemes from the top level and from every phase."""
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

    return [s for s in schemes if isinstance(s, dict)]


def _display_types(config: Dict[str, Any]) -> List[str]:
    display = config.get("instance_display")
    if not isinstance(display, dict):
        return []
    fields = display.get("fields")
    if not isinstance(fields, list):
        return []
    return sorted({
        f["type"] for f in fields
        if isinstance(f, dict) and isinstance(f.get("type"), str)
    })


def _description(example_dir: str, config: Dict[str, Any]) -> str:
    """One line about the example: its own description, else its README title."""
    for key in ("task_description", "annotation_task_description"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:300]

    readme = os.path.join(example_dir, "README.md")
    try:
        with open(readme, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return " ".join(line.split())[:300]
    except OSError:
        pass
    return ""


def describe_example(config_path: str, root: Optional[str] = None) -> Optional[dict]:
    """Catalog entry for one example config, or None if it will not parse."""
    import yaml

    root = root or _repo_root()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = f.read()
        config = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(config, dict):
        return None

    example_dir = os.path.dirname(config_path)
    rel_config = os.path.relpath(config_path, root).replace(os.sep, "/")
    rel_dir = os.path.relpath(example_dir, root).replace(os.sep, "/")
    parts = rel_dir.split("/")

    schemes = _schemes(config)
    data_files = config.get("data_files")
    if isinstance(data_files, str):
        data_files = [data_files]
    elif not isinstance(data_files, list):
        data_files = []

    return {
        "path": rel_config,
        "dir": rel_dir,
        # examples/<category>/<name>/ -- flat directories (simulator-configs)
        # have no category segment of their own.
        "category": parts[1] if len(parts) > 2 else parts[-1],
        "name": parts[-1],
        "task_name": config.get("annotation_task_name", ""),
        "description": _description(example_dir, config),
        "annotation_types": sorted({
            s["annotation_type"] for s in schemes
            if isinstance(s.get("annotation_type"), str)
        }),
        "display_types": _display_types(config),
        "config_keys": sorted(k for k in _NOTABLE_KEYS if k in config),
        "data_files": [f for f in data_files if isinstance(f, str)],
        "has_readme": os.path.isfile(os.path.join(example_dir, "README.md")),
        "has_data_dir": os.path.isdir(os.path.join(example_dir, "data")),
        "has_modeline": _MODELINE in raw[:400],
        "run": f"potato start {rel_config} -p 8000",
    }


def build_manifest(root: Optional[str] = None) -> Dict[str, Any]:
    """Walk `examples/` and return the catalog."""
    import glob

    root = root or _repo_root()
    pattern = os.path.join(root, "examples", "**", "config.yaml")

    entries = []
    for config_path in sorted(glob.glob(pattern, recursive=True)):
        entry = describe_example(config_path, root)
        if entry:
            entries.append(entry)

    categories: Dict[str, int] = {}
    for entry in entries:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1

    return {
        "description": (
            "Catalog of Potato example projects, generated from the configs "
            "themselves by scripts/generate_examples_manifest.py."
        ),
        "count": len(entries),
        "categories": dict(sorted(categories.items())),
        "examples": entries,
    }


def load_manifest() -> Optional[Dict[str, Any]]:
    """Read the packaged catalog, falling back to a live build in a checkout.

    `MANIFEST.in` does not ship `examples/`, so from an installed wheel the
    packaged JSON is the only copy that exists.
    """
    packaged = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "schemas",
        MANIFEST_FILENAME,
    )
    try:
        with open(packaged, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass

    try:
        return build_manifest()
    except Exception:  # pragma: no cover - defensive
        return None


def search_examples(
    annotation_type: Optional[str] = None,
    display_type: Optional[str] = None,
    category: Optional[str] = None,
    config_key: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
) -> List[dict]:
    """Filter the catalog. Every argument is an AND-ed constraint."""
    manifest = load_manifest() or {"examples": []}
    results = []

    needle = (query or "").lower().strip()
    for entry in manifest["examples"]:
        if annotation_type and annotation_type not in entry["annotation_types"]:
            continue
        if display_type and display_type not in entry["display_types"]:
            continue
        if category and entry["category"] != category:
            continue
        if config_key and config_key not in entry["config_keys"]:
            continue
        if needle:
            haystack = " ".join([
                entry["dir"], entry["task_name"], entry["description"],
                " ".join(entry["annotation_types"]),
            ]).lower()
            if needle not in haystack:
                continue
        results.append(entry)
        if len(results) >= limit:
            break

    return results
