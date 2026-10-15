"""
Watching accepted labels for drift, with a test you can look at every day.

Once a rule is certified, the machine's accepted labels keep coming, and the
data can move under them: new topics, a new product line, a model behind an
API quietly updated. A fixed share of newly accepted labels (``audit_rate``)
goes back to a person, blind. Each audit is a 0/1 outcome: was the accepted
label wrong?

Checking a running error rate after every audit with an ordinary interval
would raise a false alarm sooner or later by chance alone. The engine uses an
anytime-valid confidence sequence instead: the predictable plug-in empirical
Bernstein sequence of Waudby-Smith and Ramdas ("Estimating means of bounded
random variables by betting", JRSS-B 2024, Theorem 2). With probability
1 - alpha it contains the true error rate at every audit simultaneously, so it
can be checked as often as anyone likes.

When its lower end rises above the contract's ``error``, the error rate is
above target with that confidence. With ``features.drift`` on, the engine
then stops accepting machine labels for the scheme, moves the ones it
accepted to ``pending_recert``, and the planner draws fresh calibration
labels.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple


def confidence_sequence(xs: Sequence[float], alpha: float, c: float = 0.5
                        ) -> List[Tuple[float, float]]:
    """Two-sided PrPl-EB confidence sequence for the mean of [0, 1] data.

    Returns the interval after each observation. ``alpha`` is the error level
    for the whole sequence, not for each interval.
    """
    out: List[Tuple[float, float]] = []
    log_term = math.log(2.0 / alpha)
    sum_lam = sum_lam_x = sum_v_psi = 0.0
    sum_x = 0.0
    sum_sq = 0.25          # sigma^2 prior pseudo-observation
    mu_prev = 0.5          # mu-hat before the first observation
    var_prev = 0.25
    for t, x in enumerate(xs, start=1):
        x = min(1.0, max(0.0, float(x)))
        lam = min(math.sqrt(2.0 * log_term / (var_prev * t * math.log(1.0 + t))), c)
        v = 4.0 * (x - mu_prev) ** 2
        psi = (-math.log(1.0 - lam) - lam) / 4.0
        sum_lam += lam
        sum_lam_x += lam * x
        sum_v_psi += v * psi
        centre = sum_lam_x / sum_lam
        width = (log_term + sum_v_psi) / sum_lam
        out.append((max(0.0, centre - width), min(1.0, centre + width)))
        sum_x += x
        mu_prev = (0.5 + sum_x) / (t + 1)
        sum_sq += (x - mu_prev) ** 2
        var_prev = sum_sq / (t + 1)
    return out


def monitor(outcomes: Sequence[int], error: float, confidence: float) -> Dict:
    """Drift verdict for a series of audit outcomes (1 = the accepted label was wrong)."""
    alpha = 1.0 - confidence
    outcomes = [int(x) for x in outcomes]
    if not outcomes:
        return {"n": 0, "breach": False, "interval": [0.0, 1.0]}
    cs = confidence_sequence(outcomes, alpha)
    lo, hi = cs[-1]
    first = next((t + 1 for t, (l, _) in enumerate(cs) if l > error), None)
    k, n = int(sum(outcomes)), len(outcomes)
    # within: the interval's upper end is below the target, so the audits
    # show the accepted labels' error is within it. Otherwise, without a
    # breach, there are too few audits to tell either way.
    verdict = "breach" if first is not None else ("within" if hi <= error else "unclear")
    observed = f"{k}/{n} wrong ({k / n:.0%}), target at most {error:.0%}"
    if first is not None:
        text = (f"{observed}. The error rate went above the target at audit {first} "
                f"(with {confidence:.0%} confidence); it is now in "
                f"[{lo:.3f}, {hi:.3f}].")
    elif verdict == "within":
        text = (f"{observed}. The error rate is in [{lo:.3f}, {hi:.3f}] with "
                f"{confidence:.0%} confidence, at every audit so far: within the target.")
    else:
        text = (f"{observed}. Too few audits to tell: the error rate is in "
                f"[{lo:.3f}, {hi:.3f}] with {confidence:.0%} confidence.")
    return {"n": n, "errors": k, "rate": k / n, "interval": [lo, hi],
            "breach": first is not None, "breach_at": first, "verdict": verdict,
            "statement": text}
