"""
Statistical rigor for evaluation results.

Adds error bars and significance testing so an experiment delta, a win-rate, or a
human-agreement score is reported with uncertainty — not as a bare point estimate
that invites over-reading noise. Pure Python (uses only the stdlib), deterministic
(seeded resampling), so it runs anywhere the evaluators run (CI included).

- ``bootstrap_ci``     — percentile bootstrap confidence interval for a mean.
- ``wilson_ci``        — Wilson score interval for a proportion (win/success rate).
- ``paired_bootstrap`` — is system A reliably better than B? Paired by example,
  returns the mean difference, its CI, and a two-sided bootstrap p-value.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

Number = float


def _clean(values: Sequence[Optional[float]]) -> List[float]:
    return [float(v) for v in values if v is not None and not _isnan(v)]


def _isnan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


def mean(values: Sequence[Optional[float]]) -> Optional[float]:
    xs = _clean(values)
    return sum(xs) / len(xs) if xs else None


def bootstrap_ci(values: Sequence[Optional[float]], confidence: float = 0.95,
                 n_resamples: int = 2000, seed: int = 12345) -> Dict[str, Optional[float]]:
    """Percentile bootstrap CI for the mean of ``values``.

    Returns ``{mean, lo, hi, n}``. With <2 values the interval collapses to the
    point estimate (lo==hi==mean). Deterministic given ``seed``.
    """
    xs = _clean(values)
    n = len(xs)
    if n == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    m = sum(xs) / n
    if n == 1:
        return {"mean": round(m, 6), "lo": round(m, 6), "hi": round(m, 6), "n": 1}
    rng = random.Random(seed)
    means = []
    for _ in range(n_resamples):
        resample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = means[max(0, int(math.floor(alpha * n_resamples)))]
    hi = means[min(n_resamples - 1, int(math.ceil((1.0 - alpha) * n_resamples)) - 1)]
    return {"mean": round(m, 6), "lo": round(lo, 6), "hi": round(hi, 6), "n": n}


def wilson_ci(successes: int, total: int, confidence: float = 0.95) -> Dict[str, Optional[float]]:
    """Wilson score interval for a binomial proportion (e.g. a win-rate).

    Far better than the normal approximation for small ``total`` or extreme
    rates. Returns ``{rate, lo, hi, n}``.
    """
    if total <= 0:
        return {"rate": None, "lo": None, "hi": None, "n": 0}
    z = _z_for(confidence)
    p = successes / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)) / denom
    return {"rate": round(p, 6), "lo": round(max(0.0, center - margin), 6),
            "hi": round(min(1.0, center + margin), 6), "n": total}


def paired_bootstrap(a: Sequence[Optional[float]], b: Sequence[Optional[float]],
                     confidence: float = 0.95, n_resamples: int = 2000,
                     seed: int = 12345) -> Dict[str, Optional[float]]:
    """Paired bootstrap comparing system A vs B on the SAME examples.

    ``a[i]`` and ``b[i]`` are the two systems' scores on example ``i`` (pairs
    where either is missing are dropped). Returns ``{mean_diff, lo, hi, p_value,
    significant, n}`` where ``mean_diff = mean(a) - mean(b)``; ``significant`` is
    True when the CI excludes 0.
    """
    pairs = [(float(x), float(y)) for x, y in zip(a, b)
             if x is not None and y is not None and not _isnan(x) and not _isnan(y)]
    n = len(pairs)
    if n == 0:
        return {"mean_diff": None, "lo": None, "hi": None, "p_value": None,
                "significant": False, "n": 0}
    diffs = [x - y for x, y in pairs]
    md = sum(diffs) / n
    if n == 1:
        return {"mean_diff": round(md, 6), "lo": round(md, 6), "hi": round(md, 6),
                "p_value": None, "significant": False, "n": 1}
    rng = random.Random(seed)
    boot = []
    for _ in range(n_resamples):
        s = sum(diffs[rng.randrange(n)] for _ in range(n)) / n
        boot.append(s)
    boot.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = boot[max(0, int(math.floor(alpha * n_resamples)))]
    hi = boot[min(n_resamples - 1, int(math.ceil((1.0 - alpha) * n_resamples)) - 1)]
    # Two-sided bootstrap p-value: fraction of resamples on the opposite side of 0.
    if md >= 0:
        p = 2.0 * (sum(1 for v in boot if v <= 0) / n_resamples)
    else:
        p = 2.0 * (sum(1 for v in boot if v >= 0) / n_resamples)
    p = min(1.0, p)
    return {"mean_diff": round(md, 6), "lo": round(lo, 6), "hi": round(hi, 6),
            "p_value": round(p, 4), "significant": (lo > 0 or hi < 0), "n": n}


def _z_for(confidence: float) -> float:
    """Two-sided normal critical value for common confidence levels."""
    table = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.98: 2.3263, 0.99: 2.5758}
    if confidence in table:
        return table[confidence]
    # Acklam's inverse-normal approximation for arbitrary levels.
    return _inv_norm(1.0 - (1.0 - confidence) / 2.0)


def _inv_norm(p: float) -> float:
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= phigh:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


# ----- experiment-level helpers -----

def experiment_metric_cis(experiment, confidence: float = 0.95) -> Dict[str, Dict]:
    """Per-metric bootstrap CI for one experiment, from its per-example scores."""
    by_metric: Dict[str, List[float]] = {}
    for r in experiment.results:
        for k, v in (r.scores or {}).items():
            if v is not None:
                by_metric.setdefault(k, []).append(v)
    return {k: bootstrap_ci(vals, confidence=confidence) for k, vals in by_metric.items()}


def compare_experiments_metric(exp_a, exp_b, metric: str,
                               confidence: float = 0.95) -> Dict[str, Optional[float]]:
    """Paired A-vs-B comparison for one metric, aligned by ``example_id``."""
    a_scores = {r.example_id: (r.scores or {}).get(metric) for r in exp_a.results}
    b_scores = {r.example_id: (r.scores or {}).get(metric) for r in exp_b.results}
    shared = [eid for eid in a_scores if eid in b_scores]
    a = [a_scores[eid] for eid in shared]
    b = [b_scores[eid] for eid in shared]
    return paired_bootstrap(a, b, confidence=confidence)
