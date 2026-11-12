"""
A label hierarchy from a file, for ``hierarchical_multiselect``.

``taxonomy_file: codebooks/cap_topics.csv`` loads a codebook the project
supplies, such as the Comparative Agendas Project topics or the Manifesto
Project categories (neither is bundled: CAP is CC BY-NC-SA and the Manifesto
Project does not allow redistribution).

CSV columns: ``code``, ``label``, ``parent`` (the parent's code, empty for a
top-level category) and optional ``description`` (the tooltip). Order is
kept. A JSON or YAML file holding the ``taxonomy`` mapping itself also works;
its top level must be a mapping, as in the config, not a list.
With ``show_codes: true`` each entry reads ``<code> <label>``.

The scheme stores the entry's text, so two entries with the same text would
be one answer: ticking either ticks both on restore. A file where that happens
is refused (``show_codes: true`` makes CSV entries distinct).
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from typing import Any, Dict, Tuple

import yaml


class TaxonomyFileError(ValueError):
    pass


def load_taxonomy_file(path: str, show_codes: bool = False) -> Tuple[Any, Dict[str, str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json", ".yaml", ".yml"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f) if ext == ".json" else yaml.safe_load(f)
        if isinstance(data, dict) and "taxonomy" in data:
            taxonomy, tips = data["taxonomy"], dict(data.get("tooltips") or {})
        else:
            taxonomy, tips = data, {}
        # The scheme's taxonomy is a mapping of top-level categories to their
        # children (a list of leaves or another mapping), as in the config.
        if isinstance(taxonomy, list):
            raise TaxonomyFileError(
                f"{path}: the top level must be a mapping of categories to their "
                f"children, not a list. Write each top-level entry as a key "
                f"(Sciences: [Physics, Biology]); an entry with no children takes an "
                f"empty list (Other: []).")
        if not isinstance(taxonomy, dict) or not taxonomy:
            raise TaxonomyFileError(f"{path}: expected a non-empty mapping of categories "
                                    f"to their children")
        seen_labels = Counter(_labels(taxonomy))
        repeated = sorted(lab for lab, n in seen_labels.items() if n > 1)
        if repeated:
            raise TaxonomyFileError(
                f"{path}: these entries appear more than once, so they would be one answer: "
                f"{', '.join(repeated)}. Give each entry its own text.")
        return taxonomy, tips
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows or not {"code", "label"} <= set(rows[0]):
        raise TaxonomyFileError(f"{path}: needs columns code, label and parent (and optionally "
                                "description)")
    by_code: Dict[str, dict] = {}
    for i, r in enumerate(rows, start=2):
        code = (r.get("code") or "").strip()
        label = (r.get("label") or "").strip()
        if not code or not label:
            raise TaxonomyFileError(f"{path} line {i}: code and label are required")
        if code in by_code:
            raise TaxonomyFileError(f"{path} line {i}: code {code} appears twice")
        by_code[code] = {"label": f"{code} {label}" if show_codes else label,
                         "parent": (r.get("parent") or "").strip(),
                         "description": (r.get("description") or "").strip(), "children": []}
    codes_by_label: Dict[str, list] = {}
    for code, node in by_code.items():
        codes_by_label.setdefault(node["label"], []).append(code)
    repeated = {lab: codes for lab, codes in codes_by_label.items() if len(codes) > 1}
    if repeated:
        listed = "; ".join(f"{lab!r} (codes {', '.join(codes)})" for lab, codes in repeated.items())
        raise TaxonomyFileError(
            f"{path}: the scheme stores an entry's label, so entries with the same label would be "
            f"one answer: {listed}. Give them different labels, or set show_codes: true so each "
            f"reads '<code> <label>'.")
    roots = []
    for code, node in by_code.items():
        parent = node["parent"]
        if parent:
            if parent not in by_code:
                raise TaxonomyFileError(f"{path}: {code} names parent {parent}, which is not a code")
            by_code[parent]["children"].append(code)
        else:
            roots.append(code)
    # A cycle has no root to reach it from.
    seen = set()

    def build(code, depth=0):
        if code in seen or depth > 20:
            raise TaxonomyFileError(f"{path}: the parent links around {code} form a loop")
        seen.add(code)
        node = by_code[code]
        if not node["children"]:
            return None
        kids = [(by_code[c]["label"], build(c, depth + 1)) for c in node["children"]]
        if all(sub is None for _l, sub in kids):
            return [lab for lab, _ in kids]
        return {lab: (sub if sub is not None else []) for lab, sub in kids}

    taxonomy = {by_code[c]["label"]: (build(c) or []) for c in roots}
    if len(seen) != len(by_code):
        raise TaxonomyFileError(f"{path}: some parent links form a loop")
    tooltips = {n["label"]: n["description"] for n in by_code.values() if n["description"]}
    return taxonomy, tooltips


def _labels(taxonomy: Any) -> list:
    """Every entry's text in a taxonomy mapping, at every depth."""
    out = []
    if isinstance(taxonomy, dict):
        for key, sub in taxonomy.items():
            out.append(str(key))
            out.extend(_labels(sub))
    elif isinstance(taxonomy, list):
        for item in taxonomy:
            out.extend(_labels(item) if isinstance(item, (dict, list)) else [str(item)])
    return out


def apply_taxonomy_files(config_data: Dict[str, Any], config_file_dir: str) -> None:
    """Resolve ``taxonomy_file`` on every hierarchical_multiselect scheme."""
    from potato.server_utils.config_module import ConfigValidationError, validate_path_security
    task_dir = config_data.get("task_dir") or config_file_dir
    for idx, scheme in enumerate(config_data.get("annotation_schemes") or []):
        if not isinstance(scheme, dict) or not scheme.get("taxonomy_file"):
            continue
        if scheme.get("taxonomy"):
            raise ConfigValidationError(
                f"annotation_schemes[{idx}]: give taxonomy or taxonomy_file, not both")
        rel = str(scheme["taxonomy_file"])
        candidates = [rel] if os.path.isabs(rel) else [os.path.join(b, rel) for b in (task_dir, config_file_dir)]
        path = next((p for p in candidates if os.path.isfile(p)), None)
        if path is None:
            raise ConfigValidationError(
                f"annotation_schemes[{idx}].taxonomy_file: file not found: {rel}")
        validate_path_security(os.path.abspath(path), task_dir)
        try:
            taxonomy, tips = load_taxonomy_file(path, bool(scheme.get("show_codes")))
        except TaxonomyFileError as e:
            raise ConfigValidationError(f"annotation_schemes[{idx}].taxonomy_file: {e}") from None
        scheme["taxonomy"] = taxonomy
        merged = dict(tips)
        merged.update(scheme.get("tooltips") or {})
        if merged:
            scheme["tooltips"] = merged
