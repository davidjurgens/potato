"""
File I/O for codebook_lab: loading a seed codebook and platinum example
set, and saving/loading variants and scores for a reproducible run.

Seed codebook file (YAML or JSON) — a flat list of codes:

    - name: "wait times"
      definition: "..."
      clarification: "..."
      negative_clarification: "..."
      positive_examples: [{text: "...", why: "..."}]
      negative_examples: [{text: "...", why: "..."}]
      exclusion_rules: ["..."]

Platinum examples file (YAML or JSON) — a flat list:

    - id: "p1"
      text: "..."
      label: "wait times"   # must match a seed codebook label name
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import yaml

from .models import Code, CodebookVariant, PlatinumExample, VariantScore


def _load_structured(path: str) -> Any:
    with open(path, "rt", encoding="utf-8") as fh:
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(fh)
        return json.load(fh)


def _dump_structured(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wt", encoding="utf-8") as fh:
        if path.endswith((".yaml", ".yml")):
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        else:
            json.dump(data, fh, indent=2, ensure_ascii=False)


def load_seed_codebook(path: str) -> List[Code]:
    raw = _load_structured(path)
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Seed codebook {path} must be a non-empty list of code entries")
    codes = [Code.from_dict(entry) for entry in raw]
    names = [c.name for c in codes]
    if len(set(names)) != len(names):
        dupes = {n for n in names if names.count(n) > 1}
        raise ValueError(f"Seed codebook has duplicate label name(s): {dupes}")
    return codes


def load_platinum_examples(path: str, valid_labels: List[str]) -> List[PlatinumExample]:
    raw = _load_structured(path)
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Platinum examples {path} must be a non-empty list of examples")
    examples = [PlatinumExample.from_dict(entry) for entry in raw]
    ids = [e.example_id for e in examples]
    if len(set(ids)) != len(ids):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"Platinum examples have duplicate id(s): {dupes}")
    valid = set(valid_labels)
    unknown = sorted({e.label for e in examples if e.label not in valid})
    if unknown:
        raise ValueError(
            f"Platinum examples reference label(s) not in the seed "
            f"codebook: {unknown} (seed labels: {sorted(valid)})")
    return examples


def save_variant(out_dir: str, variant: CodebookVariant) -> str:
    path = os.path.join(out_dir, "variants", f"{variant.variant_id}.json")
    _dump_structured(path, variant.to_dict())
    return path


def save_hybrid(out_dir: str, variant: CodebookVariant) -> str:
    """Saved outside variants/ deliberately: a rerun without --regenerate
    reuses everything under variants/*.json as the next run's candidate
    pool, and the hybrid isn't a generated variant, it's this run's
    output. Keeping it separate means a rerun never treats last run's
    hybrid as a fresh candidate."""
    path = os.path.join(out_dir, "hybrid.json")
    _dump_structured(path, variant.to_dict())
    return path


def load_variant(path: str) -> CodebookVariant:
    return CodebookVariant.from_dict(_load_structured(path))


def save_score(out_dir: str, score: VariantScore) -> str:
    path = os.path.join(out_dir, "scores", f"{score.variant_id}.json")
    _dump_structured(path, score.to_dict())
    return path
