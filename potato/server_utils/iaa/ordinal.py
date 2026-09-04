"""
Ordinal IAA metrics: weighted kappa (linear + quadratic), Spearman's rho.
"""

from __future__ import annotations

from typing import Optional, Sequence

import logging

logger = logging.getLogger(__name__)


def _coerce_ordinal(values: Sequence, rank: Optional[dict] = None) -> list:
    """Coerce (str|int|float) ratings into numeric ranks.

    ``rank`` maps label name -> position. Pass one whenever the caller knows
    the scale, because the fallback -- sorting the label names -- is only right
    when the names happen to sort into their own order. On the common
    ``[Low, Medium, High]`` it gives High < Low < Medium, so a one-step
    disagreement is scored as a two-step one and the coefficient is wrong
    rather than imprecise: measured on four items, alpha_ordinal read 0.33
    lexically against 0.53 with the declared order.
    """
    coerced = []
    for v in values:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            coerced.append(float(v))
        else:
            try:
                coerced.append(float(v))
            except (TypeError, ValueError):
                coerced.append(str(v))
    if any(isinstance(c, str) for c in coerced):
        if rank is None:
            rank = _lexical_rank(coerced)
        # A label the scale does not name still needs a position; put it after
        # the declared ones rather than dropping the item silently.
        overflow = len(rank)
        out = []
        for c in coerced:
            if isinstance(c, str):
                if c not in rank:
                    rank[c] = overflow
                    overflow += 1
                out.append(rank[c])
            else:
                out.append(c)
        return out
    return coerced


def _lexical_rank(values: Sequence) -> dict:
    return {c: i for i, c in enumerate(sorted({v for v in values
                                               if isinstance(v, str)}))}


def _shared_rank(labels_a: Sequence, labels_b: Sequence,
                 ordering: Optional[dict]) -> Optional[dict]:
    """One rank map for both annotators.

    ``_coerce_ordinal`` used to be called on each sequence independently, so
    two annotators who used different subsets of the scale were ranked against
    different maps: an annotator who only ever said "High" or "Low" had "High"
    at 0, while one who also used "Medium" had it at 0 as well but "Low" at 1
    instead of 1 -- the maps agree only by luck, and where they disagree the
    kappa is not a comparison of the same quantity. Build the map once, over
    both sequences, so the two are on one scale.
    """
    if ordering is not None:
        return dict(ordering)
    combined = list(labels_a) + list(labels_b)
    if not any(isinstance(v, str) and not _is_number(v) for v in combined):
        return None
    return _lexical_rank([str(v) for v in combined if not _is_number(v)])


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def weighted_kappa(labels_a: Sequence, labels_b: Sequence,
                   weights: str = "quadratic",
                   ordering: Optional[dict] = None) -> float:
    """
    Cohen's weighted kappa for ordinal categories.

    weights: 'linear' or 'quadratic' (CKD convention).
    ordering: label -> rank, when the caller knows the scale. See
        ``_coerce_ordinal``.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if not labels_a:
        return float("nan")
    try:
        from sklearn.metrics import cohen_kappa_score
        rank = _shared_rank(labels_a, labels_b, ordering)
        a = _coerce_ordinal(labels_a, rank)
        b = _coerce_ordinal(labels_b, rank)
        return float(cohen_kappa_score(a, b, weights=weights))
    except ImportError:  # pragma: no cover
        logger.warning("sklearn unavailable; weighted_kappa returning NaN")
        return float("nan")


def spearman_rho(labels_a: Sequence, labels_b: Sequence,
                 ordering: Optional[dict] = None) -> float:
    """Spearman rank correlation between two annotators."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    if len(labels_a) < 2:
        return float("nan")
    try:
        from scipy.stats import spearmanr
        rank = _shared_rank(labels_a, labels_b, ordering)
        a = _coerce_ordinal(labels_a, rank)
        b = _coerce_ordinal(labels_b, rank)
        rho, _ = spearmanr(a, b)
        return float(rho) if rho == rho else float("nan")  # NaN-safe
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; spearman_rho returning NaN")
        return float("nan")
