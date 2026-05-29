"""
Multi-label IAA metrics for schemas where each annotator can select a set of labels
per item (e.g., multiselect, hierarchical_multiselect, card_sort).

Provides MASI distance, Jaccard distance, and pairwise alpha-MASI.
"""

from __future__ import annotations

from typing import Dict, Iterable, Sequence

from potato.server_utils.iaa.alpha import krippendorff_alpha, _masi_distance


def jaccard_distance(set_a: Iterable, set_b: Iterable) -> float:
    a = frozenset(set_a)
    b = frozenset(set_b)
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return 1.0 - len(a & b) / len(union)


def masi_distance(set_a: Iterable, set_b: Iterable) -> float:
    return _masi_distance(set_a, set_b)


def mean_jaccard(label_sets_by_user: Dict[str, Sequence[Iterable]]) -> float:
    """Average pairwise (1 - Jaccard distance) across users and items."""
    users = list(label_sets_by_user)
    if len(users) < 2:
        return float("nan")
    sims = []
    for i in range(len(users)):
        a = list(label_sets_by_user[users[i]])
        for j in range(i + 1, len(users)):
            b = list(label_sets_by_user[users[j]])
            m = min(len(a), len(b))
            if m == 0:
                continue
            for k in range(m):
                sims.append(1.0 - jaccard_distance(a[k], b[k]))
    if not sims:
        return float("nan")
    return sum(sims) / len(sims)


def alpha_masi(long_format_sets) -> float:
    """Krippendorff's alpha with MASI distance on multi-label sets."""
    return krippendorff_alpha(long_format_sets, level="masi")
