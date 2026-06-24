"""Unit tests for active preference-pair selection (E10)."""

import pytest

from potato.server_utils.active_preference import (
    acquisition, select_pairs, expected_label_savings, _win_prob, STRATEGIES,
)


class TestAcquisition:
    def test_uncertainty_peaks_at_tie(self):
        tie = acquisition({"score_a": 1.0, "score_b": 1.0}, "uncertainty")
        lopsided = acquisition({"score_a": 5.0, "score_b": -5.0}, "uncertainty")
        assert tie == pytest.approx(1.0)
        assert lopsided < 0.05

    def test_moderate_margin_peaks_at_equal(self):
        assert acquisition({"score_a": 2.0, "score_b": 2.0}, "moderate_margin") == 1.0
        assert acquisition({"score_a": 0.0, "score_b": 10.0}, "moderate_margin") < 0.2

    def test_random_constant(self):
        assert acquisition({"score_a": 0, "score_b": 9}, "random") == 0.5

    def test_win_prob_helper(self):
        assert _win_prob(0.0, 0.0) == pytest.approx(0.5)
        assert _win_prob(10.0, -10.0) > 0.99

    def test_missing_scores_default(self):
        assert acquisition({}, "uncertainty") == 0.5

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError):
            acquisition({}, "bogus")


class TestSelectPairs:
    def _pool(self):
        # a mix: near-ties (informative) and blowouts (uninformative)
        return [
            {"pair_id": "tie1", "score_a": 1.0, "score_b": 1.0},
            {"pair_id": "tie2", "score_a": 0.5, "score_b": 0.4},
            {"pair_id": "blow1", "score_a": 9.0, "score_b": -9.0},
            {"pair_id": "blow2", "score_a": 8.0, "score_b": -2.0},
        ]

    def test_uncertainty_prioritizes_ties(self):
        sel = select_pairs(self._pool(), k=2, strategy="uncertainty")
        ids = {c["pair_id"] for c in sel}
        assert ids == {"tie1", "tie2"}
        assert all(c["acquisition"] >= sel[-1]["acquisition"] for c in sel)

    def test_deterministic(self):
        pool = self._pool()
        assert select_pairs(pool, k=4) == select_pairs(pool, k=4)

    def test_random_is_deterministic_with_seed(self):
        pool = self._pool()
        assert ([c["pair_id"] for c in select_pairs(pool, 4, "random", seed=7)]
                == [c["pair_id"] for c in select_pairs(pool, 4, "random", seed=7)])

    def test_annotates_strategy(self):
        sel = select_pairs(self._pool(), k=1, strategy="uncertainty")
        assert sel[0]["strategy"] == "uncertainty" and "acquisition" in sel[0]

    def test_k_caps(self):
        assert len(select_pairs(self._pool(), k=2)) == 2


class TestSavingsReport:
    def test_active_beats_random_on_skewed_pool(self):
        # pool dominated by blowouts -> active (picks the few ties) beats random
        pool = [{"pair_id": f"b{i}", "score_a": 9.0, "score_b": -9.0} for i in range(18)]
        pool += [{"pair_id": "t1", "score_a": 1.0, "score_b": 1.0},
                 {"pair_id": "t2", "score_a": 1.0, "score_b": 1.0}]
        rep = expected_label_savings(pool, k=2, strategy="uncertainty")
        assert rep["active_mean_acquisition"] > rep["random_mean_acquisition"]
        assert rep["active_beats_random"] is True

    def test_empty(self):
        assert expected_label_savings([], k=5)["n"] == 0
