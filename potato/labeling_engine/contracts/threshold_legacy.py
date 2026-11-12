"""
Accept above a fixed confidence, with no guarantee.

Only for configs translated from the older subsystems (``icl_labeling``'s
``min_confidence``, ``active_learning``'s ``routing_thresholds``), so they
keep behaving as they did. The certificate says plainly that these labels
are uncertified, and reports their measured error on the calibration labels
so the size of the risk is visible.
"""

from __future__ import annotations

from .base import CalibrationView, Contract, ContractResult


class ThresholdLegacy(Contract):
    kind = "threshold_legacy"
    VERSION = "1"

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        lam = float(self.cfg.threshold)
        # No test, so nothing is spent: the rule is a fixed number.
        res = ContractResult(status="met", look=look, ran=False)
        tid = view.tier_ids[-1] if view.tier_ids else None
        if tid is None:
            res.status = "insufficient"
            return res
        res.acceptance = {t: {"*": lam} for t in view.tier_ids}
        res.metrics["route"] = {t: {"*": lam} for t in view.tier_ids}
        acc = [c for c in view.cal if c.output is not None and c.output.answered
               and c.output.conf >= lam]
        wrong = sum(1 for c in acc if not view.correct(c.output.value, c.human))
        res.metrics["measured_error"] = (wrong / len(acc)) if acc else None
        res.metrics["n_measured"] = len(acc)
        res.statement = (f"Uncertified: labels with confidence at least {lam} are accepted "
                         "without a guarantee" + (
                             f"; {wrong} of {len(acc)} such calibration labels were wrong."
                             if acc else "."))
        return res
