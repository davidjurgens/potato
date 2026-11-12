"""
Active preference-pair selection for DPO / reward-model labeling.

Naively queuing every response pair for human comparison wastes effort. Active
selection (Active Reward Modeling, ICML 2025) prioritizes the *most informative*
pairs — those the current model is most uncertain about (near a 50/50 win
probability / small quality margin), which is where a human label moves the reward
model most.

Includes an honest **random** baseline: the 2026 "Random Is Hard to Beat" result
warns active selection isn't always worth it, so callers can A/B against random.

Pure stdlib, deterministic given a seed.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional

STRATEGIES = ("uncertainty", "moderate_margin", "random")


def _win_prob(score_a: Optional[float], score_b: Optional[float]) -> Optional[float]:
    """Logistic win probability of A over B from scalar quality scores (Bradley-Terry
    style). None if either score is missing."""
    if score_a is None or score_b is None:
        return None
    return 1.0 / (1.0 + math.exp(-(score_a - score_b)))


def acquisition(candidate: Dict[str, Any], strategy: str = "uncertainty") -> float:
    """Acquisition score in [0,1] (higher = label this pair first).

    candidate may carry ``score_a``/``score_b`` (model quality estimates) or a
    precomputed ``win_prob``. ``uncertainty`` peaks at a 50/50 prediction;
    ``moderate_margin`` peaks at a small score gap; ``random`` is constant.
    """
    if strategy == "random":
        return 0.5
    wp = candidate.get("win_prob")
    if wp is None:
        wp = _win_prob(candidate.get("score_a"), candidate.get("score_b"))
    if strategy == "uncertainty":
        if wp is None:
            return 0.5  # unknown → moderately informative
        return 1.0 - 2.0 * abs(wp - 0.5)        # 1.0 at p=0.5, 0.0 at p∈{0,1}
    if strategy == "moderate_margin":
        a, b = candidate.get("score_a"), candidate.get("score_b")
        if a is None or b is None:
            return 0.5
        return 1.0 / (1.0 + abs(a - b))          # 1.0 at equal scores, →0 as gap grows
    raise ValueError(f"unknown strategy '{strategy}' (use {STRATEGIES})")


def select_pairs(candidates: List[Dict[str, Any]], k: int = 10,
                 strategy: str = "uncertainty", seed: int = 12345) -> List[Dict[str, Any]]:
    """Return the top-``k`` candidate pairs to label next, each annotated with its
    ``acquisition`` score and the ``strategy`` used. ``random`` shuffles deterministically.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}' (use {STRATEGIES})")
    scored = []
    for c in candidates:
        c2 = dict(c)
        c2["acquisition"] = round(acquisition(c, strategy), 4)
        c2["strategy"] = strategy
        scored.append(c2)
    if strategy == "random":
        random.Random(seed).shuffle(scored)
    else:
        # stable sort by acquisition desc; tie-break by a seeded jitter for determinism
        rng = random.Random(seed)
        order = {id(c): rng.random() for c in scored}
        scored.sort(key=lambda c: (c["acquisition"], order[id(c)]), reverse=True)
    return scored[: k if k else len(scored)]


def expected_label_savings(candidates: List[Dict[str, Any]], k: int,
                           strategy: str = "uncertainty") -> Dict[str, Any]:
    """A simple, honest report: mean acquisition of the selected top-k vs the whole
    pool vs a random k. If active ≈ random, the report says so (don't oversell)."""
    if not candidates:
        return {"n": 0}
    sel = select_pairs(candidates, k, strategy)
    rnd = select_pairs(candidates, k, "random")
    mean = lambda rows: round(sum(c["acquisition"] for c in rows) / len(rows), 4) if rows else 0.0
    active_mean = mean(sel)
    pool_mean = round(sum(acquisition(c, strategy) for c in candidates) / len(candidates), 4)
    # random-baseline acquisition under the SAME strategy (not the constant 0.5)
    rnd_mean = mean([{**c, "acquisition": round(acquisition(c, strategy), 4)} for c in rnd])
    return {"n": len(candidates), "k": min(k, len(candidates)), "strategy": strategy,
            "active_mean_acquisition": active_mean, "pool_mean_acquisition": pool_mean,
            "random_mean_acquisition": rnd_mean,
            "active_beats_random": active_mean > rnd_mean + 1e-9}
