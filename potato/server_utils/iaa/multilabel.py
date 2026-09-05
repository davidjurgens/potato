"""
Multi-label IAA metrics for schemas where each annotator can select a set of labels
per item (e.g., multiselect, hierarchical_multiselect, card_sort).

Provides MASI distance, Jaccard distance, and pairwise alpha-MASI.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Sequence

from potato.server_utils.iaa.alpha import krippendorff_alpha, _masi_distance

logger = logging.getLogger(__name__)


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


def mean_jaccard(label_sets_by_user) -> float:
    """Average pairwise (1 - Jaccard distance) across users and items.

    Accepts either shape:

        {user: {item_id: label_set}}   pairs by item -- always correct
        {user: [label_set, ...]}       pairs by position

    Pass the mapping. The positional form pairs `a[k]` against `b[k]`, which is
    only right while every user answered every item in the same order: one
    missing answer shortens that user's list and every index after it compares
    two DIFFERENT items. On eight items where two raters each skipped one, and
    every answer given was identical, this returned 0.6 -- below anything the
    data could produce -- beside an `alpha_masi` of 1.0 on the same input.
    `alpha_masi` was right because it receives (user, item, value) triples and
    aligns on the item.

    Only items a pair of users BOTH answered are compared, which is what a
    pairwise agreement figure means.
    """
    users = list(label_sets_by_user)
    if len(users) < 2:
        return float("nan")

    by_item = all(isinstance(label_sets_by_user[u], dict) for u in users)
    if not by_item:
        lengths = {len(list(label_sets_by_user[u])) for u in users}
        if len(lengths) > 1:
            logger.warning(
                "mean_jaccard got per-user sequences of differing lengths %s, "
                "so it is comparing different items to each other. Pass "
                "{user: {item_id: labels}} instead.", sorted(lengths))

    sims = []
    for i in range(len(users)):
        a = label_sets_by_user[users[i]]
        for j in range(i + 1, len(users)):
            b = label_sets_by_user[users[j]]
            if by_item:
                for iid in a.keys() & b.keys():
                    sims.append(1.0 - jaccard_distance(a[iid], b[iid]))
            else:
                a_list, b_list = list(a), list(b)
                for k in range(min(len(a_list), len(b_list))):
                    sims.append(1.0 - jaccard_distance(a_list[k], b_list[k]))
    if not sims:
        return float("nan")
    return sum(sims) / len(sims)


def alpha_masi(long_format_sets) -> float:
    """Krippendorff's alpha with MASI distance on multi-label sets."""
    return krippendorff_alpha(long_format_sets, level="masi")
