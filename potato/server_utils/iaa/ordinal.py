"""
Ordinal IAA metrics: weighted kappa (linear + quadratic), Spearman's rho.
"""

from __future__ import annotations

from typing import Sequence

import logging

logger = logging.getLogger(__name__)


def _coerce_ordinal(values: Sequence) -> list:
    """Try to coerce a sequence of (str|int|float) ratings into numeric ranks."""
    coerced = []
    for v in values:
        if isinstance(v, (int, float)):
            coerced.append(float(v))
        else:
            try:
                coerced.append(float(v))
            except (TypeError, ValueError):
                # Fall back to lexical ordering by stable string sort
                coerced.append(str(v))
    if any(isinstance(c, str) for c in coerced):
        rank = {c: i for i, c in enumerate(sorted(set(coerced)))}
        return [rank[c] for c in coerced]
    return coerced


def weighted_kappa(labels_a: Sequence, labels_b: Sequence, weights: str = "quadratic") -> float:
    """
    Cohen's weighted kappa for ordinal categories.

    weights: 'linear' or 'quadratic' (CKD convention).
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if not labels_a:
        return float("nan")
    try:
        from sklearn.metrics import cohen_kappa_score
        a = _coerce_ordinal(labels_a)
        b = _coerce_ordinal(labels_b)
        return float(cohen_kappa_score(a, b, weights=weights))
    except ImportError:  # pragma: no cover
        logger.warning("sklearn unavailable; weighted_kappa returning NaN")
        return float("nan")


def spearman_rho(labels_a: Sequence, labels_b: Sequence) -> float:
    """Spearman rank correlation between two annotators."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if len(labels_a) < 2:
        return float("nan")
    try:
        from scipy.stats import spearmanr
        a = _coerce_ordinal(labels_a)
        b = _coerce_ordinal(labels_b)
        rho, _ = spearmanr(a, b)
        return float(rho) if rho == rho else float("nan")  # NaN-safe
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; spearman_rho returning NaN")
        return float("nan")
