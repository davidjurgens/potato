"""
Nominal IAA metrics: percent agreement, Cohen's kappa, Fleiss' kappa.

Inputs are lists keyed by item: for two-annotator metrics, two equal-length
label lists; for multi-annotator metrics, a list of (annotator_id -> label) dicts.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from math import isclose
from typing import Any, Dict, List, Mapping, Sequence

import logging
import warnings

logger = logging.getLogger(__name__)


def percent_agreement(labels_a: Sequence, labels_b: Sequence) -> float:
    """Fraction of items on which two annotators agree."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if not labels_a:
        return float("nan")
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    return agree / len(labels_a)


def cohen_kappa(labels_a: Sequence, labels_b: Sequence) -> float:
    """
    Cohen's kappa for two annotators on nominal categories.

    Uses sklearn if available (handles ties and edge cases well); falls back
    to a direct implementation otherwise.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if not labels_a:
        return float("nan")
    try:
        from sklearn.metrics import cohen_kappa_score
        # One label throughout makes chance agreement 1 and kappa 0/0;
        # sklearn returns NaN for it and warns, and NaN is the answer.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return float(cohen_kappa_score(list(labels_a), list(labels_b)))
    except ImportError:  # pragma: no cover
        pass

    n = len(labels_a)
    po = percent_agreement(labels_a, labels_b)
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    pe = sum(counts_a[c] * counts_b[c] for c in set(counts_a) | set(counts_b)) / (n * n)
    if isclose(pe, 1.0):
        return float("nan")  # chance agreement 1: undefined, not perfect
    return (po - pe) / (1 - pe)


def fleiss_kappa(per_item_label_counts: List[Dict[str, int]]) -> float:
    """
    Fleiss' kappa for >=2 annotators on nominal categories.

    Args:
        per_item_label_counts: one dict per item mapping label -> number of
            annotators who chose it. Items may have different numbers of
            annotators; items with fewer than 2 are skipped.

    Returns:
        Fleiss' kappa as a float, or NaN if undefined.
    """
    # Use only items rated by at least 2 annotators.
    rated = [d for d in per_item_label_counts if sum(d.values()) >= 2]
    if not rated:
        return float("nan")

    # Items may have different numbers of raters. Each item's agreement is
    # over its own pairs, and the marginals pool every rating. With equal N
    # this is Fleiss' formula exactly. Keeping only the items whose N was the
    # statistics.mode used to drop the rest, and on a tied mode the input
    # order decided which half survived: -0.333 one way, 0.250 reversed.
    categories = sorted({c for d in rated for c in d})
    if not categories:
        return float("nan")
    p_is = []
    for d in rated:
        n_i = sum(d.values())
        p_is.append(sum(v * (v - 1) for v in d.values()) / (n_i * (n_i - 1)))
    p_bar = sum(p_is) / len(rated)
    total = sum(sum(d.values()) for d in rated)
    p_js = [sum(d.get(c, 0) for d in rated) / total for c in categories]
    p_e = sum(p * p for p in p_js)
    if isclose(p_e, 1.0):
        # Every rating is one label, so chance agreement is 1 and kappa is
        # 0/0. Undefined, not perfect: mean_pairwise_agreement carries the
        # raw 1.0, and the dispatcher attaches a note saying why.
        return float("nan")
    return (p_bar - p_e) / (1 - p_e)


def pairwise_cohen_kappa(annotations_by_user: Dict[str, Sequence]) -> float:
    """
    Mean Cohen's kappa across every distinct pair of annotators.

    annotations_by_user maps user_id -> aligned label sequence (same length per user).
    Users contributing fewer than the maximum length are restricted to their
    overlap with each partner.
    """
    users = list(annotations_by_user)
    if len(users) < 2:
        return float("nan")
    kappas = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            a = list(annotations_by_user[users[i]])
            b = list(annotations_by_user[users[j]])
            m = min(len(a), len(b))
            if m == 0:
                continue
            try:
                kappas.append(cohen_kappa(a[:m], b[:m]))
            except ValueError:
                continue
    if not kappas:
        return float("nan")
    return sum(kappas) / len(kappas)


def mean_pairwise_agreement(items: Sequence[Mapping[str, Any]]) -> float:
    """
    Observed agreement over items rated by different subsets of annotators.

    ``items`` holds one ``{annotator: label}`` mapping per item. Each item with
    two or more annotators contributes the fraction of its annotator pairs that
    chose the same label, and the result is the mean over those items. That is
    Fleiss' P-bar, so it sits beside ``fleiss_kappa`` as the raw number the
    coefficient corrects, and it stays defined where the coefficient is 0/0.
    """
    per_item = []
    for labels in items:
        values = list(labels.values())
        if len(values) < 2:
            continue
        pairs = list(combinations(values, 2))
        per_item.append(sum(1 for a, b in pairs if a == b) / len(pairs))
    if not per_item:
        return float("nan")
    return sum(per_item) / len(per_item)


def mean_cohen_kappa_over_shared_items(items: Sequence[Mapping[str, Any]]) -> float:
    """
    Mean Cohen's kappa across annotator pairs, each on the items that pair shares.

    ``pairwise_cohen_kappa`` takes sequences already aligned across everyone,
    which means only the items *every* annotator rated. Under heterogeneous
    coverage that set is often empty, and the coefficient came back NaN for
    studies where every pair had overlapping items. Here each pair is scored on
    its own overlap, so full coverage gives the same number as before and
    partial coverage gives one at all.

    Pairs whose kappa is undefined (no shared item, or one label throughout so
    chance agreement is 1) are left out of the mean rather than poisoning it.
    """
    annotators = sorted({u for labels in items for u in labels})
    kappas = []
    for a, b in combinations(annotators, 2):
        shared = [labels for labels in items if a in labels and b in labels]
        if not shared:
            continue
        try:
            # sklearn warns on a single-label pair, which is exactly the
            # undefined case skipped below; unsilenced it fires once per pair.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                value = cohen_kappa([l[a] for l in shared],
                                    [l[b] for l in shared])
        except ValueError:
            continue
        if value == value:
            kappas.append(value)
    if not kappas:
        return float("nan")
    return sum(kappas) / len(kappas)
