"""
Question files for survey-style phases (consent, prestudy, poststudy, ...).

Shared by the server, which renders them at boot, and by config validation,
which checks them first. They used to be read only at boot, so `potato
validate` passed a phase file with an unknown question type that `potato
start` then refused.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import yaml

#: Phase types whose `file` holds items or HTML rather than question objects.
NON_QUESTION_PHASE_TYPES = frozenset({"training", "annotation"})
QUESTION_FILE_SUFFIXES = (".json", ".jsonl", ".yaml", ".yml")


def load_phase_schemes(filename: str) -> List[Any]:
    """The question objects in a phase file (.json, .jsonl, .yaml or .yml)."""
    if not os.path.exists(filename):
        raise Exception("Phase labeling schemes file %s does not exist" % filename)

    schemes: Any = []
    if filename.endswith(".json"):
        with open(filename, "rt", encoding="utf-8") as f:
            schemes = json.load(f)
        # A single question may be given without a surrounding list.
        if not isinstance(schemes, list):
            schemes = [schemes]
    elif filename.endswith(".jsonl"):
        with open(filename, "rt", encoding="utf-8") as f:
            for line_no, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    schemes.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON at line {line_no + 1} in {filename}: {e}") from e
    elif filename.endswith((".yaml", ".yml")):
        with open(filename, "rt", encoding="utf-8") as f:
            schemes = yaml.safe_load(f)
    else:
        raise Exception("Unknown file format for phase labeling schemes file %s" % filename)
    return schemes


def check_phase_schemes(schemes: Iterable[Any], source: str, phase_name: str,
                        listed_plugins: Optional[Iterable[str]] = None) -> None:
    """Refuse a phase file whose entries cannot be rendered, and say which.

    Each entry needs annotation_type, name and description, and the type must
    be registered -- by Potato, or by a plugin the config lists. The message
    names the file, the position and the question, so the author of a long
    survey file does not have to read every entry to find the bad one.
    """
    from potato import plugins
    from potato.server_utils.schemas.registry import schema_registry

    listed = set(listed_plugins or [])
    required = ("annotation_type", "name", "description")
    problems = []
    for index, scheme in enumerate(schemes or []):
        if not isinstance(scheme, dict):
            problems.append(f"  entry {index}: expected a question object, got "
                            f"{type(scheme).__name__}")
            continue
        named = scheme.get("name") or scheme.get("description") or "(unnamed)"
        missing = [key for key in required if not scheme.get(key)]
        if missing:
            problems.append(f"  entry {index} ({named!r}) is missing: {', '.join(missing)}")
            continue
        kind = scheme["annotation_type"]
        owner = plugins.owner_of("schema", kind) if isinstance(kind, str) else None
        if owner and owner not in listed:
            problems.append(f"  entry {index} ({named!r}): annotation type '{kind}' comes "
                            f"from plugin '{owner}'; add '{owner}' to plugins")
        elif not isinstance(kind, str) or not schema_registry.is_registered(kind):
            problems.append(f"  entry {index} ({named!r}): '{kind}' is not an annotation type")
    if problems:
        raise ValueError(
            f"{source} cannot be rendered as the '{phase_name}' phase.\n"
            + "\n".join(problems)
            + "\nEvery question needs annotation_type, name and description, and a "
              "known annotation_type."
        )


def question_file_phases(config_data: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """(phase name, file) for every phase whose `file` holds questions."""
    phases = config_data.get("phases")
    if isinstance(phases, list):
        entries = [(p.get("name"), p) for p in phases if isinstance(p, dict)]
    elif isinstance(phases, dict):
        entries = [(k, v) for k, v in phases.items() if k != "order" and isinstance(v, dict)]
    else:
        return
    for name, phase in entries:
        if "annotation_schemes" in phase:
            continue
        kind = str(phase.get("type") or name or "").lower()
        filename = phase.get("file")
        if kind in NON_QUESTION_PHASE_TYPES or not isinstance(filename, str):
            continue
        if filename.lower().endswith(QUESTION_FILE_SUFFIXES):
            yield str(name), filename


def resolve_phase_file(filename: str, config_file_dir: Optional[str]) -> Optional[str]:
    """Where the server will find a phase file, in the order it looks; None if absent."""
    candidates = [filename]
    if config_file_dir:
        candidates.append(os.path.join(config_file_dir, filename))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(config_file_dir)), filename))
    candidates.append(os.path.join(os.getcwd(), filename))
    return next((c for c in candidates if os.path.isfile(c)), None)
