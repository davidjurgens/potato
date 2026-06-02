"""
Ranking IAA metrics for schemas where each annotator produces an ordering
(e.g., ranking, best-worst scaling, pairwise).
"""

from __future__ import annotations

from typing import Sequence

import logging

logger = logging.getLogger(__name__)


def kendall_tau(ranking_a: Sequence, ranking_b: Sequence) -> float:
    """Kendall's tau-b between two rankings (lists of comparable items)."""
    if len(ranking_a) != len(ranking_b):
        raise ValueError("rankings must be the same length")
    if len(ranking_a) < 2:
        return float("nan")
    try:
        from scipy.stats import kendalltau
        tau, _ = kendalltau(list(ranking_a), list(ranking_b))
        return float(tau) if tau == tau else float("nan")
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; kendall_tau returning NaN")
        return float("nan")


def spearman_footrule(ranking_a: Sequence, ranking_b: Sequence) -> float:
    """
    Normalized Spearman footrule distance. 0 = identical, 1 = maximally disagree.

    Items are matched by identity; missing items get max-rank.
    """
    items = list({*ranking_a, *ranking_b})
    if len(items) < 2:
        return float("nan")
    n = len(items)
    rank_a = {item: i for i, item in enumerate(ranking_a)}
    rank_b = {item: i for i, item in enumerate(ranking_b)}
    total = sum(abs(rank_a.get(it, n) - rank_b.get(it, n)) for it in items)
    # Worst-case footrule for n items is floor(n^2 / 2)
    worst = (n * n) // 2 if n > 0 else 1
    return total / worst if worst else float("nan")
