"""
Contract (e): match how people disagree, not a single right answer.

For subjective tasks (offensiveness, sentiment of sarcasm, humor) people
disagree for reasons that are part of the data. Collapsing their labels to a
majority throws that away, and a machine "accurate" against the majority can
be confidently wrong about how contested an item is.

Each item labeled by several people has a human label distribution. The
machine's distribution is its probabilities where the source gives them
(decision models, k-sample, logprob), or its label as a one-hot vector. The
contract reports:

- the mean Jensen-Shannon distance (base 2, in [0, 1]) between the machine's
  distribution and the people's, with a bootstrap interval;
- the human noise ceiling: the same distance between two random halves of the
  people on each item. A machine closer to the people than they are to each
  other is as close as the data allows;
- the same per annotator group, when ``groups_by`` names a user field.

It is ``met`` when the interval's upper end is at most ``max_distance``.
Without ``max_distance`` it reports and is ``met`` once it can.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .base import CalibrationView, Contract, ContractResult, TierPred

MIN_ITEMS = 20
MIN_PEOPLE = 3


def _dist(labels: Sequence[str], values: Sequence[Any]) -> np.ndarray:
    v = np.array([sum(1 for x in values if str(x) == lab) for lab in labels], float)
    s = v.sum()
    return v / s if s else np.full(len(labels), 1.0 / len(labels))


def _machine_dist(labels: Sequence[str], p: Optional[TierPred]) -> Optional[np.ndarray]:
    if p is None or not p.answered:
        return None
    if p.dist:
        v = np.array([float(p.dist.get(lab, 0.0)) for lab in labels])
        if v.sum() > 0:
            return v / v.sum()
    return _dist(labels, [p.value])


def jsd(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon distance, base 2: 0 for identical, 1 for disjoint."""
    m = 0.5 * (p + q)

    def kl(a, b):
        mask = a > 0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))
    return math.sqrt(max(0.0, 0.5 * kl(p, m) + 0.5 * kl(q, m)))


class Distributional(Contract):
    kind = "distributional"
    VERSION = "2"   # 2: look-adjusted interval level

    def _summary(self, view: CalibrationView, items, rng) -> Dict[str, Any]:
        labels = view.labels
        d_machine, d_ceiling = [], []
        for c in items:
            people = list((c.humans or {}).values())
            md = _machine_dist(labels, c.output)
            if md is None or len(people) < MIN_PEOPLE:
                continue
            hd = _dist(labels, people)
            d_machine.append(jsd(md, hd))
            shuffled = people[:]
            rng.shuffle(shuffled)
            half = len(shuffled) // 2
            d_ceiling.append(jsd(_dist(labels, shuffled[:half]), _dist(labels, shuffled[half:])))
        n = len(d_machine)
        if n < MIN_ITEMS:
            return {"n_items": n}
        arr = np.array(d_machine)
        boots = [float(np.mean(arr[rng_idx])) for rng_idx in
                 (np.random.default_rng(7 + b).integers(0, n, n) for b in range(400))]
        a = getattr(self, "_alpha", 1 - self.cfg.confidence)
        lo, hi = np.quantile(boots, [a / 2, 1 - a / 2])
        return {"n_items": n, "machine_distance": float(arr.mean()),
                "interval": [float(lo), float(hi)],
                "human_ceiling": float(np.mean(d_ceiling)),
                "machine_within_ceiling": bool(arr.mean() <= np.mean(d_ceiling))}

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        from . import stats
        res = ContractResult(status="insufficient", look=look)
        # Each look's interval is at its own, stricter level, so testing
        # max_distance again as labels arrive keeps the stated confidence.
        self._alpha = stats.look_alpha(1.0 - float(self.cfg.confidence), look)
        res.alpha = self._alpha
        rng = random.Random(0)
        overall = self._summary(view, view.cal, rng)
        res.metrics["overall"] = overall
        if self.cfg.groups_by:
            # Annotator groups: each group's distribution on an item is built
            # from that group's people only.
            field_ = self.cfg.groups_by
            group_of = {u: a.get(field_) for u, a in view.user_groups.items()
                        if a.get(field_) is not None}
            groups = sorted(set(group_of.values()))
            if not groups:
                res.notes.append(f"groups_by: no annotator has a {field_!r} answer, so "
                                 "only the overall figures are reported.")
            res.metrics["groups"] = {g: self._summary(view, [
                replace(c, humans={u: v for u, v in (c.humans or {}).items()
                                   if group_of.get(u) == g}) for c in view.cal], rng)
                for g in groups}
        if "machine_distance" not in overall:
            res.notes.append(f"Needs at least {MIN_ITEMS} items labeled by "
                             f"{MIN_PEOPLE} or more people.")
            res.projection = {"more_overlap_items": MIN_ITEMS - overall["n_items"]}
            res.ran = False
            return res
        target = self.cfg.max_distance
        if target is None or overall["interval"][1] <= target:
            res.status = "met"
        elif overall["interval"][0] > target:
            # The whole interval is above the target: more items narrow it
            # around a distance that is too large, so waiting will not help.
            res.status = "infeasible"
            res.notes.append(
                f"The machine's distribution is {overall['machine_distance']:.3f} from the "
                f"people's, and the interval's lower end is above max_distance {target:g}. "
                "More items will not meet it; a source with better calibrated "
                "probabilities, or a looser target, might.")
        res.statement = (
            f"The machine's label distribution is {overall['machine_distance']:.3f} "
            f"(JS distance) from the people's on {overall['n_items']} items; two halves "
            f"of the people are {overall['human_ceiling']:.3f} from each other.")
        return res
