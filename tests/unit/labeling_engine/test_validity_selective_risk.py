"""
Does the selective-risk guarantee hold? Simulated studies, known truth.

Each trial draws a study, certifies thresholds, and computes the exact error
among the population items the certified rule accepts. Across trials the share
whose error exceeds `error` must be at most delta, plus Monte Carlo slack.
The guard tests remove one piece of the procedure and must see it break.
"""

import math

import numpy as np
import pytest

from potato.labeling_engine.config.schema import ContractConfig
from potato.labeling_engine.contracts.selective_risk import SelectiveRisk

from .simulate import study, true_accepted_error

TRIALS = 200


def _cfg(error=0.1, confidence=0.9, per_class=False):
    return ContractConfig(id="c", kind="selective_risk", schema="s", error=error,
                          confidence=confidence, per_class=per_class)


def _slack(delta, trials=TRIALS):
    return 3 * math.sqrt(delta * (1 - delta) / trials)


def _violation_rate(contract, trials=TRIALS, seed=0, **study_kw):
    rng = np.random.default_rng(seed)
    violations = certified = 0
    coverages = []
    for _ in range(trials):
        view, truth = study(rng, **study_kw)
        res = contract.evaluate(view)
        route = res.metrics["route"]
        err, n_acc = true_accepted_error(view, truth, res.acceptance, route,
                                         contract.cfg.per_class)
        if n_acc:
            certified += 1
        coverages.append(n_acc / len(view.population))
        if err > contract.cfg.error:
            violations += 1
    return violations / trials, certified / trials, float(np.mean(coverages))


class TestGuaranteeHolds:

    def test_single_tier_overall(self):
        c = SelectiveRisk(_cfg(error=0.1, confidence=0.9))
        rate, cert_share, cov = _violation_rate(c)
        assert rate <= 0.1 + _slack(0.1), rate
        # Not vacuous: most trials certify a rule with real coverage. (With
        # ~150 cert labels, error 0.1 and delta 0.1 the first test passes about
        # 70% of the time in this model; more labels raise it.)
        assert cert_share > 0.6 and cov > 0.3, (cert_share, cov)

    def test_single_tier_per_class(self):
        c = SelectiveRisk(_cfg(error=0.1, confidence=0.9, per_class=True))
        rate, cert_share, cov = _violation_rate(c, n_pop=2500, rate=0.2)
        assert rate <= 0.1 + _slack(0.1), rate
        assert cert_share > 0.6, cert_share

    def test_two_tier_cascade(self):
        c = SelectiveRisk(_cfg(error=0.08, confidence=0.9))
        rate, cert_share, cov = _violation_rate(
            c, tiers=(lambda x: 0.6 * (1 - x), lambda x: 0.25 * (1 - x) ** 2),
            n_pop=2500, rate=0.2)
        assert rate <= 0.1 + _slack(0.1), rate
        assert cert_share > 0.6, cert_share

    def test_stratified_design_per_class(self):
        # Rare predicted classes are oversampled; within a predicted class the
        # sample is still uniform, so per-class certification stays valid.
        c = SelectiveRisk(_cfg(error=0.1, confidence=0.9, per_class=True))
        rate, _, _ = _violation_rate(c, n_pop=2500,
                                     pi_by_pred={"a": 0.08, "b": 0.15, "c": 0.3})
        assert rate <= 0.1 + _slack(0.1), rate


class TestGuardsMatter:
    """Each removes one safeguard; the guarantee must visibly break."""

    def test_accepting_the_dev_choice_without_a_cert_test_breaks_it(self, monkeypatch):
        import potato.labeling_engine.contracts.selective_risk as sr
        # Pretend every cert test passes: what you get from trusting dev.
        monkeypatch.setattr(sr.stats, "binom_pvalue_risk_above", lambda k, n, e: 0.0)
        c = SelectiveRisk(_cfg(error=0.1, confidence=0.9))
        rate, _, _ = _violation_rate(c)
        assert rate > 0.1 + _slack(0.1), rate

    def test_choosing_thresholds_on_the_cert_split_breaks_it(self, monkeypatch):
        import potato.labeling_engine.contracts.selective_risk as sr
        # Search all the way down the grid on cert with no stopping rule,
        # keeping the most liberal threshold that individually passes.
        real_eval = SelectiveRisk.evaluate

        def greedy(self, view, look=1):
            res = real_eval(self, view, look)
            cert = view.split("cert")
            for tid in view.tier_ids:
                cell = [(it, it.tiers[0]) for it in cert]
                best = None
                for lam in sorted({p.conf for _, p in cell}, reverse=True):
                    acc = [(it, p) for it, p in cell if p.conf >= lam]
                    k = sum(p.value != it.human for it, p in acc)
                    if acc and k / len(acc) <= self.cfg.error:
                        best = lam
                res.acceptance[tid]["*"] = best
                res.metrics["route"][tid]["*"] = best
            return res
        monkeypatch.setattr(SelectiveRisk, "evaluate", greedy)
        c = SelectiveRisk(_cfg(error=0.1, confidence=0.9))
        rate, _, _ = _violation_rate(c)
        assert rate > 0.1 + _slack(0.1), rate


class TestDegenerate:

    def test_no_cert_labels_is_insufficient(self):
        rng = np.random.default_rng(1)
        view, _ = study(rng, dev_fraction=1.0)
        res = SelectiveRisk(_cfg()).evaluate(view)
        assert res.status == "insufficient"
        assert all(v is None for v in res.acceptance["t0"].values())

    def test_no_labels_at_all(self):
        rng = np.random.default_rng(2)
        view, _ = study(rng, rate=0.0)
        res = SelectiveRisk(_cfg()).evaluate(view)
        assert res.status == "insufficient" and res.metrics["coverage"] == 0.0

    def test_hopeless_model_is_infeasible(self):
        rng = np.random.default_rng(3)
        view, _ = study(rng, tiers=(lambda c: np.full_like(c, 0.6),))
        res = SelectiveRisk(_cfg(error=0.05)).evaluate(view)
        assert res.status == "infeasible"

    def test_constant_confidence(self):
        rng = np.random.default_rng(4)
        view, truth = study(rng, tiers=(lambda c: np.full_like(c, 0.01),))
        for it in view.population:
            it.tiers[0].conf = 1.0
        res = SelectiveRisk(_cfg(error=0.1)).evaluate(view)
        assert res.status == "met"
        assert res.metrics["coverage"] == 1.0

    def test_every_prediction_abstains(self):
        rng = np.random.default_rng(5)
        view, _ = study(rng)
        for it in view.population:
            it.tiers[0].status = "abstain"
        res = SelectiveRisk(_cfg()).evaluate(view)
        assert res.status == "insufficient" and res.metrics["accepted"] == 0

    def test_unequal_pi_within_a_cell_is_not_tested(self):
        rng = np.random.default_rng(6)
        view, _ = study(rng)
        for k, it in enumerate(view.cal):
            it.pi = 0.1 if k % 2 else 0.2
        res = SelectiveRisk(_cfg()).evaluate(view)
        assert res.acceptance["t0"]["*"] is None
        assert "uniform sample" in res.metrics["cells"]["t0:*"]["skipped"]

    def test_later_looks_spend_less(self):
        rng = np.random.default_rng(7)
        view, _ = study(rng)
        c = SelectiveRisk(_cfg())
        a1, a2 = c.evaluate(view, look=1).alpha, c.evaluate(view, look=2).alpha
        assert a2 < a1 < 0.1

    def test_projection_when_short(self):
        rng = np.random.default_rng(8)
        view, _ = study(rng, n_pop=3000, rate=0.02)
        res = SelectiveRisk(_cfg(error=0.05)).evaluate(view)
        if res.status != "met":
            assert res.projection.get("more_calibration_labels", 0) > 0


class TestProjectionMatchesTheRule:
    """Found by potato-skill (B8, D11): the projection counted thresholds the
    rule would never choose, and ignored its start margin, so a stalled
    contract said "about 3 more" on every planner pass."""

    def test_a_projection_covers_the_start_margin(self):
        from potato.labeling_engine.contracts import selective_risk as sr
        from potato.labeling_engine.contracts import stats
        rng = np.random.default_rng(8)
        view, _ = study(rng, n_pop=3000, rate=0.02)
        res = SelectiveRisk(_cfg(error=0.05)).evaluate(view)
        if res.status != "met" and res.projection.get("more_cert_labels"):
            n_min = stats.min_n_for_zero_errors(0.05, res.alpha)
            have = len(view.split("cert"))
            assert res.projection["more_cert_labels"] + have >= sr.START_MARGIN * n_min * 0.5


def _even_error_view(n_dev, dev_every, n_cert, cert_every):
    """Errors spread evenly over confidence: every `every`-th item is wrong."""
    from potato.labeling_engine.contracts import CalItem, CalibrationView, TierPred
    labels = ["pos", "neg"]
    cal = []
    for split, n, every in (("dev", n_dev, dev_every), ("cert", n_cert, cert_every)):
        for i in range(n):
            truth = labels[i % 2]
            pred = labels[1 - labels.index(truth)] if i % every == 0 else truth
            out = TierPred(pred, (i + 1) / n)
            cal.append(CalItem(f"{split}{i}", truth, split, 0.5, tiers=[out], output=out))
    return CalibrationView("s", labels, ["t0"], cal=cal, output_complete=True)


class TestProjectionTellsTheTruth:
    """Found by potato-skill (B8)."""

    def test_a_failed_test_with_enough_cert_labels_projects_from_its_errors(self):
        # Dev 2% wrong, cert 8%: the count was met, the test failed, and the
        # old projection said one more label, pass after pass.
        res = SelectiveRisk(_cfg()).evaluate(_even_error_view(300, 50, 300, 12))
        assert res.status == "insufficient"
        assert res.projection.get("more_cert_labels", 0) > 50 or \
            any(c.get("projection_note") for c in res.metrics["cells"].values())

    def test_an_error_between_half_the_target_and_the_target_says_why(self):
        # 7% wrong against a 10% target: the test never starts, which was
        # "insufficient" forever with no projection and no reason.
        res = SelectiveRisk(_cfg()).evaluate(_even_error_view(1000, 14, 1000, 14))
        assert res.status == "insufficient" and not res.projection
        assert any("half the target" in n for n in res.notes)
