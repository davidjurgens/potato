"""Unit tests for the evaluation statistics layer (D7)."""

import pytest

from potato.server_utils import eval_stats as st


class TestBootstrapCI:
    def test_ci_brackets_mean(self):
        r = st.bootstrap_ci([1, 2, 3, 4, 5] * 10)
        assert r["lo"] <= r["mean"] <= r["hi"]
        assert r["mean"] == pytest.approx(3.0, abs=0.2)
        assert r["n"] == 50

    def test_deterministic(self):
        vals = [0.1, 0.9, 0.4, 0.6, 0.5, 0.7]
        assert st.bootstrap_ci(vals) == st.bootstrap_ci(vals)

    def test_single_value_collapses(self):
        r = st.bootstrap_ci([0.7])
        assert r["lo"] == r["hi"] == r["mean"] == 0.7

    def test_empty(self):
        r = st.bootstrap_ci([])
        assert r["mean"] is None and r["n"] == 0

    def test_ignores_none(self):
        r = st.bootstrap_ci([1.0, None, 1.0, None])
        assert r["mean"] == 1.0 and r["n"] == 2

    def test_tighter_ci_with_more_data(self):
        few = st.bootstrap_ci([0, 1] * 5)
        many = st.bootstrap_ci([0, 1] * 200)
        assert (many["hi"] - many["lo"]) < (few["hi"] - few["lo"])


class TestWilsonCI:
    def test_basic(self):
        r = st.wilson_ci(7, 10)
        assert r["rate"] == 0.7
        assert 0.0 <= r["lo"] < 0.7 < r["hi"] <= 1.0

    def test_extreme_rate_stays_in_bounds(self):
        r = st.wilson_ci(10, 10)  # 100% wins
        assert r["hi"] <= 1.0 and r["lo"] > 0.0  # Wilson never gives [1,1]

    def test_zero_total(self):
        r = st.wilson_ci(0, 0)
        assert r["rate"] is None

    def test_more_data_tightens(self):
        small = st.wilson_ci(7, 10)
        large = st.wilson_ci(700, 1000)
        assert (large["hi"] - large["lo"]) < (small["hi"] - small["lo"])


class TestPairedBootstrap:
    def test_clear_winner_is_significant(self):
        a = [0.9] * 30
        b = [0.1] * 30
        r = st.paired_bootstrap(a, b)
        assert r["mean_diff"] == pytest.approx(0.8, abs=1e-6)
        assert r["significant"] is True
        assert r["lo"] > 0

    def test_no_difference_not_significant(self):
        a = [0.5, 0.6, 0.4, 0.55, 0.45] * 6
        r = st.paired_bootstrap(a, list(a))
        assert r["mean_diff"] == pytest.approx(0.0, abs=1e-9)
        assert r["significant"] is False

    def test_drops_unpaired(self):
        r = st.paired_bootstrap([1.0, None, 1.0], [0.0, 0.0, None])
        assert r["n"] == 1  # only the first pair is complete

    def test_empty(self):
        r = st.paired_bootstrap([], [])
        assert r["n"] == 0 and r["significant"] is False


class TestExperimentHelpers:
    def _exp(self, scores_by_example):
        from potato.experiments.models import Experiment, ExperimentResult
        results = [ExperimentResult(example_id=eid, scores=sc)
                   for eid, sc in scores_by_example.items()]
        return Experiment(id="x", dataset_name="d", dataset_version="1", results=results)

    def test_metric_cis(self):
        exp = self._exp({"e1": {"acc": 1.0}, "e2": {"acc": 0.0}, "e3": {"acc": 1.0}})
        cis = st.experiment_metric_cis(exp)
        assert "acc" in cis
        assert cis["acc"]["mean"] == pytest.approx(2/3, abs=1e-6)

    def test_compare_metric_paired_by_example(self):
        a = self._exp({"e1": {"acc": 1.0}, "e2": {"acc": 1.0}, "e3": {"acc": 1.0}})
        b = self._exp({"e1": {"acc": 0.0}, "e2": {"acc": 0.0}, "e3": {"acc": 0.0}})
        cmp = st.compare_experiments_metric(a, b, "acc")
        assert cmp["mean_diff"] == pytest.approx(1.0)
        assert cmp["significant"] is True
        assert cmp["n"] == 3
