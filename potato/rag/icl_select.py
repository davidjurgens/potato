"""
Per-instance ICL example selection (Phase E).

Pure ranking over already-retrieved candidates — no DB or embedding here, so
it is trivially testable. Implements the three Phase-E requirements:

1. Blend, don't replace, the gain signal: relevance =
   (1-gain_weight)*norm(similarity) + gain_weight*norm(val_accuracy_gain).
   The library is pre-filtered to proven-positive examples, but gain
   magnitude still separates a +0.15 from a +0.02 example.
2. Per-label coverage floor: guarantee up to ``min_per_label`` of each label
   present in the pool before filling the rest, so similarity doesn't
   collapse the demonstrations onto one or two labels.
3. MMR diversification for the remaining slots: balance relevance against
   redundancy with already-selected examples in embedding space.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np


def _norm(values: List[float]) -> Dict[int, float]:
    lo, hi = min(values), max(values)
    if hi <= lo:
        return {i: 0.0 for i in range(len(values))}
    return {i: (v - lo) / (hi - lo) for i, v in enumerate(values)}


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(a @ b) / (na * nb)


def select(
    candidates: List[Dict[str, Any]], *, max_total: int,
    min_per_label: int = 1, gain_weight: float = 0.5,
    mmr_lambda: float = 0.7,
) -> List[Dict[str, Any]]:
    """Rank + diversify candidates. Each candidate is a dict with at least
    ``label``, ``similarity`` (cosine to the instance), ``gain``
    (val_accuracy_gain), and ``vector`` (np.ndarray). Returns the chosen
    subset (each annotated with ``_rel``), best first."""
    if not candidates or max_total <= 0:
        return []

    sim_n = _norm([c.get("similarity", 0.0) for c in candidates])
    gain_n = _norm([float(c.get("gain", 0.0) or 0.0) for c in candidates])
    for i, c in enumerate(candidates):
        c["_rel"] = ((1.0 - gain_weight) * sim_n[i]
                     + gain_weight * gain_n[i])

    by_rel = sorted(candidates, key=lambda c: c["_rel"], reverse=True)

    # (2) Per-label coverage floor: top-relevance examples per label first.
    selected: List[Dict[str, Any]] = []
    per_label: Dict[Any, int] = {}
    if min_per_label > 0:
        for c in by_rel:
            if len(selected) >= max_total:
                break
            lbl = c.get("label")
            if per_label.get(lbl, 0) < min_per_label:
                selected.append(c)
                per_label[lbl] = per_label.get(lbl, 0) + 1

    # (3) MMR fill for the remaining slots.
    chosen_ids = {id(c) for c in selected}
    remaining = [c for c in by_rel if id(c) not in chosen_ids]
    while remaining and len(selected) < max_total:
        best, best_score = None, None
        for c in remaining:
            div = max((_cos(np.asarray(c["vector"]), np.asarray(s["vector"]))
                       for s in selected), default=0.0)
            mmr = mmr_lambda * c["_rel"] - (1.0 - mmr_lambda) * div
            if best_score is None or mmr > best_score:
                best, best_score = c, mmr
        selected.append(best)
        remaining.remove(best)

    return selected[:max_total]
