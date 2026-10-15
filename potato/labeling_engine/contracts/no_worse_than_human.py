"""
Contract (c): the machine is no worse than a person.

An absolute accuracy target against one person's labels partly measures that
person's noise: on a task where two careful people agree 85% of the time, no
labeler can be shown to be 95% "right". The alternative annotator test
(Calderon, Reichart and Dror, ACL 2025; ``server_utils/alt_test.py``) asks the
relative question instead. Leaving each annotator out in turn, does the
machine agree with the remaining annotators at least as often as the
left-out one does, up to an allowance ``epsilon``? The machine passes when
it wins against at least half of the annotators, with the false discovery
rate across annotators controlled.

It needs items labeled by several people. ``humans.overlap`` and
``humans.overlap_k`` make the engine send a share of the calibration sample to
that many people; the alt-test asks for at least three annotators with 30
items each.

The machine's label is the cascade's routed output, the label the engine
would accept, so the test is about what is delivered.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import CalibrationView, Contract, ContractResult


class NoWorseThanHuman(Contract):
    kind = "no_worse_than_human"
    # 2: failing to pass is "insufficient" unless clearly worse.
    # 3: each look tests at its own, stricter level.
    VERSION = "3"

    def evaluate(self, view: CalibrationView, look: int = 1) -> ContractResult:
        from potato.server_utils.alt_test import alt_test
        res = ContractResult(status="insufficient", look=look)
        if not view.output_complete:
            res.notes.append("Some items have no routed machine label yet.")
        llm = {c.item_id: (c.output.value if c.output is not None and c.output.answered
                           else None) for c in view.cal}
        humans: Dict[str, Dict[str, Any]] = {}
        for c in view.cal:
            for user, label in (c.humans or {}).items():
                humans.setdefault(user, {})[c.item_id] = label
        metric = (self.cfg.raw or {}).get("metric", "accuracy")
        min_items = int((self.cfg.raw or {}).get("min_items_per_annotator", 30))
        from . import stats
        alpha = stats.look_alpha(1.0 - float(self.cfg.confidence), look)
        out = alt_test(llm, humans, epsilon=float(self.cfg.epsilon),
                       alpha=alpha, metric=metric,
                       min_items_per_annotator=min_items,
                       test="ttest" if min_items >= 30 else "wilcoxon")
        res.metrics = {"alt_test": out.to_dict(),
                       "overlap_items": sum(1 for c in view.cal
                                            if len(c.humans or {}) >= 2)}
        res.alpha = alpha
        if out.passed is None:
            res.status = "insufficient"
            res.ran = False
            res.notes.append(out.insufficient or "not enough overlapping human labels")
            have = res.metrics["overlap_items"]
            res.projection = {"more_overlap_items": max(0, min_items - have),
                              "note": "The alt-test needs at least 3 annotators with "
                                      f"{min_items} shared items each."}
        elif out.passed:
            res.status = "met"
        else:
            # Failing to show the machine is as good is not showing it is
            # worse. "violated" only when even the point estimates put it
            # below the people by more than the allowance; otherwise more
            # overlap labels may settle it either way.
            per = out.per_annotator
            llm_adv = sum(a.llm_advantage for a in per) / len(per)
            hum_adv = sum(a.human_advantage for a in per) / len(per)
            res.metrics["mean_advantage"] = {"machine": llm_adv, "people": hum_adv}
            if llm_adv < hum_adv - float(self.cfg.epsilon):
                res.status = "violated"
            else:
                res.status = "insufficient"
                res.projection = {
                    "note": "The machine's point estimates are within the allowance of "
                            "the people's, but the test could not confirm it. More "
                            "items labeled by several people would.",
                    "more_overlap_items": max(10, res.metrics["overlap_items"] // 2)}
        res.statement = (
            f"The machine {'is' if out.passed else 'is not shown to be'} as good as a "
            f"person here: it beat {out.winning_rate or 0:.0%} of "
            f"{out.n_annotators} annotators at epsilon {self.cfg.epsilon} "
            f"(alt-test, FDR {res.alpha:.2f}); advantage probability "
            f"{(out.advantage_probability or 0):.2f}.")
        return res
