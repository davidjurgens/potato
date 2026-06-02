"""
Continuous IAA metrics: Pearson r, MAE, RMSE, intra-class correlation (ICC).

ICC implementation follows Shrout & Fleiss (1979). We expose:
    icc_2_1 — single-rater ICC(2,1) (two-way random, agreement, single measure)
    icc_2_k — average-rater ICC(2,k) (two-way random, agreement, average measure)
"""

from __future__ import annotations

from math import isnan, sqrt
from typing import Sequence

import logging

logger = logging.getLogger(__name__)


def _to_float(seq: Sequence) -> list:
    out = []
    for v in seq:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def pearson_r(values_a: Sequence, values_b: Sequence) -> float:
    a = _to_float(values_a)
    b = _to_float(values_b)
    pairs = [(x, y) for x, y in zip(a, b) if not (isnan(x) or isnan(y))]
    if len(pairs) < 2:
        return float("nan")
    try:
        from scipy.stats import pearsonr
        r, _ = pearsonr([x for x, _ in pairs], [y for _, y in pairs])
        return float(r) if not isnan(r) else float("nan")
    except ImportError:  # pragma: no cover
        pass
    n = len(pairs)
    sa = sum(x for x, _ in pairs)
    sb = sum(y for _, y in pairs)
    sab = sum(x * y for x, y in pairs)
    saa = sum(x * x for x, _ in pairs)
    sbb = sum(y * y for _, y in pairs)
    num = n * sab - sa * sb
    den = sqrt((n * saa - sa * sa) * (n * sbb - sb * sb))
    if den == 0:
        return float("nan")
    return num / den


def mae(values_a: Sequence, values_b: Sequence) -> float:
    a = _to_float(values_a)
    b = _to_float(values_b)
    pairs = [(x, y) for x, y in zip(a, b) if not (isnan(x) or isnan(y))]
    if not pairs:
        return float("nan")
    return sum(abs(x - y) for x, y in pairs) / len(pairs)


def rmse(values_a: Sequence, values_b: Sequence) -> float:
    a = _to_float(values_a)
    b = _to_float(values_b)
    pairs = [(x, y) for x, y in zip(a, b) if not (isnan(x) or isnan(y))]
    if not pairs:
        return float("nan")
    return sqrt(sum((x - y) ** 2 for x, y in pairs) / len(pairs))


def _icc_components(matrix):
    """Mean squares for a two-way ANOVA: MSR (rows/items), MSC (cols/raters), MSE."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 2:
        return None
    if np.isnan(arr).any():
        # listwise deletion of items with any missing rating
        arr = arr[~np.isnan(arr).any(axis=1)]
        if arr.shape[0] < 2:
            return None
    n, k = arr.shape
    grand = arr.mean()
    row_means = arr.mean(axis=1)
    col_means = arr.mean(axis=0)
    ss_total = ((arr - grand) ** 2).sum()
    ss_rows = k * ((row_means - grand) ** 2).sum()
    ss_cols = n * ((col_means - grand) ** 2).sum()
    ss_err = ss_total - ss_rows - ss_cols
    df_rows = n - 1
    df_cols = k - 1
    df_err = (n - 1) * (k - 1)
    if df_err <= 0:
        return None
    msr = ss_rows / df_rows
    msc = ss_cols / df_cols
    mse = ss_err / df_err
    return msr, msc, mse, n, k


def icc_2_1(matrix) -> float:
    """ICC(2,1): two-way random effects, single rater, absolute agreement."""
    comps = _icc_components(matrix)
    if comps is None:
        return float("nan")
    msr, msc, mse, n, k = comps
    denom = msr + (k - 1) * mse + k * (msc - mse) / n
    if denom == 0:
        return float("nan")
    return (msr - mse) / denom


def icc_2_k(matrix) -> float:
    """ICC(2,k): two-way random effects, average of k raters, absolute agreement."""
    comps = _icc_components(matrix)
    if comps is None:
        return float("nan")
    msr, msc, mse, n, k = comps
    denom = msr + (msc - mse) / n
    if denom == 0:
        return float("nan")
    return (msr - mse) / denom
