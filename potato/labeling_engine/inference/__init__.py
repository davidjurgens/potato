"""
One human label per item, from however many people labeled it.

``infer`` turns ``{item: {person: label}}`` into ``{item: (label, confidence)}``:

- ``majority``: the most common label; ties go to the label given first.
  Confidence is the winning share.
- ``dawid_skene``: worker-quality-weighted consensus
  (``server_utils/consensus.py``), fitted on every multiply-labeled item at
  once, so a careless rater's vote counts for less. Confidence is the
  posterior of the chosen label.

Only people go in. Machine raters may help choose final labels elsewhere, but
the labels contracts certify against are human ground truth (invariant 5 in
``plans/llm-labeling-engine-v2.md``); a machine voting on its own test would
grade its own homework.

An adjudicated label, where one exists, replaces the inferred one: that is a
decision someone made after seeing the disagreement.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, Hashable, Mapping, Optional, Tuple

METHODS = ("majority", "dawid_skene")


def _key(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, default=str)


def majority(labels: Mapping[str, Any]) -> Tuple[Any, float]:
    vals = list(labels.values())
    if not vals:
        return None, 0.0
    counts = Counter(_key(v) for v in vals)
    best = max(counts.values())
    for v in vals:
        if counts[_key(v)] == best:
            return v, best / len(vals)


def infer(labels_by_item: Mapping[Hashable, Mapping[str, Any]], method: str = "majority",
          adjudicated: Optional[Mapping[Hashable, Any]] = None
          ) -> Dict[Hashable, Tuple[Any, float]]:
    if method not in METHODS:
        raise ValueError(f"unknown truth method {method!r}; use one of {METHODS}")
    out: Dict[Hashable, Tuple[Any, float]] = {}
    if method == "dawid_skene":
        from potato.server_utils.consensus import dawid_skene
        # Values must be hashable class labels; structured answers (box sets,
        # step maps) have no class structure and fall back to majority.
        obs, structured = [], set()
        for item, people in labels_by_item.items():
            for person, label in people.items():
                if isinstance(label, (dict, list)):
                    structured.add(item)
                else:
                    obs.append((str(person), str(item), str(label)))
        res = dawid_skene(obs) if obs else None
        originals = {(str(i), str(v)): v for i, ppl in labels_by_item.items()
                     for v in ppl.values() if not isinstance(v, (dict, list))}
        for item, people in labels_by_item.items():
            if item in structured or res is None or str(item) not in res.labels:
                out[item] = majority(people)
                continue
            lab = res.labels[str(item)]
            out[item] = (originals.get((str(item), lab), lab),
                         float(res.confidence.get(str(item), 0.0)))
    else:
        for item, people in labels_by_item.items():
            out[item] = majority(people)
    for item, label in (adjudicated or {}).items():
        if item in out or item in labels_by_item:
            out[item] = (label, 1.0)
    return out
