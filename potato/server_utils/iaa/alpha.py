"""
Krippendorff's alpha wrapper.

Delegates to ``simpledorff`` (already a project dependency). Supports nominal,
ordinal, interval, ratio, and MASI distance metrics. Accepts long-format data:
a list of (annotator, item, label) triples.

When ``simpledorff`` is unavailable, falls back to NaN with a logged warning.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, Sequence, Tuple, Union

import logging

logger = logging.getLogger(__name__)


def _nominal_distance(a, b) -> float:
    return 0.0 if a == b else 1.0


def _ordinal_distance_for(rows) -> Callable[[Any, Any], float]:
    """
    Krippendorff's ordinal metric, which depends on the data and not only on
    the pair: for ranked values c <= k,

        delta^2(c, k) = (sum_{g=c..k} n_g - (n_c + n_k) / 2) ** 2

    where n_g is how often value g occurs among pairable units (units with two
    or more values). A step across a crowded part of the scale costs more than
    the same step across a rarely used part. ``abs(a - b)`` used to stand in
    for it, which is neither this nor the interval metric.

    Values must be numbers (or numeric strings), because rank order is all the
    metric uses and labels have none of their own; the dispatcher maps a
    scheme's labels to their declared ranks before it gets here. Anything else
    falls back to the nominal metric with a warning.
    """
    by_item: Dict[Any, list] = defaultdict(list)
    for _annotator, item, value in rows:
        by_item[item].append(value)
    # Every value gets a rank; only pairable units add to its count.
    counts: Dict[Any, int] = {}
    for values in by_item.values():
        for value in values:
            counts[value] = counts.get(value, 0) + (len(values) >= 2)
    try:
        ranked = sorted(counts, key=float)
    except (TypeError, ValueError):
        logger.warning("ordinal alpha needs numeric values; got %r -- using "
                       "the nominal metric", sorted(map(str, counts))[:5])
        return _nominal_distance

    position = {value: i for i, value in enumerate(ranked)}
    prefix = [0]
    for value in ranked:
        prefix.append(prefix[-1] + counts[value])

    def distance(a, b) -> float:
        c, k = sorted((position[a], position[b]))
        if c == k:
            return 0.0
        n_c, n_k = counts[ranked[c]], counts[ranked[k]]
        return (prefix[k + 1] - prefix[c] - (n_c + n_k) / 2.0) ** 2

    return distance


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
    "interval": _interval_distance,
    "ratio": _ratio_distance,
    "masi": _masi_distance,
}


def krippendorff_alpha(
    long_format: Sequence[Tuple[str, str, Union[str, float, frozenset]]],
    level: Union[str, Callable[[Any, Any], float]] = "nominal",
) -> float:
    """
    Krippendorff's alpha.

    Args:
        long_format: iterable of (annotator_id, item_id, value) tuples.
        level: 'nominal', 'ordinal', 'interval', 'ratio', 'masi', **or a
            callable** ``(a, b) -> float`` giving the distance between two
            values, 0 meaning identical.

    Accepting a callable is what lets alpha run over geometry without any new
    coefficient code: simpledorff already receives ``metric_fn``, and only the
    named lookup was closed. Values must still be HASHABLE, because a
    coincidence matrix is built over distinct values -- so geometry is passed
    as opaque handles and the callable resolves handle -> shape.

    Returns:
        Alpha as a float, or NaN if undefined.
    """
    rows = list(long_format)
    if callable(level):
        dist = level
    elif level == "ordinal":
        dist = _ordinal_distance_for(rows)
    elif level in _DISTANCES:
        dist = _DISTANCES[level]
    else:
        raise ValueError(f"Unknown level for Krippendorff's alpha: {level!r}")

    try:
        import simpledorff
        import pandas as pd
    except ImportError:  # pragma: no cover
        logger.warning("simpledorff/pandas unavailable; krippendorff_alpha returning NaN")
        return float("nan")

    if not rows:
        return float("nan")
    df = pd.DataFrame(rows, columns=["annotator", "item", "value"])
    if df["item"].nunique() < 2 or df["annotator"].nunique() < 2:
        return float("nan")

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
