"""
Ranking IAA metrics for schemas where each annotator produces an ordering
(e.g., ranking, best-worst scaling, pairwise).
"""

from __future__ import annotations

from typing import Sequence

import logging

logger = logging.getLogger(__name__)


def _shared_positions(ranking_a: Sequence, ranking_b: Sequence):
    """Positions in each ranking of the items both rankings contain, in the
    order of ``ranking_a``.

    A ranking here is an ordered list of item ids, best first. Correlating the
    lists directly paired a[i] with b[i] and compared the item NAMES, so
    renaming an item changed the coefficient: ABCED vs ABDEC read 0.80 where
    the rank correlation is 0.40.
    """
    pos_b = {item: i for i, item in enumerate(ranking_b)}
    shared = [item for item in dict.fromkeys(ranking_a) if item in pos_b]
    # Re-rank within the shared items, so a missing item shifts nobody.
    order_b = sorted(shared, key=pos_b.__getitem__)
    rank_b = {item: i for i, item in enumerate(order_b)}
    return list(range(len(shared))), [rank_b[item] for item in shared]


def kendall_tau(ranking_a: Sequence, ranking_b: Sequence) -> float:
    """Kendall's tau between two rankings (ordered lists of item ids), over
    the items both contain."""
    pos_a, pos_b = _shared_positions(ranking_a, ranking_b)
    if len(pos_a) < 2:
        return float("nan")
    try:
        from scipy.stats import kendalltau
        tau, _ = kendalltau(pos_a, pos_b)
        return float(tau) if tau == tau else float("nan")
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; kendall_tau returning NaN")
        return float("nan")


def spearman_footrule(ranking_a: Sequence, ranking_b: Sequence) -> float:
    """
    Normalized Spearman footrule distance over the items both rankings
    contain. 0 = identical, 1 = maximally disagree.

    Missing items used to be placed at rank n, which could push the distance
    past its worst case: ``(["x"], ["y"])`` scored 2.0.
    """
    pos_a, pos_b = _shared_positions(ranking_a, ranking_b)
    n = len(pos_a)
    if n < 2:
        return float("nan")
    total = sum(abs(a - b) for a, b in zip(pos_a, pos_b))
    # Worst-case footrule for n items is floor(n^2 / 2)
    return total / ((n * n) // 2)
