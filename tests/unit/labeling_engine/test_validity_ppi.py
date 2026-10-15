"""
Do the PPI intervals cover the true prevalence? Simulated studies, known truth.

The machine is biased: it over-calls label "a". Its own estimate misses the
truth by several points, and a valid interval must cover the truth at its
stated rate anyway. Guard: treating a stratified sample as uniform (ignoring
inclusion probabilities) must break coverage.
"""

import math

import numpy as np
import pytest

from potato.labeling_engine.config.schema import ContractConfig
from potato.labeling_engine.contracts import CalItem, CalibrationView, PopItem, TierPred
from potato.labeling_engine.contracts.ppi import PPI, ht_difference_mean, ppi_mean

TRIALS = 400
LABELS = ["a", "b"]


def _biased_population(rng, n=2000, prev=0.3, over=0.15, under=0.1):
    """True label "a" with prob prev. The machine says "a" for 1-under of the
    a's and for `over` of the b's."""
    truth = rng.random(n) < prev
    says_a = np.where(truth, rng.random(n) >= under, rng.random(n) < over)
    conf = rng.uniform(0.5, 1.0, n)
    return truth, says_a, conf


def _view(rng, pis, **kw):
    truth, says_a, conf = _biased_population(rng, **kw)
    pop = [PopItem(f"i{i}", [TierPred("a" if says_a[i] else "b", float(conf[i]))])
           for i in range(len(truth))]
    cal = [CalItem(f"i{i}", "a" if truth[i] else "b", "dev", float(pis[i]),
                   tiers=pop[i].tiers)
           for i in np.flatnonzero(rng.random(len(truth)) < pis)]
    return CalibrationView("s", LABELS, ["t0"], cal=cal, population=pop), truth.mean()


def _coverage(trials, pi_fn, ignore_pi=False, seed=0, confidence=0.9):
    rng = np.random.default_rng(seed)
    c = PPI(ContractConfig(id="p", kind="ppi", schema="s", confidence=confidence))
    hits = machine_hits = 0
    widths = []
    for _ in range(trials):
        n = 2000
        truth, says_a, conf = _biased_population(rng, n)
        pis = pi_fn(says_a)
        pop = [PopItem(f"i{i}", [TierPred("a" if says_a[i] else "b", float(conf[i]))],
                       pi=float(pis.mean()) if ignore_pi else float(pis[i]))
               for i in range(n)]
        sampled = np.flatnonzero(rng.random(n) < pis)
        cal = [CalItem(f"i{i}", "a" if truth[i] else "b", "dev",
                       float(pis.mean()) if ignore_pi else float(pis[i]),
                       tiers=pop[i].tiers) for i in sampled]
        view = CalibrationView("s", LABELS, ["t0"], cal=cal, population=pop)
        e = c.evaluate(view).metrics["estimates"]["all"]["a"]
        p = truth.mean()
        hits += e["lo"] <= p <= e["hi"]
        machine_hits += abs(e["machine_only"] - p) < 0.01
        widths.append(e["hi"] - e["lo"])
    return hits / trials, machine_hits / trials, float(np.mean(widths))


def _floor(level, trials=TRIALS):
    return level - 3 * math.sqrt(level * (1 - level) / trials)


class TestCoverage:

    def test_uniform_sample(self):
        cov, machine_close, width = _coverage(TRIALS, lambda s: np.full(len(s), 0.1))
        assert cov >= _floor(0.9 * 0.999), cov
        # The machine alone is off by about 8 points: the correction matters.
        assert machine_close < 0.05

    def test_stratified_sample_with_inverse_probability_weights(self):
        # Oversample items the machine calls "a" (the class it gets wrong).
        cov, _, _ = _coverage(TRIALS, lambda s: np.where(s, 0.25, 0.05))
        assert cov >= _floor(0.9 * 0.999), cov

    def test_ignoring_inclusion_probabilities_breaks_coverage(self):
        # Heavy oversampling of machine-"a" items makes the unweighted
        # rectifier lean on the class the machine over-calls.
        cov, _, _ = _coverage(TRIALS, lambda s: np.where(s, 0.4, 0.02), ignore_pi=True)
        assert cov < 0.7, cov

    def test_the_same_heavy_design_is_covered_with_weights(self):
        cov, _, _ = _coverage(TRIALS, lambda s: np.where(s, 0.4, 0.02))
        assert cov >= _floor(0.9 * 0.999), cov


class TestEstimators:

    def test_ppi_beats_humans_alone_when_the_machine_is_good(self):
        rng = np.random.default_rng(3)
        n, N = 200, 20000
        y_pop = (rng.random(N) < 0.4).astype(float)
        f_pop = np.where(rng.random(N) < 0.95, y_pop, 1 - y_pop)
        idx = rng.choice(N, n, replace=False)
        e = ppi_mean(y_pop[idx], f_pop[idx], f_pop, level=0.9)
        human_se = math.sqrt(0.4 * 0.6 / n)
        assert (e["hi"] - e["lo"]) < 2 * 1.645 * human_se

    def test_power_tuning_falls_back_to_humans_for_a_useless_machine(self):
        rng = np.random.default_rng(4)
        n, N = 300, 5000
        y = (rng.random(n) < 0.5).astype(float)
        f_lab = rng.random(n)
        e = ppi_mean(y, f_lab, rng.random(N), level=0.9)
        assert e["lambda"] < 0.2

    def test_ht_reduces_to_the_population_mean_with_a_census(self):
        y = np.array([1, 0, 1, 1.0])
        f = np.array([0.5, 0.5, 0.5, 0.5])
        e = ht_difference_mean(y, f, np.ones(4), f, level=0.9)
        assert e["estimate"] == pytest.approx(0.75) and e["lo"] == pytest.approx(0.75)


class TestContract:

    def test_too_few_labels_is_insufficient(self):
        rng = np.random.default_rng(5)
        view, _ = _view(rng, np.full(2000, 0.002))
        res = PPI(ContractConfig(id="p", kind="ppi", schema="s")).evaluate(view)
        assert res.status == "insufficient"
        assert res.projection["more_calibration_labels"] > 0

    def test_width_target(self):
        rng = np.random.default_rng(6)
        view, _ = _view(rng, np.full(2000, 0.05))
        cfg = ContractConfig(id="p", kind="ppi", schema="s", max_width=0.01)
        res = PPI(cfg).evaluate(view)
        assert res.status == "insufficient"
        assert res.projection["more_calibration_labels"] > 100
        loose = ContractConfig(id="p", kind="ppi", schema="s", max_width=0.9)
        assert PPI(loose).evaluate(view).status == "met"

    def test_groups(self):
        rng = np.random.default_rng(7)
        view, _ = _view(rng, np.full(2000, 0.2))
        view.item_fields = {p.item_id: {"platform": "x" if int(p.item_id[1:]) % 2 else "y"}
                            for p in view.population}
        cfg = ContractConfig(id="p", kind="ppi", schema="s", by="platform")
        est = PPI(cfg).evaluate(view).metrics["estimates"]
        assert set(est) == {"all", "x", "y"}
        assert est["x"]["a"]["n"] + est["y"]["a"]["n"] == est["all"]["a"]["n"]

    def test_mean_estimand(self):
        rng = np.random.default_rng(8)
        N = 1000
        truth = rng.integers(1, 6, N)
        pop = [PopItem(f"i{i}", [TierPred(str(min(5, truth[i] + 1)), 0.9)]) for i in range(N)]
        cal = [CalItem(f"i{i}", str(truth[i]), "dev", 0.2, tiers=pop[i].tiers)
               for i in np.flatnonzero(rng.random(N) < 0.2)]
        view = CalibrationView("s", ["1", "2", "3", "4", "5"], ["t0"], cal=cal,
                               population=pop)
        cfg = ContractConfig(id="p", kind="ppi", schema="s", estimand="mean")
        e = PPI(cfg).evaluate(view).metrics["estimates"]["all"]["mean"]
        assert e["lo"] <= truth.mean() <= e["hi"]
        assert e["machine_only"] > truth.mean() + 0.5


def test_rare_class_with_a_perfect_sample_still_has_width():
    """Every sampled residual zero must not give a zero-width interval."""
    y = np.zeros(50)
    f = np.zeros(50)
    e = ppi_mean(y, f, np.zeros(5000), level=0.9)
    assert e["hi"] - e["lo"] > 0.01


def test_without_population_strata_the_ht_estimator_is_used():
    rng = np.random.default_rng(9)
    view, _ = _view(rng, np.where(np.arange(2000) % 2, 0.3, 0.05))
    est = PPI(ContractConfig(id="p", kind="ppi", schema="s")).evaluate(
        view).metrics["estimates"]["all"]["a"]
    assert est["estimator"] == "ht_difference"
    for p in view.population:
        p.pi = 0.3 if int(p.item_id[1:]) % 2 else 0.05
    est = PPI(ContractConfig(id="p", kind="ppi", schema="s")).evaluate(
        view).metrics["estimates"]["all"]["a"]
    assert est["estimator"] == "stratified_difference"


def _capped_trial(tmp_path, seed, record_uncapped=False, strata_known=True):
    """Two halves of a corpus with different prevalences. Half A is sampled
    by a wave the budget cut (Bernoulli 0.4, then at most 50), half B by an
    uncapped wave at 0.1. The estimate must use the cut wave's real odds."""
    from potato.labeling_engine.allocation import designs
    from potato.labeling_engine.store import EngineStore
    from potato.persistence import clear_db_cache
    clear_db_cache()
    rng = np.random.default_rng(seed)
    store = EngineStore(str(tmp_path / f"s{seed}"))
    n = 300
    ids_a = [f"a{i}" for i in range(n)]
    ids_b = [f"b{i}" for i in range(n)]
    store.upsert_items([{"item_id": i, "meta": {}} for i in ids_a + ids_b])
    truth = {i: rng.random() < 0.6 for i in ids_a}
    truth.update({i: rng.random() < 0.2 for i in ids_b})
    # The machine misses half of half A's "a" items, so the estimate leans
    # on the human correction there, weighted by A's inclusion probability.
    machine = {i: truth[i] and (i.startswith("b") or rng.random() < 0.5) for i in truth}
    designs.draw(store, "s", ids_a, designs.rates_uniform(ids_a, 0.4), seed=seed,
                 max_requests=50, shared_key="a")
    designs.draw(store, "s", ids_b, designs.rates_uniform(ids_b, 0.1), seed=seed,
                 shared_key="b")
    pis = {i: m["s"] for i, m in store.get_items_meta(ids_a + ids_b, "pi").items()}
    if record_uncapped:
        pis.update({i: 0.4 for i in ids_a})
    # Without the population's strata the estimator is Horvitz-Thompson,
    # which uses the inclusion probabilities' values, not only their groups.
    pop = [PopItem(i, [TierPred("a" if machine[i] else "b", 0.9)],
                   pi=pis[i] if strata_known else None)
           for i in ids_a + ids_b]
    by_id = {p.item_id: p for p in pop}
    cal = [CalItem(r.item_id, "a" if truth[r.item_id] else "b", "dev", pis[r.item_id],
                   tiers=by_id[r.item_id].tiers) for r in store.requests(schema="s")]
    c = PPI(ContractConfig(id="p", kind="ppi", schema="s", confidence=0.9))
    e = c.evaluate(CalibrationView("s", LABELS, ["t0"], cal=cal, population=pop)
                   ).metrics["estimates"]["all"]["a"]
    p = np.mean([truth[i] for i in truth])
    clear_db_cache()
    return e["lo"] <= p <= e["hi"], e["estimate"] - p


@pytest.mark.parametrize("strata_known", [True, False])
def test_a_budget_capped_wave_keeps_ppi_coverage(tmp_path, strata_known):
    trials = [_capped_trial(tmp_path, s, strata_known=strata_known) for s in range(120)]
    coverage = np.mean([hit for hit, _ in trials])
    assert coverage >= 0.84, coverage


def test_recording_the_uncapped_rate_would_bias_the_estimate(tmp_path):
    # Guard for the test above: the cut wave's odds matter to the estimate.
    trials = [_capped_trial(tmp_path, s, strata_known=False) for s in range(120)]
    coverage = np.mean([hit for hit, _ in trials])
    biased = [_capped_trial(tmp_path, s, record_uncapped=True, strata_known=False)
              for s in range(120)]
    assert np.mean([b for _, b in biased]) < -0.03
    assert np.mean([hit for hit, _ in biased]) < coverage - 0.1
