"""
Perspectivist / soft-label export: treat annotator disagreement as signal.

Majority vote (and even Dawid-Skene consensus, [[project_agent_eval_differentiation]])
collapse every item to one answer. The perspectivist frontier moves the opposite
way: preserve and export the **distribution** of annotator labels, an **ambiguity**
flag for genuinely contested items, and per-annotator perspectives — which improves
uncertainty estimation and soft-label training, and surfaces items worth a second
look. Potato already stores every per-annotator label, so this is mostly a
distribution + export layer over data it holds.

Pure stdlib, deterministic.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Observation = Tuple[str, str, str]  # (annotator, item, label)


@dataclass
class SoftLabel:
    item: str
    distribution: Dict[str, float] = field(default_factory=dict)  # label -> probability
    hard_label: Optional[str] = None        # the modal label (ties → first by sort)
    entropy: float = 0.0                      # normalized Shannon entropy in [0, 1]
    n_annotators: int = 0
    ambiguous: bool = False                   # entropy ≥ threshold (contested)
    annotators: Dict[str, str] = field(default_factory=dict)  # annotator -> label

    def to_dict(self) -> Dict:
        return {"item": self.item,
                "distribution": {k: round(v, 4) for k, v in self.distribution.items()},
                "hard_label": self.hard_label, "entropy": round(self.entropy, 4),
                "n_annotators": self.n_annotators, "ambiguous": self.ambiguous,
                "annotators": self.annotators}


def normalized_entropy(distribution: Dict[str, float]) -> float:
    """Shannon entropy of a label distribution, normalized to [0,1] by log(k) where
    k is the number of *observed* labels. 0 = unanimous, 1 = maximally split."""
    probs = [p for p in distribution.values() if p > 0]
    if len(probs) <= 1:
        return 0.0
    h = -sum(p * math.log(p) for p in probs)
    return h / math.log(len(probs))


def soft_labels(observations: List[Observation], ambiguity_threshold: float = 0.5
                ) -> List[SoftLabel]:
    """Per-item soft label distributions from raw annotator labels.

    ``ambiguity_threshold`` is on normalized entropy: an item is flagged
    ``ambiguous`` when annotators are split at/above it. Returns items sorted by
    entropy desc (most contested first).
    """
    by_item: Dict[str, Dict[str, str]] = defaultdict(dict)
    for ann, item, label in observations:
        by_item[item][ann] = label  # last label wins per annotator

    out: List[SoftLabel] = []
    for item, ann_labels in by_item.items():
        counts: Dict[str, int] = defaultdict(int)
        for lab in ann_labels.values():
            counts[lab] += 1
        n = sum(counts.values())
        dist = {lab: c / n for lab, c in counts.items()} if n else {}
        # hard label = modal (ties broken by label sort for determinism)
        hard = None
        if dist:
            top = max(dist.values())
            hard = sorted([l for l, p in dist.items() if p == top])[0]
        ent = normalized_entropy(dist)
        out.append(SoftLabel(item=item, distribution=dist, hard_label=hard, entropy=ent,
                             n_annotators=len(ann_labels), ambiguous=ent >= ambiguity_threshold,
                             annotators=dict(ann_labels)))
    out.sort(key=lambda s: s.entropy, reverse=True)
    return out


def annotator_perspectives(observations: List[Observation]) -> Dict[str, Dict]:
    """Per-annotator perspective summary: how often they side with the majority vs
    take a minority view (a perspectivist's contribution, not an error)."""
    softs = {s.item: s for s in soft_labels(observations)}
    by_ann: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for ann, item, label in observations:
        by_ann[ann].append((item, label))
    out: Dict[str, Dict] = {}
    for ann, items in by_ann.items():
        agree = minority = 0
        for item, label in items:
            s = softs.get(item)
            if not s:
                continue
            if label == s.hard_label:
                agree += 1
            else:
                minority += 1
        total = agree + minority
        out[ann] = {"n": total,
                    "majority_rate": round(agree / total, 4) if total else None,
                    "minority_rate": round(minority / total, 4) if total else None}
    return out


def perspectivist_export(observations: List[Observation], ambiguity_threshold: float = 0.5
                         ) -> List[Dict]:
    """JSONL-ready rows preserving the full label distribution per item — the
    soft-label training / disagreement-aware export format."""
    return [s.to_dict() for s in soft_labels(observations, ambiguity_threshold)]
