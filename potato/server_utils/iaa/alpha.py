"""
Krippendorff's alpha wrapper.

Delegates to ``simpledorff`` (already a project dependency). Supports nominal,
ordinal, interval, ratio, and MASI distance metrics. Accepts long-format data:
a list of (annotator, item, label) triples.

When ``simpledorff`` is unavailable, falls back to NaN with a logged warning.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple, Union

import logging

logger = logging.getLogger(__name__)


def _nominal_distance(a, b) -> float:
    return 0.0 if a == b else 1.0


def _ordinal_distance(a, b) -> float:
    try:
        return abs(float(a) - float(b))
    except (TypeError, ValueError):
        return 0.0 if a == b else 1.0


def _interval_distance(a, b) -> float:
    try:
        return (float(a) - float(b)) ** 2
    except (TypeError, ValueError):
        return 0.0 if a == b else 1.0


def _ratio_distance(a, b) -> float:
    try:
        a, b = float(a), float(b)
        if a + b == 0:
            return 0.0
        return ((a - b) / (a + b)) ** 2
    except (TypeError, ValueError):
        return 0.0 if a == b else 1.0


def _masi_distance(a, b) -> float:
    """
    MASI distance for multi-label sets. ``a`` and ``b`` are iterables of labels.
    """
    set_a = frozenset(a) if not isinstance(a, frozenset) else a
    set_b = frozenset(b) if not isinstance(b, frozenset) else b
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    jaccard = len(intersection) / len(union)
    if set_a == set_b:
        m = 1.0
    elif set_a < set_b or set_b < set_a:
        m = 2 / 3
    elif intersection and set_a != set_b:
        m = 1 / 3
    else:
        m = 0.0
    return 1.0 - (jaccard * m)


_DISTANCES = {
    "nominal": _nominal_distance,
    "ordinal": _ordinal_distance,
    "interval": _interval_distance,
    "ratio": _ratio_distance,
    "masi": _masi_distance,
}


def krippendorff_alpha(
    long_format: Sequence[Tuple[str, str, Union[str, float, frozenset]]],
    level: str = "nominal",
) -> float:
    """
    Krippendorff's alpha.

    Args:
        long_format: iterable of (annotator_id, item_id, value) tuples.
        level: 'nominal', 'ordinal', 'interval', 'ratio', or 'masi'.

    Returns:
        Alpha as a float, or NaN if undefined.
    """
    if level not in _DISTANCES:
        raise ValueError(f"Unknown level for Krippendorff's alpha: {level!r}")

    try:
        import simpledorff
        import pandas as pd
    except ImportError:  # pragma: no cover
        logger.warning("simpledorff/pandas unavailable; krippendorff_alpha returning NaN")
        return float("nan")

    rows = list(long_format)
    if not rows:
        return float("nan")
    df = pd.DataFrame(rows, columns=["annotator", "item", "value"])
    if df["item"].nunique() < 2 or df["annotator"].nunique() < 2:
        return float("nan")

    dist = _DISTANCES[level]
    try:
        return float(
            simpledorff.calculate_krippendorffs_alpha_for_df(
                df,
                experiment_col="item",
                annotator_col="annotator",
                class_col="value",
                metric_fn=dist,
            )
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("krippendorff_alpha failed: %s", exc)
        return float("nan")
