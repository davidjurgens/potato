"""
The tests and intervals the contracts are built from.

Every function here is pure and vectorizable, so the coverage of each
guarantee can be checked by simulation in the unit tests
(``tests/unit/labeling_engine/test_validity_*.py``).
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np
from scipy import stats as _st


def binom_pvalue_risk_above(k: int, n: int, eps: float) -> float:
    """p-value for H0: error rate > eps, having seen k errors in n.

    Small when k is small enough that an error rate above eps would rarely
    produce it. ``n == 0`` gives 1: no evidence, no rejection.
    """
    if n <= 0:
        return 1.0
    return float(_st.binom.cdf(k, n, eps))


def min_n_for_zero_errors(eps: float, alpha: float) -> int:
    """Fewest accepted labels that could certify at all: (1-eps)^n <= alpha."""
    if eps <= 0:
        return math.inf
    if eps >= 1:
        return 1
    return int(math.ceil(math.log(alpha) / math.log(1.0 - eps)))


def n_needed(p_hat: float, eps: float, alpha: float, cap: int = 1_000_000) -> Optional[int]:
    """Accepted labels needed to certify eps if the true error rate is p_hat.

    The smallest n at which observing round(p_hat * n) errors gives a p-value
    at or below alpha. None when p_hat >= eps: no amount of data certifies a
    labeler that is worse than the target.
    """
    if p_hat >= eps:
        return None
    lo = max(1, min_n_for_zero_errors(eps, alpha))
    if lo == math.inf:
        return None
    n = lo
    while n <= cap:
        if binom_pvalue_risk_above(int(round(p_hat * n)), n, eps) <= alpha:
            return n
        n = int(n * 1.25) + 1
    return None


def clopper_pearson(k: int, n: int, level: float = 0.9) -> Tuple[float, float]:
    """Exact two-sided interval for a binomial proportion."""
    if n <= 0:
        return 0.0, 1.0
    a = 1 - level
    lo = 0.0 if k == 0 else float(_st.beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(_st.beta.ppf(1 - a / 2, k + 1, n - k))
    return lo, hi


def wilson_upper(k: int, n: int, level: float = 0.8) -> float:
    """One-sided Wilson upper bound, used on dev to choose a threshold."""
    if n <= 0:
        return 1.0
    z = float(_st.norm.ppf(level))
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centre + half) / denom)


def look_alpha(delta: float, look: int) -> float:
    """The level spent on the ``look``-th look (1-based) at one cascade.

    delta * 6 / (pi^2 k^2) sums to delta over every possible look, so a study
    that re-certifies after each new batch of labels keeps its overall error
    rate at delta. The first look gets 61% of delta, not half, which is the
    reason for this series over delta / 2^k.
    """
    k = max(1, int(look))
    return delta * 6.0 / (math.pi ** 2 * k * k)


def normal_ci(est: float, se: float, level: float) -> Tuple[float, float]:
    z = float(_st.norm.ppf(1 - (1 - level) / 2))
    return est - z * se, est + z * se
