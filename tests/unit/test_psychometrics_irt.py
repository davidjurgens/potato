"""Unit tests for the psychometrics IRT model (multiclass GLAD)."""

import numpy as np
import pytest

from potato.psychometrics.irt import IRTModel


def synthetic_observations(
    seed=42,
    n_items=60,
    labels=("neg", "neu", "pos"),
    abilities=None,
    easy_frac=2 / 3,
):
    """Generate observations from the model's own generative process."""
    from scipy.special import expit

    rng = np.random.default_rng(seed)
    K = len(labels)
    if abilities is None:
        abilities = {
            "expert1": 3.0,
            "expert2": 2.5,
            "ok1": 1.0,
            "ok2": 0.8,
            "spammer": 0.0,
        }
    truth = rng.integers(0, K, n_items)
    n_easy = int(n_items * easy_frac)
    easiness = np.array([1.5] * n_easy + [0.35] * (n_items - n_easy))
    observations = []
    for name, theta in abilities.items():
        for i in range(n_items):
            if rng.random() < expit(theta * easiness[i]):
                lab = truth[i]
            else:
                lab = rng.choice([k for k in range(K) if k != truth[i]])
            observations.append((f"item{i:03d}", name, labels[lab]))
    truth_labels = {f"item{i:03d}": labels[truth[i]] for i in range(n_items)}
    return observations, truth_labels, n_easy


class TestFitRecovery:
    def test_recovers_ability_ordering(self):
        observations, _, _ = synthetic_observations()
        model = IRTModel().fit(observations)
        assert model.fitted
        thetas = {a: est.theta for a, est in model.abilities().items()}
        assert thetas["expert1"] > thetas["ok1"] > thetas["spammer"]
        assert thetas["expert2"] > thetas["ok2"] > thetas["spammer"]

    def test_map_labels_at_least_match_majority(self):
        from collections import Counter, defaultdict

        observations, truth_labels, _ = synthetic_observations()
        model = IRTModel().fit(observations)

        votes = defaultdict(Counter)
        for item, _, label in observations:
            votes[item][label] += 1
        majority_correct = sum(
            1 for item, c in votes.items()
            if c.most_common(1)[0][0] == truth_labels[item]
        )
        map_correct = sum(
            1 for item, truth in truth_labels.items()
            if model.item_report(item).map_label == truth
        )
        assert map_correct >= majority_correct
        assert map_correct >= 0.9 * len(truth_labels)

    def test_hard_items_get_higher_difficulty(self):
        observations, _, n_easy = synthetic_observations()
        model = IRTModel().fit(observations)
        difficulties = [
            model.item_report(f"item{i:03d}").difficulty for i in range(60)
        ]
        assert np.mean(difficulties[n_easy:]) > np.mean(difficulties[:n_easy])

    def test_fit_is_deterministic(self):
        observations, _, _ = synthetic_observations()
        m1 = IRTModel().fit(observations)
        m2 = IRTModel().fit(observations)
        assert m1.log_likelihood == m2.log_likelihood
        for ann in m1.annotator_ids():
            assert m1.ability(ann).theta == m2.ability(ann).theta

    def test_ability_se_shrinks_with_more_labels(self):
        # Same generative ability, one annotator sees 3x the items.
        observations, _, _ = synthetic_observations(
            n_items=90, abilities={"a": 1.5, "b": 1.5, "c": 1.5, "d": 1.5}
        )
        few = [o for o in observations if o[1] != "a" or o[0] < "item030"]
        model = IRTModel().fit(few)
        assert model.ability("a").se > model.ability("b").se


class TestDegenerateInputs:
    def test_no_observations(self):
        model = IRTModel().fit([])
        assert not model.fitted
        assert model.degenerate_reason == "no observations"
        assert model.item_report("x") is None
        assert model.abilities() == {}
        assert model.expected_information_gain("x", "y") == 0.0

    def test_single_distinct_label(self):
        model = IRTModel().fit([("i1", "a", "yes"), ("i2", "b", "yes")])
        assert not model.fitted
        assert "fewer than two" in model.degenerate_reason

    def test_duplicate_item_annotator_keeps_last(self):
        observations = [("i1", "a", "yes"), ("i1", "a", "no"), ("i1", "b", "no"),
                        ("i2", "a", "yes"), ("i2", "b", "yes")]
        model = IRTModel().fit(observations)
        assert model.fitted
        assert model.num_observations == 4  # i1/a deduped
        assert model.item_report("i1").map_label == "no"

    def test_unknown_ids_return_none(self):
        observations, _, _ = synthetic_observations(n_items=10)
        model = IRTModel().fit(observations)
        assert model.item_report("nope") is None
        assert model.ability("nobody") is None
        assert model.posterior("nope") is None


class TestReports:
    def test_posterior_sums_to_one_and_band_brackets_prob(self):
        observations, _, _ = synthetic_observations(n_items=30)
        model = IRTModel().fit(observations)
        for item_id in model.item_ids():
            report = model.item_report(item_id)
            assert abs(sum(report.posterior.values()) - 1.0) < 1e-6
            assert report.prob_lo <= report.prob + 1e-9
            assert report.prob_hi >= report.prob - 1e-9
            assert 0.0 <= report.entropy <= np.log2(3) + 1e-9

    def test_discrimination_none_below_three_annotators(self):
        observations = [("i1", "a", "x"), ("i1", "b", "y"),
                        ("i2", "a", "x"), ("i2", "b", "x"),
                        ("i3", "a", "y"), ("i3", "b", "y")]
        model = IRTModel().fit(observations)
        for item_id in model.item_ids():
            assert model.item_report(item_id).discrimination is None
            assert model.item_report(item_id).flagged is False

    def test_flag_follows_threshold(self):
        observations, _, _ = synthetic_observations()
        # Absurdly high threshold: anything with computable discrimination
        # below 0.99 must be flagged — exercises the flag plumbing.
        model = IRTModel(discrimination_flag_threshold=0.99).fit(observations)
        reports = [model.item_report(i) for i in model.item_ids()]
        with_disc = [r for r in reports if r.discrimination is not None]
        assert with_disc, "expected some items with >=3 annotators"
        for r in with_disc:
            assert r.flagged == (r.discrimination < 0.99)


class TestInformationGain:
    def test_expert_gains_more_than_spammer_on_uncertain_item(self):
        observations, _, _ = synthetic_observations()
        model = IRTModel().fit(observations)
        uncertain = max(
            model.item_ids(), key=lambda i: model.item_report(i).entropy
        )
        expert = model.expected_information_gain(uncertain, "expert1")
        spammer = model.expected_information_gain(uncertain, "spammer")
        assert expert > spammer

    def test_resolved_item_gains_less_than_uncertain_item(self):
        observations, _, _ = synthetic_observations()
        model = IRTModel().fit(observations)
        by_entropy = sorted(
            model.item_ids(), key=lambda i: model.item_report(i).entropy
        )
        assert model.expected_information_gain(
            by_entropy[-1], "ok1"
        ) > model.expected_information_gain(by_entropy[0], "ok1")

    def test_unseen_item_and_annotator_are_graceful(self):
        observations, _, _ = synthetic_observations(n_items=10)
        model = IRTModel().fit(observations)
        assert model.expected_information_gain("brand_new_item", "expert1") > 0
        assert model.expected_information_gain("item001", "brand_new_person") >= 0
