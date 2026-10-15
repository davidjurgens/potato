"""
Contract (d): what a human-label budget buys.

The other contracts start from a target and say how many labels it needs.
This one starts from the budget (``human_labels``, or ``human_usd`` at the
crowd reward per label) and reports, from the dev labels collected so far,
the best guarantee it can be expected to buy:

- for each error target on a grid, the share of the corpus the machines could
  be certified to label, with the cert labels the budget adds;
- how wide each prevalence interval would be.

It is a projection, not a guarantee: the guarantee comes from the
selective-risk or PPI contract once the labels are in. Its status is ``met``
when there are enough dev labels to project from.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from . import stats
from .base import CalibrationView, Contract, ContractResult

ERROR_GRID = (0.02, 0.05, 0.1, 0.15, 0.2, 0.3)
MIN_DEV = 20


class BudgetFirst(Contract):
    kind = "budget_first"
    VERSION = "1"

    def _labels(self) -> int:
        if self.cfg.human_labels is not None:
            return int(self.cfg.human_labels)
        reward = float((self.cfg.raw or {}).get("reward_per_label_usd") or 0)
        if self.cfg.human_usd is not None and reward > 0:
            return int(self.cfg.human_usd / reward)
        return 0

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        # A projection, not a test: it reads dev labels only and spends nothing.
        res = ContractResult(status="insufficient", look=look, ran=False)
        budget = self._labels()
        dev = view.split("dev")
        frac_cert = 1.0 - float(getattr(self, "dev_fraction", 0.5))
        scored = [(c.output.conf, view.correct(c.output.value, c.human))
                  for c in dev if c.output is not None and c.output.answered]
        res.metrics["budget_labels"] = budget
        res.metrics["n_dev"] = len(scored)
        if len(scored) < MIN_DEV:
            res.notes.append(f"Needs at least {MIN_DEV} dev labels with a machine answer "
                             "to project from.")
            res.projection = {"more_calibration_labels": 2 * (MIN_DEV - len(scored))}
            return res
        scored.sort(key=lambda x: -x[0])
        n_dev = len(scored)
        cert_total = view.n_cert + int(budget * frac_cert)
        delta = float(self.cfg.delta)
        alpha = stats.look_alpha(delta, max(1, look) + 1)
        frontier: List[Dict[str, Any]] = []
        for eps in ERROR_GRID:
            best = {"error": eps, "coverage": 0.0, "threshold": None}
            wrong = 0
            for k, (conf, ok) in enumerate(scored, start=1):
                wrong += 0 if ok else 1
                if k < 5 or (k < n_dev and scored[k][0] == conf):
                    continue
                p_up = stats.wilson_upper(wrong, k, 0.6)
                need = stats.n_needed(p_up, eps, alpha) if p_up < eps else None
                share = k / n_dev
                if need is not None and need <= cert_total * share:
                    best = {"error": eps, "coverage": share, "threshold": conf}
            frontier.append(best)
        res.metrics["frontier"] = frontier
        res.metrics["cert_labels_after_budget"] = cert_total
        # PPI interval width shrinks like 1/sqrt(n).
        n_lab = len([c for c in view.cal if c.pi])
        if n_lab:
            p = sum(1 for c in view.cal if c.human == view.labels[0]) / n_lab if view.labels else 0.5
            res.metrics["prevalence_halfwidth_after_budget"] = 1.645 * math.sqrt(
                max(p * (1 - p), 0.01) / (n_lab + budget))
        res.status = "met"
        best = max(frontier, key=lambda f: (f["coverage"] > 0, -f["error"]))
        res.statement = (
            f"With {budget} more human labels, the dev labels so far project that "
            + (f"an error target of {best['error']:.0%} could be certified on about "
               f"{best['coverage']:.0%} of the corpus." if best["coverage"] > 0 else
               "no error target on the grid could be certified."))
        return res
