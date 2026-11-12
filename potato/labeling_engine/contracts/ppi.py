"""
Contract (b): unbiased estimates from machine labels plus a few human ones.

A prevalence computed from machine labels alone carries the machine's bias:
a model that over-calls "toxic" by five points reports five points too much
toxicity, with a confidence interval too narrow to show it. Prediction-powered
inference (Angelopoulos et al., Science 2023) corrects the machine estimate
with the error measured on a random human-labeled sample, and gives an
interval that is valid whatever the machine's quality. A good machine makes
the interval narrow; a bad one makes it no worse than humans alone.

Two estimators, chosen by the sampling design:

- Every labeled item had the same inclusion probability (a Bernoulli or
  simple random calibration sample): PPI++ (Angelopoulos, Duchi and Zrnic,
  2023) with the power-tuning weight lambda.
- Probabilities differ (stratified or active sampling, which spends human
  labels where the machine is least sure): the Horvitz-Thompson difference
  estimator, which is what active statistical inference (Zrnic and Candes,
  ICML 2024) reduces to for a mean.

Repeated looks at a growing sample spend the error level as the selective-risk
contract does, so an interval reported after every batch keeps its coverage.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import stats
from .base import CalibrationView, Contract, ContractResult, TierPred

MIN_LABELS = 10


def _variance_floor(n: int, value_range: float) -> float:
    """The least residual variance a sample of n is allowed to claim.

    A sample in which every residual is zero (the machine agreed with every
    human it was checked against) says the error rate is small, not that it
    is zero. Without a floor such a sample gives a zero-width interval, and in
    simulation an interval over a stratum sampled at 2% covered the truth 68%
    of the time instead of 90%. The floor is the variance of one error of
    full size in n + 2 draws, the same pseudo-count idea as the Agresti-Coull
    interval.
    """
    q = 1.0 / (n + 2)
    return (value_range ** 2) * q * (1 - q)


def ppi_mean(y_lab: np.ndarray, f_lab: np.ndarray, f_pop: np.ndarray,
             level: float, tune: bool = True, value_range: float = 1.0
             ) -> Dict[str, float]:
    """PPI++ estimate and interval for E[Y] under uniform sampling."""
    n, N = len(y_lab), len(f_pop)
    if n < 2 or N < 1:
        raise ValueError("need at least two labeled items and a population")
    lam = 1.0
    if tune:
        vf = float(np.var(f_lab, ddof=1)) if n > 1 else 0.0
        if vf > 0:
            cov = float(np.cov(y_lab, f_lab, ddof=1)[0, 1])
            lam = min(1.0, max(0.0, cov / ((1 + n / N) * vf)))
        else:
            lam = 0.0
    rect = y_lab - lam * f_lab
    est = lam * float(np.mean(f_pop)) + float(np.mean(rect))
    var_rect = max(float(np.var(rect, ddof=1)), _variance_floor(n, value_range))
    var = (lam ** 2) * float(np.var(f_pop, ddof=1) if N > 1 else 0.0) / N + var_rect / n
    lo, hi = stats.normal_ci(est, math.sqrt(max(var, 0.0)), level)
    return {"estimate": est, "lo": lo, "hi": hi, "lambda": lam, "n": n, "N": N}


def stratified_difference_mean(y_lab: np.ndarray, f_lab: np.ndarray, pi_lab: np.ndarray,
                               f_pop: np.ndarray, pi_pop: np.ndarray, level: float,
                               value_range: float = 1.0) -> Dict[str, float]:
    """Difference estimator of E[Y] for a sample stratified by inclusion probability.

    Strata are the distinct pi values. Within a stratum the labeled items are a
    uniform sample, so its mean residual estimates the stratum's machine error;
    each stratum's correction is weighted by its population size N_h. Using the
    realized n_h rather than the expected N_h * pi_h is the post-stratified
    form, steadier than Horvitz-Thompson when n_h is small.
    """
    N = len(f_pop)
    if N < 1 or len(y_lab) < 2:
        raise ValueError("need at least two labeled items and a population")
    resid = y_lab - f_lab
    est = float(np.mean(f_pop))
    var = 0.0
    key_lab = np.round(pi_lab, 12)
    key_pop = np.round(pi_pop, 12)
    for h in np.unique(key_pop):
        N_h = int(np.sum(key_pop == h))
        r_h = resid[key_lab == h]
        n_h = len(r_h)
        if n_h == 0:
            # A stratum nobody sampled: its correction is unknown, so its
            # whole range goes into the interval rather than being ignored.
            var += (N_h * value_range) ** 2 / 4
            continue
        est += N_h * float(np.mean(r_h)) / N
        s2 = float(np.var(r_h, ddof=1)) if n_h > 1 else 0.0
        s2 = max(s2, _variance_floor(n_h, value_range))
        fpc = max(0.0, 1.0 - n_h / N_h)
        var += N_h ** 2 * fpc * s2 / n_h
    var /= N ** 2
    lo, hi = stats.normal_ci(est, math.sqrt(max(var, 0.0)), level)
    return {"estimate": est, "lo": lo, "hi": hi, "lambda": 1.0, "n": len(y_lab), "N": N}


def ht_difference_mean(y_lab: np.ndarray, f_lab: np.ndarray, pi_lab: np.ndarray,
                       f_pop: np.ndarray, level: float,
                       value_range: float = 1.0) -> Dict[str, float]:
    """Horvitz-Thompson difference estimator of E[Y] under Bernoulli sampling.

    Used when the population's inclusion probabilities are not known (only the
    sampled items carry one), so strata cannot be formed.
    """
    N = len(f_pop)
    if N < 1 or len(y_lab) < 2:
        raise ValueError("need at least two labeled items and a population")
    resid = (y_lab - f_lab) / pi_lab
    est = float(np.mean(f_pop)) + float(np.sum(resid)) / N
    var = float(np.sum((1 - pi_lab) / pi_lab ** 2 * (y_lab - f_lab) ** 2)) / N ** 2
    floor = float(np.sum((1 - pi_lab) / pi_lab ** 2)) * _variance_floor(
        len(y_lab), value_range) / N ** 2
    var = max(var, floor)
    lo, hi = stats.normal_ci(est, math.sqrt(max(var, 0.0)), level)
    return {"estimate": est, "lo": lo, "hi": hi, "lambda": 1.0, "n": len(y_lab), "N": N}


def classical_mean(y_lab: np.ndarray, pi_lab: Optional[np.ndarray], N: int,
                   level: float) -> Dict[str, float]:
    """The human-only estimate, for comparison."""
    n = len(y_lab)
    if pi_lab is None:
        est = float(np.mean(y_lab))
        se = math.sqrt(float(np.var(y_lab, ddof=1)) / n) if n > 1 else float("inf")
    else:
        est = float(np.sum(y_lab / pi_lab)) / N
        se = math.sqrt(float(np.sum((1 - pi_lab) / pi_lab ** 2 * y_lab ** 2))) / N
    lo, hi = stats.normal_ci(est, se, level)
    return {"estimate": est, "lo": lo, "hi": hi, "n": n}


def _f_value(p: Optional[TierPred], cls: Optional[str], numeric: bool) -> float:
    if p is None or not p.answered:
        return 0.0
    if numeric:
        if p.dist:
            total = sum(p.dist.values()) or 1.0
            try:
                return sum(float(k) * v for k, v in p.dist.items()) / total
            except ValueError:
                pass
        try:
            return float(p.value)
        except (TypeError, ValueError):
            return 0.0
    if p.dist:
        total = sum(p.dist.values()) or 1.0
        return float(p.dist.get(cls, 0.0)) / total
    return 1.0 if str(p.value) == cls else 0.0


def _pick(item, t: Optional[int]) -> Optional[TierPred]:
    if t is None:
        return item.output
    return item.tiers[t] if t < len(item.tiers) else None


class PPI(Contract):
    kind = "ppi"
    VERSION = "2"   # 2: f is the routed cascade output, not the last tier

    def _tier_index(self, view: CalibrationView) -> Optional[int]:
        """The tier whose prediction is the estimator's f, or None for the
        cascade's routed output.

        f must be the same function of an item whether or not the item was
        sampled. Later tiers label the calibration sample but only some of the
        rest, so "the last tier's prediction" exists for every sampled item
        and few others; using it biased a live estimate by half. The routed
        output is used when it is complete; otherwise the deepest tier that
        labeled every item.
        """
        want = (self.cfg.raw or {}).get("tier")
        if want in view.tier_ids:
            return view.tier_ids.index(want)
        if view.output_complete:
            return None
        for t in range(len(view.tier_ids) - 1, -1, -1):
            if all(t < len(p.tiers) and p.tiers[t] is not None for p in view.population):
                return t
        return 0

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        res = ContractResult(status="insufficient", look=look)
        alpha = stats.look_alpha(1.0 - float(self.cfg.confidence), look)
        level = 1.0 - alpha
        res.alpha = alpha
        if not view.tier_ids:
            res.notes.append("The cascade has no machine tiers.")
            res.ran = False
            return res
        t = self._tier_index(view)
        numeric = self.cfg.estimand == "mean"
        targets: List[Optional[str]] = [None] if numeric else list(view.labels)
        groups: List[Optional[str]] = [None]
        by = self.cfg.by

        def group_of(iid):
            return (view.item_fields.get(iid) or {}).get(by) if by else None
        if by:
            found = sorted({g for g in (group_of(p.item_id) for p in view.population)
                            if g is not None})
            groups += found
            if not found:
                res.notes.append(f"by: no item has a {by!r} field, so only the overall "
                                 "estimate is reported.")

        labeled = [c for c in view.cal if c.pi is not None and c.pi > 0
                   and c.human is not None]
        pop_ids = {p.item_id for p in view.population}
        dropped = [c for c in labeled if c.item_id not in pop_ids]
        labeled = [c for c in labeled if c.item_id in pop_ids]
        if dropped:
            res.notes.append(f"{len(dropped)} labeled item(s) are outside the population "
                             "and were not used.")

        estimates: Dict[str, Any] = {}
        widths = []
        for g in groups:
            lab = [c for c in labeled if g is None or group_of(c.item_id) == g]
            pop = [p for p in view.population if g is None or group_of(p.item_id) == g]
            gkey = "all" if g is None else g
            if len(lab) < MIN_LABELS or not pop:
                estimates[gkey] = {"n": len(lab), "N": len(pop),
                                   "note": f"needs at least {MIN_LABELS} labels"}
                continue
            pis = np.array([c.pi for c in lab], dtype=float)
            uniform = float(pis.max() - pis.min()) < 1e-12
            pop_pis = [p.pi for p in pop]
            strata_known = all(x is not None for x in pop_pis)
            if numeric:
                try:
                    vals = [float(x) for x in view.labels]
                    value_range = (max(vals) - min(vals)) or 1.0
                except ValueError:
                    value_range = 1.0
            else:
                value_range = 1.0
            out = {}
            for cls in targets:
                if numeric:
                    try:
                        y = np.array([float(c.human) for c in lab])
                    except (TypeError, ValueError):
                        res.notes.append("A human label is not a number; the mean "
                                         "estimand needs numeric labels.")
                        res.ran = False
                        return res
                else:
                    y = np.array([1.0 if str(c.human) == cls else 0.0 for c in lab])
                f_lab = np.array([_f_value(_pick(c, t), cls, numeric) for c in lab])
                f_pop = np.array([_f_value(_pick(p, t), cls, numeric) for p in pop])
                if uniform:
                    e = ppi_mean(y, f_lab, f_pop, level, value_range=value_range)
                    human = classical_mean(y, None, len(pop), level)
                    e["estimator"] = "ppi++"
                elif strata_known:
                    e = stratified_difference_mean(
                        y, f_lab, pis, f_pop, np.array(pop_pis, dtype=float), level,
                        value_range=value_range)
                    human = classical_mean(y, pis, len(pop), level)
                    e["estimator"] = "stratified_difference"
                else:
                    e = ht_difference_mean(y, f_lab, pis, f_pop, level,
                                           value_range=value_range)
                    human = classical_mean(y, pis, len(pop), level)
                    e["estimator"] = "ht_difference"
                if not numeric:
                    e["lo"], e["hi"] = max(0.0, e["lo"]), min(1.0, e["hi"])
                e["machine_only"] = float(np.mean(f_pop))
                e["human_only"] = human
                widths.append(e["hi"] - e["lo"])
                out["mean" if numeric else cls] = e
            estimates[gkey] = out

        res.metrics["estimates"] = estimates
        res.metrics["level"] = level
        res.metrics["tier"] = "cascade output" if t is None else view.tier_ids[t]
        if not widths:
            res.projection = {"more_calibration_labels": max(0, MIN_LABELS - len(labeled))}
            res.ran = False
            return res
        target = self.cfg.max_width
        widest = max(widths)
        res.metrics["widest_interval"] = widest
        if target is None:
            res.status = "met"
        elif widest <= float(target):
            res.status = "met"
        else:
            # Width shrinks like 1/sqrt(n).
            n = len(labeled)
            need = int(math.ceil(n * (widest / float(target)) ** 2)) - n
            res.projection = {"more_calibration_labels": max(1, need),
                              "note": "Projected from the current interval width."}
            res.status = "insufficient"
        what = "the mean" if numeric else "each label's prevalence"
        res.statement = (f"{level:.1%} intervals for {what}, corrected for the machine's "
                         f"error on {len(labeled)} randomly sampled human labels "
                         f"(look {look}).")
        return res
