"""
Tests for potato.server_utils.alt_test (Calderon, Reichart & Dror, ACL 2025).

Golden values in TestReferenceParity were produced by running the reference
``alt_test`` from github.com/nitaytech/AltTest (alt_test_example.ipynb, commit
18428b1) on the seeded toy data built by ``_toy`` below. They are pinned
numbers, not recomputed here, so the test does not consult the code it checks.
"""

import math
import random

import pytest

from potato.server_utils.alt_test import (
    AltTestResult,
    accuracy_alignment,
    alt_test,
    benjamini_yekutieli,
    neg_rmse_alignment,
)


def _toy(seed, n_items=60, n_ann=4, k=3, p_h=0.75, p_f=0.85, numeric=False):
    """Seeded synthetic data; identical to the generator used for the goldens."""
    rng = random.Random(seed)
    humans = {f"a{j}": {} for j in range(n_ann)}
    llm = {}
    for i in range(n_items):
        iid = f"item{i}"
        gold = rng.randrange(k)
        for j in range(n_ann):
            if numeric:
                humans[f"a{j}"][iid] = gold + rng.choice([-1, 0, 0, 0, 1])
            else:
                humans[f"a{j}"][iid] = gold if rng.random() < p_h else rng.randrange(k)
        if numeric:
            llm[iid] = gold + rng.choice([-1, 0, 0, 0, 0, 1])
        else:
            llm[iid] = gold if rng.random() < p_f else rng.randrange(k)
    return llm, humans


def _noisy_humans(seed, n_items=60, n_ann=4, k=4, p_h=0.7):
    rng = random.Random(seed)
    gold = {f"i{i}": rng.randrange(k) for i in range(n_items)}
    humans = {
        f"h{j}": {
            i: (g if rng.random() < p_h else rng.randrange(k)) for i, g in gold.items()
        }
        for j in range(n_ann)
    }
    return gold, humans


def _majority(humans, item):
    votes = [anns[item] for anns in humans.values() if item in anns]
    return max(sorted(set(votes)), key=votes.count)


class TestScoring:
    def test_accuracy_is_mean_match_against_remaining(self):
        assert accuracy_alignment("A", ["A", "B", "A", "C"]) == 0.5

    def test_neg_rmse(self):
        assert neg_rmse_alignment(3, [1, 5]) == pytest.approx(-2.0)
        assert neg_rmse_alignment("2", [2.0]) == 0.0

    def test_neg_rmse_rejects_non_numeric(self):
        with pytest.raises(ValueError, match="numeric"):
            neg_rmse_alignment("high", [1])


class TestBenjaminiYekutieli:
    def test_hand_computed_adjustment(self):
        # m=4, c(m)=25/12, m*c(m)=25/3. p*(25/3)/rank:
        # 0.01 -> 0.08333, 0.02/2 -> 0.08333, 0.03/3 -> 0.08333, 0.5/4 -> 1.0417 -> 1
        adj, rej = benjamini_yekutieli([0.03, 0.01, 0.5, 0.02], q=0.1)
        assert adj == pytest.approx([0.25 / 3, 0.25 / 3, 1.0, 0.25 / 3])
        assert rej == [True, True, False, True]
        _, rej05 = benjamini_yekutieli([0.03, 0.01, 0.5, 0.02], q=0.05)
        assert rej05 == [False, False, False, False]

    def test_distinct_ranks(self):
        # m=3, m*c(m)=5.5: 0.001*5.5=0.0055, 0.012*5.5/2=0.033, 0.04*5.5/3=0.07333
        adj, rej = benjamini_yekutieli([0.001, 0.04, 0.012], q=0.05)
        assert adj == pytest.approx([0.0055, 0.04 * 5.5 / 3, 0.033])
        assert rej == [True, False, True]

    def test_step_up_rejects_a_hypothesis_above_its_own_threshold(self):
        # m=2, m*c(m)=3. Thresholds at q=0.05: 0.01667, 0.03333.
        # 0.02 misses rank 1's threshold, but 0.021 meets rank 2's, so both go.
        adj, rej = benjamini_yekutieli([0.02, 0.021], q=0.05)
        assert rej == [True, True]
        assert adj == pytest.approx([0.0315, 0.0315])

    def test_stricter_than_benjamini_hochberg(self):
        # BH would reject both (0.03 <= 0.05, 0.04 <= 0.05); BY does not.
        _, rej = benjamini_yekutieli([0.03, 0.04], q=0.05)
        assert rej == [False, False]

    def test_nan_and_empty(self):
        adj, rej = benjamini_yekutieli([float("nan"), 0.001], q=0.05)
        assert math.isnan(adj[0]) and rej == [False, True]
        assert benjamini_yekutieli([], q=0.05) == ([], [])


class TestAltTestOutcomes:
    def test_llm_copying_the_majority_passes(self):
        _, humans = _noisy_humans(seed=3)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        r = alt_test(llm, humans, epsilon=0.1)
        assert r.passed is True
        assert r.winning_rate == 1.0
        assert r.insufficient is None
        assert r.n_annotators == 4 and r.n_items == 60
        assert all(a.rejected for a in r.per_annotator)
        assert all(a.llm_alignment > a.human_alignment for a in r.per_annotator)

    def test_random_llm_fails(self):
        _, humans = _noisy_humans(seed=5)
        rng = random.Random(99)
        llm = {i: rng.randrange(4) for i in humans["h0"]}
        r = alt_test(llm, humans, epsilon=0.2)
        assert r.passed is False
        assert r.winning_rate == 0.0
        assert not any(a.rejected for a in r.per_annotator)
        # Ties count as wins for both sides, so rho^f can sit near 0.5 even
        # for a random LLM; the comparison with rho^h is what separates them.
        assert all(a.llm_advantage < a.human_advantage for a in r.per_annotator)
        assert all(a.llm_alignment < a.human_alignment for a in r.per_annotator)

    def test_to_dict_round_trip(self):
        _, humans = _noisy_humans(seed=3)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        d = alt_test(llm, humans).to_dict()
        assert set(d["per_annotator"][0]) >= {
            "annotator_id", "n_items", "p_value", "p_value_adjusted", "rejected",
            "llm_alignment", "human_alignment",
        }
        assert d["passed"] is True and d["insufficient"] is None


class TestInsufficientData:
    def test_too_few_annotators(self):
        _, humans = _noisy_humans(seed=1, n_ann=2)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        r = alt_test(llm, humans)
        assert r.passed is None and r.winning_rate is None
        assert "needs 3" in r.insufficient
        # Two annotators are allowed when asked for (the paper calls it weaker).
        assert alt_test(llm, humans, min_annotators=2).passed is not None

    def test_too_few_items_per_annotator(self):
        _, humans = _noisy_humans(seed=1, n_items=20)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        r = alt_test(llm, humans)
        assert r.passed is None
        assert "30" in r.insufficient
        assert [s["n_items"] for s in r.skipped_annotators] == [20, 20, 20, 20]

    def test_one_short_annotator_is_skipped_not_fatal(self):
        _, humans = _noisy_humans(seed=1, n_ann=4)
        humans["h3"] = dict(list(humans["h3"].items())[:10])
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        r = alt_test(llm, humans)
        assert r.insufficient is None
        assert r.n_annotators == 3
        assert [s["annotator_id"] for s in r.skipped_annotators] == ["h3"]

    def test_no_overlap_with_llm(self):
        _, humans = _noisy_humans(seed=1)
        r = alt_test({"other": 1}, humans)
        assert r.passed is None and "no items" in r.insufficient

    def test_items_with_one_human_are_dropped(self):
        _, humans = _noisy_humans(seed=1)
        humans["h0"]["solo"] = 1
        llm = {i: _majority(humans, i) for i in humans["h1"]}
        llm["solo"] = 1
        r = alt_test(llm, humans)
        assert r.n_items_dropped == 1 and r.n_items == 60

    def test_none_labels_are_missing(self):
        _, humans = _noisy_humans(seed=1)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        for i in list(llm)[:40]:
            llm[i] = None
        r = alt_test(llm, humans)
        assert r.passed is None and r.n_items == 20

    def test_no_humans(self):
        r = alt_test({"a": 1}, {})
        assert isinstance(r, AltTestResult) and r.passed is None


class TestReferenceParity:
    """Numbers produced by the reference implementation on ``_toy`` data."""

    @pytest.mark.parametrize("seed,wr,ap", [
        (0, 1.0, 0.975),
        (1, 1.0, 0.8875),
        (3, 1.0, 0.9083333333333333),
    ])
    def test_accuracy_toys(self, seed, wr, ap):
        llm, humans = _toy(seed)
        r = alt_test(llm, humans, metric="accuracy", epsilon=0.2)
        assert r.winning_rate == pytest.approx(wr)
        assert r.advantage_probability == pytest.approx(ap)

    def test_accuracy_toy_that_fails(self):
        llm, humans = _toy(0, p_f=0.7)
        r = alt_test(llm, humans, metric="accuracy", epsilon=0.1)
        assert r.winning_rate == 0.0
        assert r.advantage_probability == pytest.approx(0.85)
        assert r.passed is False

    @pytest.mark.parametrize("seed,wr,ap", [
        (1, 0.75, 0.7958333333333334),
        (3, 0.25, 0.7708333333333333),
        (2, 0.0, 0.7250000000000001),
        (7, 1.0, 0.8458333333333334),
    ])
    def test_neg_rmse_toys(self, seed, wr, ap):
        llm, humans = _toy(seed, k=5, numeric=True)
        r = alt_test(llm, humans, metric="neg_rmse", epsilon=0.1)
        assert r.winning_rate == pytest.approx(wr)
        assert r.advantage_probability == pytest.approx(ap)
        assert r.passed is (wr >= 0.5)

    def test_neg_rmse_per_annotator_p_values(self):
        llm, humans = _toy(1, k=5, numeric=True)
        r = alt_test(llm, humans, metric="neg_rmse", epsilon=0.1)
        got = {a.annotator_id: a.p_value for a in r.per_annotator}
        assert got == pytest.approx({
            "a0": 0.004826842700661994,
            "a1": 0.04650811318698718,
            "a2": 0.015867882777538797,
            "a3": 0.0037211702754571217,
        })
        # BY by hand, m=4, m*c(m)=25/3, thresholds rank*0.006 at q=0.05:
        # a3 .0037<=.006, a0 .0048<=.012, a2 .0159<=.018, a1 .0465>.024.
        assert {a.annotator_id: a.rejected for a in r.per_annotator} == {
            "a0": True, "a1": False, "a2": True, "a3": True,
        }


class TestNumericPath:
    def test_llm_at_the_mean_beats_noisy_raters(self):
        rng = random.Random(4)
        truth = {f"i{i}": rng.randint(1, 5) for i in range(50)}
        humans = {
            f"h{j}": {i: max(1, min(5, t + rng.choice([-2, -1, 0, 1, 2]))) for i, t in truth.items()}
            for j in range(4)
        }
        r = alt_test(truth, humans, metric="neg_rmse", epsilon=0.1)
        assert r.passed is True
        assert all(a.llm_alignment > a.human_alignment for a in r.per_annotator)
        assert all(a.llm_alignment <= 0 for a in r.per_annotator)

    def test_far_off_llm_fails(self):
        rng = random.Random(4)
        truth = {f"i{i}": rng.randint(1, 5) for i in range(50)}
        humans = {
            f"h{j}": {i: max(1, min(5, t + rng.choice([-1, 0, 0, 1]))) for i, t in truth.items()}
            for j in range(4)
        }
        llm = {i: 6 - t for i, t in truth.items()}
        assert alt_test(llm, humans, metric="neg_rmse").passed is False

    def test_custom_metric_and_wilcoxon(self):
        _, humans = _noisy_humans(seed=2, n_items=20)
        llm = {i: _majority(humans, i) for i in humans["h0"]}
        r = alt_test(llm, humans, metric=accuracy_alignment, test="wilcoxon",
                     min_items_per_annotator=15, epsilon=0.1)
        assert r.metric == "accuracy_alignment" and r.test == "wilcoxon"
        assert r.passed is True

    def test_bad_arguments(self):
        with pytest.raises(ValueError):
            alt_test({}, {}, metric="f1")
        with pytest.raises(ValueError):
            alt_test({}, {}, test="z")
