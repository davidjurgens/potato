"""
Calibration metrics: reliability bins, ECE and Brier score.

One implementation for the whole package. ``server_utils/judge_bias.py`` and
``judge_calibration/metrics.py`` each computed ECE their own way; they now
call this, so a judge's ECE on the bias report and on the engine dashboard
cannot disagree.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np


def reliability_bins(confidences: Sequence[float], correct: Sequence[bool],
                     n_bins: int = 10) -> List[Dict[str, float]]:
    """Equal-width bins over [0, 1]: count, mean confidence, accuracy.

    Empty bins are omitted rather than reported as accuracy 0, which a chart
    would draw as a model that is always wrong in that range.
    """
    conf = np.clip(np.asarray(confidences, dtype=float), 0.0, 1.0)
    corr = np.asarray(correct, dtype=float)
    if conf.size == 0:
        return []
    # The top edge belongs to the last bin, so a confidence of exactly 1.0
    # is counted rather than falling off the end.
    idx = np.minimum((conf * n_bins).astype(int), n_bins - 1)
    out = []
    for b in range(n_bins):
        mask = idx == b
        n = int(mask.sum())
        if not n:
            continue
        out.append({"lo": b / n_bins, "hi": (b + 1) / n_bins, "n": n,
                    "confidence": float(conf[mask].mean()),
                    "accuracy": float(corr[mask].mean())})
    return out


def expected_calibration_error(confidences: Sequence[float], correct: Sequence[bool],
                               n_bins: int = 10) -> Optional[float]:
    """Sum over bins of (bin share) x |accuracy - mean confidence|."""
    bins = reliability_bins(confidences, correct, n_bins)
    total = sum(b["n"] for b in bins)
    if not total:
        return None
    return float(sum(b["n"] / total * abs(b["accuracy"] - b["confidence"]) for b in bins))


def brier_score(confidences: Sequence[float], correct: Sequence[bool]) -> Optional[float]:
    conf = np.asarray(confidences, dtype=float)
    if conf.size == 0:
        return None
    return float(np.mean((conf - np.asarray(correct, dtype=float)) ** 2))


def ece_bootstrap_ci(confidences: Sequence[float], correct: Sequence[bool],
                     n_bins: int = 10, n_boot: int = 500, level: float = 0.9,
                     seed: int = 0):
    """Percentile bootstrap interval for ECE, or None below 10 points."""
    conf = np.asarray(confidences, dtype=float)
    corr = np.asarray(correct, dtype=float)
    if conf.size < 10:
        return None
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n_boot):
        ix = rng.integers(0, conf.size, conf.size)
        stats.append(expected_calibration_error(conf[ix], corr[ix], n_bins))
    lo, hi = np.quantile(stats, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)
