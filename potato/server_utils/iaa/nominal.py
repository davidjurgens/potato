"""
Nominal IAA metrics: percent agreement, Cohen's kappa, Fleiss' kappa.

Inputs are lists keyed by item: for two-annotator metrics, two equal-length
label lists; for multi-annotator metrics, a list of (annotator_id -> label) dicts.
"""

from __future__ import annotations

from collections import Counter
from math import isclose
from typing import Dict, List, Sequence

import logging

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
        return float(cohen_kappa_score(list(labels_a), list(labels_b)))
    except ImportError:  # pragma: no cover
        pass

    n = len(labels_a)
    po = percent_agreement(labels_a, labels_b)
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    pe = sum(counts_a[c] * counts_b[c] for c in set(counts_a) | set(counts_b)) / (n * n)
    if isclose(pe, 1.0):
        return 1.0 if isclose(po, 1.0) else 0.0
    return (po - pe) / (1 - pe)


def fleiss_kappa(per_item_label_counts: List[Dict[str, int]]) -> float:
    """
    Fleiss' kappa for >=2 annotators on nominal categories.

    Args:
        per_item_label_counts: one dict per item mapping label -> number of
            annotators who chose it. Each item dict must sum to the same N
            (the number of annotators rating that item). Items where N < 2
            are skipped.

    Returns:
        Fleiss' kappa as a float, or NaN if undefined.
    """
    # Use only items rated by at least 2 annotators.
    rated = [d for d in per_item_label_counts if sum(d.values()) >= 2]
    if not rated:
        return float("nan")

    ns = [sum(d.values()) for d in rated]
    if len(set(ns)) != 1:
        # Variable-N Fleiss' kappa is rare in practice; restrict to majority N.
        from statistics import mode
        majority_n = mode(ns)
        rated = [d for d, n in zip(rated, ns) if n == majority_n]
        ns = [majority_n] * len(rated)
        if not rated:
            return float("nan")

    n = ns[0]
    categories = sorted({c for d in rated for c in d})
    if n < 2 or not categories:
        return float("nan")

    n_items = len(rated)
    # Per-item agreement P_i
    p_is = []
    for d in rated:
        total = sum(d.get(c, 0) ** 2 for c in categories)
        p_is.append((total - n) / (n * (n - 1)))
    p_bar = sum(p_is) / n_items
    # Marginal proportions per category
    p_js = []
    for c in categories:
        s = sum(d.get(c, 0) for d in rated)
        p_js.append(s / (n_items * n))
    p_e = sum(p * p for p in p_js)
    if isclose(p_e, 1.0):
        return 1.0 if isclose(p_bar, 1.0) else 0.0
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
