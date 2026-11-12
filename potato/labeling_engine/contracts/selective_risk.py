"""
Contract (a): a guarantee on the labels the machines are allowed to accept.

    With probability at least 1 - delta, at most `error` of the labels
    accepted under the certified rule are wrong.

The rule is a confidence threshold per cascade tier, and per predicted class
when ``per_class`` is set. Items a tier is not confident enough about go to
the next tier, and after the last one to a human.

How the guarantee is made valid
-------------------------------
Thresholds are chosen on the ``dev`` split and tested on the ``cert`` split,
which nothing else reads.

- For every tier but the last, the threshold is fixed from dev and tested
  once on cert. Fixing it from dev makes the set of items each later tier
  sees independent of the cert labels, so each tier's test is a test about a
  fixed population.
- The last tier runs Learn-then-Test fixed-sequence testing (Angelopoulos et
  al., "Learn then Test") over thresholds from the dev choice toward more
  liberal ones, each tested at the same level, stopping at the first that
  fails. Fixed-sequence testing needs no correction across the sequence.
- Each test is a one-sided binomial test of H0: error among accepted > error.
  The levels are Bonferroni-split across tiers x classes, and the overall
  delta is spent across repeated looks at a growing cert set by
  ``stats.look_alpha``.
- A tier whose test fails accepts nothing: its items go to humans, not to the
  next tier, so the next tier's tested population is unchanged.

If every accepted subset has error at most `error`, so does their union, so
the per-cell guarantees give the overall one.

The binomial test needs a uniform sample of each tested cell. A Bernoulli or
stratified-by-predicted-class design gives one; a cell whose cert items have
unequal inclusion probabilities is not tested, and the result says why.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import stats
from .base import CalItem, CalibrationView, Contract, ContractResult, PopItem, TierPred

#: Dev-side confidence for choosing a threshold. Not part of the guarantee;
#: a dev choice that is too liberal just fails on cert.
DEV_LEVEL = 0.8
#: The dev choice must leave this factor of headroom in cert labels. The cert
#: search moves on to more liberal thresholds by itself, so starting a little
#: conservative costs little coverage, while starting at the edge fails the
#: first test about half the time and then certifies nothing.
DEV_MARGIN = 1.5
#: The last tier's cert search starts at the most conservative threshold with
#: at least this many times the fewest cert points that could certify. Two
#: starts at alpha/2 each (a union bound) were tried in simulation and
#: certified no more often than one, so there is one.
START_MARGIN = 1.5
MAX_GRID = 200


def _reaches(tiers: Sequence[Optional[TierPred]], t: int,
             route: Dict[int, Dict[str, Optional[float]]], per_class: bool,
             class_of=None) -> bool:
    """Whether an item gets past tiers 0..t-1 to tier t.

    An item leaves the cascade at the first earlier tier that answered with
    confidence at or above that tier's routing threshold.
    """
    for j in range(t):
        p = tiers[j] if j < len(tiers) else None
        if p is None or not p.answered:
            continue
        lam = route.get(j, {}).get(_key(p, per_class, class_of))
        if lam is not None and p.conf >= lam:
            return False
    return True


def _key(p: TierPred, per_class: bool, class_of) -> str:
    if not per_class:
        return "*"
    return class_of(p.value) if class_of else str(p.value)


def _cell(items, t, cls, route, per_class, class_of=None):
    out = []
    for it in items:
        p = it.tiers[t] if t < len(it.tiers) else None
        if p is None or not p.answered or not _reaches(it.tiers, t, route, per_class,
                                                       class_of):
            continue
        if per_class and _key(p, True, class_of) != cls:
            continue
        out.append((it, p))
    return out


class _Counts:
    """Errors and counts at any threshold, from one sort of the cell."""

    def __init__(self, cell, view: CalibrationView):
        conf = np.array([p.conf for _, p in cell], dtype=float)
        wrong = np.array([0 if view.correct(p.value, it.human) else 1
                          for it, p in cell], dtype=int)
        order = np.argsort(-conf, kind="stable")
        self.conf = conf[order]
        self.cum_wrong = np.concatenate([[0], np.cumsum(wrong[order])])

    def __call__(self, lam: float) -> Tuple[int, int]:
        # Items with conf >= lam are a prefix of the descending order.
        n = int(np.searchsorted(-self.conf, -lam, side="right"))
        return int(self.cum_wrong[n]), n

    def grid(self) -> List[float]:
        vals = sorted({round(float(c), 6) for c in self.conf}, reverse=True)
        if len(vals) > MAX_GRID:
            step = len(vals) / MAX_GRID
            vals = [vals[int(i * step)] for i in range(MAX_GRID)]
        return vals


def _errors(cell, view: CalibrationView, lam: float) -> Tuple[int, int]:
    return _Counts(cell, view)(lam)


class SelectiveRisk(Contract):
    kind = "selective_risk"
    VERSION = "2"   # 2: alpha split over tested cells only

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        eps = float(self.cfg.error)
        delta = float(self.cfg.delta)
        per_class = bool(self.cfg.per_class)
        T = len(view.tier_ids)
        classes = list(view.labels) if per_class else ["*"]
        res = ContractResult(status="insufficient", look=look)
        if T == 0:
            res.notes.append("The cascade has no machine tiers.")
            res.ran = False
            return res
        alpha_look = stats.look_alpha(delta, look)
        # Pass 1 plans with the most pessimistic split (every cell tested);
        # pass 2 splits only across the cells actually tested, which dev
        # alone decides, so the larger per-test level stays valid.
        alpha_plan = alpha_look / (T * len(classes))
        dev, cert = view.split("dev"), view.split("cert")
        n_min = stats.min_n_for_zero_errors(eps, alpha_plan)

        route: Dict[int, Dict[str, Optional[float]]] = {}
        cells: Dict[str, Dict[str, Any]] = {}
        plan = []           # (t, tier_id, cls, info, grid, ccount, proj, lam_dev)
        any_feasible, any_answered = False, False

        # --- pass 1: dev only ------------------------------------------------
        for t, tier_id in enumerate(view.tier_ids):
            route[t] = {}
            res.acceptance[tier_id] = {}
            last = t == T - 1
            for cls in classes:
                dcell = _cell(dev, t, cls, route, per_class, view.class_of)
                ccell = _cell(cert, t, cls, route, per_class, view.class_of)
                info: Dict[str, Any] = {"n_dev": len(dcell), "n_cert": len(ccell)}
                ratio = (len(ccell) / len(dcell)) if dcell else 0.0
                dcount, ccount = _Counts(dcell, view), _Counts(ccell, view)
                grid = dcount.grid()
                lam_dev, dev_err, proj = None, None, None
                # The lowest raw dev error on the last tier among thresholds
                # with enough labels to mean something: under the target but
                # not under half of it, the test never starts (B8).
                closest = None
                need_cache: Dict[float, Optional[int]] = {}

                def need_for(p):
                    key = round(p, 3)
                    if key not in need_cache:
                        need_cache[key] = stats.n_needed(key, eps, alpha_plan)
                    return need_cache[key]

                for lam in grid:
                    k, n = dcount(lam)
                    if n < 5:
                        continue
                    p_hat = (k + 0.5) / (n + 1)
                    # A threshold counts toward the projection only if the
                    # rule below could ever choose it: on the last tier dev's
                    # error must be at most half the target, and the cert
                    # labels must reach the start margin. Projecting from
                    # thresholds it would never choose said "about 3 more" on
                    # every pass while nothing could be tested.
                    # Judged on the raw rate: the smoothed p_hat cannot get
                    # under eps/2 on a few labels even with no errors, and
                    # that is the "short" case more labels fix.
                    choosable = p_hat < eps and (not last or k / n < eps / 2)
                    if p_hat < eps:
                        any_feasible = True
                    if choosable:
                        # Labels needed if the error rate is what dev saw; the
                        # cheapest threshold is the projection's target.
                        need = need_for(p_hat)
                        if need is not None:
                            need = max(need, int(math.ceil(START_MARGIN * n_min))) if last \
                                else int(math.ceil(need * DEV_MARGIN))
                            share = n / max(1, len(dev))
                            cost = need / share if share else None
                            if cost is not None and (proj is None or cost < proj[0]):
                                proj = (cost, lam, need, k, n)
                    if last and n >= 30 and p_hat < eps and (closest is None or k / n < closest):
                        closest = k / n
                    if last:
                        # Start the cert search at the most conservative
                        # threshold its first test can pass: enough expected
                        # cert points and a low dev error there. The search
                        # then moves to more liberal thresholds on its own.
                        if p_hat <= eps / 2 and n * ratio >= START_MARGIN * n_min:
                            lam_dev, dev_err = lam, k / n
                            break
                    else:
                        # Earlier tiers get one fixed threshold: the most
                        # liberal one whose test is expected to pass.
                        need_pt = need_for(p_hat) if p_hat < eps else None
                        if need_pt is not None and need_pt * DEV_MARGIN <= n * ratio:
                            lam_dev, dev_err = lam, k / n
                route[t][cls] = lam_dev
                info.update(lam_dev=lam_dev, dev_error=dev_err)
                if last and lam_dev is None and proj is None and closest is not None \
                        and closest >= eps / 2:
                    info["closest_dev_error"] = closest
                if dcell:
                    k_all, n_all = dcount(0.0)
                    info["dev_error_all"] = k_all / n_all if n_all else None
                    any_answered = True
                pis = {round(it.pi, 12) for it, _ in ccell if it.pi is not None}
                if len(pis) > 1:
                    info["skipped"] = ("inclusion probabilities vary within this cell; "
                                       "the binomial test needs a uniform sample")
                testable = lam_dev is not None and bool(ccell) and len(pis) <= 1
                plan.append((t, tier_id, cls, info, grid, ccount, proj, lam_dev, testable))

        # --- pass 2: test on cert -------------------------------------------
        m = sum(1 for *_, testable in plan if testable)
        # Dev said no cell was ready, so the cert labels were never read.
        res.ran = m > 0
        alpha = alpha_look / max(1, m)
        res.alpha = alpha
        for t, tier_id, cls, info, grid, ccount, proj, lam_dev, testable in plan:
            certified = None
            if testable:
                sequence = [lam_dev] if t < T - 1 else grid[grid.index(lam_dev):]
                tested = []
                for lam in sequence:
                    k, n = ccount(lam)
                    p = stats.binom_pvalue_risk_above(k, n, eps)
                    tested.append({"threshold": lam, "n": n, "errors": k, "p": p})
                    if p <= alpha:
                        certified = lam
                    else:
                        break
                info["tests"] = tested[:40]
                if certified is not None:
                    k, n = ccount(certified)
                    info.update(n_accepted_cert=n, errors_cert=k,
                                error_interval=stats.clopper_pearson(k, n, 1 - 2 * alpha))
            res.acceptance[tier_id][cls] = certified
            info["certified"] = certified
            if t == T - 1 and certified is not None:
                # The last tier may certify below the dev threshold; it routes
                # nothing onward, so its routing threshold is what it accepts.
                route[t][cls] = certified
            if certified is None and proj is not None:
                cost, lam_p, need_acc, k_dev, n_dev = proj
                k_cert, have = ccount(lam_p)
                share = need_acc / cost if cost else 0
                if testable and have >= need_acc:
                    # Enough cert labels and the test still failed: cert saw
                    # more errors than dev. Projecting from the count alone
                    # said "about 3 more" for 150 labels (B8); use the rate
                    # both halves saw.
                    p_pool = (k_dev + k_cert + 0.5) / (n_dev + have + 1)
                    need2 = stats.n_needed(round(p_pool, 3), eps, alpha)
                    if need2 is None:
                        info["projection_note"] = (
                            f"held-out error {k_cert}/{have} at this threshold puts the "
                            "rate at the target; more labels are unlikely to certify it")
                        share = 0
                    else:
                        need_acc = max(need2, have + 1)
                if share > 0:
                    info["more_cert_labels"] = max(1, int((need_acc - have) / share) + 1)
            cells[f"{tier_id}:{cls}"] = info

        res.metrics["cells"] = cells
        res.metrics["tested_cells"] = m
        res.metrics["route"] = {view.tier_ids[t]: r for t, r in route.items()}
        res.metrics.update(self.coverage(view, res.acceptance, route, per_class))

        needs = [c.get("more_cert_labels") for c in cells.values()
                 if c.get("more_cert_labels") is not None]
        frac = getattr(self, "dev_fraction", 0.5)
        if needs:
            # The cheapest cell to certify, not the dearest: one certified
            # cell already lets the machines take some of the work.
            res.projection = {
                "more_cert_labels": min(needs),
                "more_calibration_labels": int(min(needs) / max(1e-9, 1 - frac)) + 1,
                "note": "Projected from the error rate the labels so far show, for the cell that is "
                        "cheapest to certify.",
            }
        certified_any = any(v is not None for tier in res.acceptance.values()
                            for v in tier.values())
        if certified_any:
            res.status = "met"
        elif not any_feasible and any_answered and len(dev) >= 30:
            res.status = "infeasible"
            res.notes.append(
                f"On the dev labels no tier reaches an error rate below {eps:.3f}. "
                "More labels will not certify this target; a better prompt or model "
                "might, or a looser target.")
        else:
            res.status = "insufficient"
            close = [c["closest_dev_error"] for c in cells.values()
                     if c.get("closest_dev_error") is not None]
            if close and not needs:
                best = min(close)
                res.notes.append(
                    f"The lowest machine error on the dev labels is {best:.1%}: under the "
                    f"target of {eps:.1%}, but the test starts only once it is at most "
                    f"half the target ({eps / 2:.1%}), so nothing is tested. More labels "
                    "help only if the error turns out lower; a better prompt or model, or "
                    f"a target of at least {2 * best:.1%}, would let it start.")
        scope = "for each predicted class" if per_class else "overall"
        if res.status == "met":
            res.statement = (
                f"With probability at least {1 - delta:.2f}, at most {eps:.1%} of the "
                f"labels accepted under this rule are wrong ({scope}; {view.n_cert} "
                f"held-out labels, look {look}).")
        else:
            # Quoted on its own (the certificate's statement column, the admin
            # page), the guarantee sentence would read as established.
            res.statement = (
                f"Target, not established: at most {eps:.1%} of accepted labels wrong, "
                f"with probability at least {1 - delta:.2f} ({scope}). No machine label "
                f"on this scheme is accepted until it is met ({view.n_cert} held-out "
                f"labels, look {look}).")
        return res

    @staticmethod
    def coverage(view: CalibrationView, acceptance, route, per_class) -> Dict[str, Any]:
        """Share of the population each tier would accept under the rule."""
        n = len(view.population)
        by_tier = {tid: 0 for tid in view.tier_ids}
        routed_to_human = 0
        for it in view.population:
            placed = False
            for t, tid in enumerate(view.tier_ids):
                p = it.tiers[t] if t < len(it.tiers) else None
                if p is None or not p.answered:
                    continue
                key = _key(p, per_class, view.class_of)
                lam_route = route.get(t, {}).get(key)
                if lam_route is None or p.conf < lam_route:
                    continue
                lam_cert = acceptance.get(tid, {}).get(key)
                if lam_cert is not None and p.conf >= lam_cert:
                    by_tier[tid] += 1
                else:
                    routed_to_human += 1
                placed = True
                break
            if not placed:
                routed_to_human += 1
        accepted = sum(by_tier.values())
        return {"population": n, "accepted": accepted,
                "coverage": accepted / n if n else 0.0,
                "accepted_by_tier": by_tier, "to_humans": routed_to_human}
