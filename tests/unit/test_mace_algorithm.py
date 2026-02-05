"""Tests for the pure MACE algorithm implementation."""

import numpy as np
import pytest

from potato.mace import MACEAlgorithm


class TestMACEAlgorithm:
    """Test the core MACE EM algorithm."""

    def test_perfect_agreement_two_labels(self):
        """When all annotators agree perfectly, predictions should match and competence be high."""
        # 5 items, 3 annotators, 2 labels, all agree
        annotations = np.array([
            [0, 0, 0],
            [1, 1, 1],
            [0, 0, 0],
            [1, 1, 1],
            [0, 0, 0],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=2, num_instances=5,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        # All predictions should match the unanimous labels
        np.testing.assert_array_equal(predicted, [0, 1, 0, 1, 0])

        # All annotators should have high competence
        assert np.all(competence > 0.7), f"Expected high competence, got {competence}"

        # Marginals should be confident (close to 0 or 1)
        assert np.all(marginals.max(axis=1) > 0.8)

    def test_perfect_agreement_three_labels(self):
        """Perfect agreement with 3 label categories."""
        annotations = np.array([
            [0, 0, 0, 0],
            [1, 1, 1, 1],
            [2, 2, 2, 2],
            [0, 0, 0, 0],
            [1, 1, 1, 1],
            [2, 2, 2, 2],
        ])
        mace = MACEAlgorithm(
            num_annotators=4, num_labels=3, num_instances=6,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        np.testing.assert_array_equal(predicted, [0, 1, 2, 0, 1, 2])
        assert np.all(competence > 0.6)

    def test_one_spammer_detected(self):
        """One annotator who always picks label 0 should have lower competence."""
        # 3 good annotators agree, 1 spammer always says 0
        annotations = np.array([
            [0, 0, 0, 0],  # spammer agrees by chance
            [1, 1, 1, 0],  # spammer disagrees
            [0, 0, 0, 0],  # agrees
            [1, 1, 1, 0],  # disagrees
            [0, 0, 0, 0],  # agrees
            [1, 1, 1, 0],  # disagrees
            [0, 0, 0, 0],  # agrees
            [1, 1, 1, 0],  # disagrees
        ])
        mace = MACEAlgorithm(
            num_annotators=4, num_labels=2, num_instances=8,
            num_restarts=10, num_iters=50, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        # Predictions should follow the majority
        np.testing.assert_array_equal(predicted, [0, 1, 0, 1, 0, 1, 0, 1])

        # Spammer (annotator 3) should have lower competence than others
        good_competence = competence[:3].mean()
        spammer_competence = competence[3]
        assert spammer_competence < good_competence, (
            f"Spammer competence {spammer_competence} should be less than "
            f"good annotators {good_competence}"
        )

    def test_missing_annotations_handled(self):
        """Missing annotations (-1) should be handled gracefully."""
        annotations = np.array([
            [0,  0, -1],
            [1, -1,  1],
            [-1, 0,  0],
            [1,  1,  1],
            [0,  0,  0],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=2, num_instances=5,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        # Should produce valid outputs without errors
        assert predicted.shape == (5,)
        assert competence.shape == (3,)
        assert marginals.shape == (5, 2)
        assert np.all(np.isfinite(competence))
        assert np.all(np.isfinite(marginals))

        # Items with full agreement should still be predicted correctly
        assert predicted[3] == 1  # all agree on 1
        assert predicted[4] == 0  # all agree on 0

    def test_all_missing_annotator(self):
        """An annotator with all missing values should get prior competence."""
        annotations = np.array([
            [0, 0, -1],
            [1, 1, -1],
            [0, 0, -1],
            [1, 1, -1],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=2, num_instances=4,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        # Should not crash; predictions based on available data
        assert predicted.shape == (4,)
        assert np.all(np.isfinite(competence))

    def test_entropy_high_for_uncertain(self):
        """Uncertain distributions should have higher entropy than confident ones."""
        # Confident distribution
        confident = np.array([[0.99, 0.01], [0.01, 0.99]])
        # Uncertain distribution
        uncertain = np.array([[0.5, 0.5], [0.5, 0.5]])

        ent_confident = MACEAlgorithm.entropy(confident)
        ent_uncertain = MACEAlgorithm.entropy(uncertain)

        assert np.all(ent_uncertain > ent_confident)

    def test_entropy_zero_for_degenerate(self):
        """A degenerate distribution (all mass on one label) should have ~0 entropy."""
        degenerate = np.array([[1.0, 0.0], [0.0, 1.0]])
        ent = MACEAlgorithm.entropy(degenerate)
        # Not exactly 0 due to EPS clipping, but very small
        assert np.all(ent < 0.01)

    def test_single_annotator(self):
        """Edge case: only 1 annotator. Should still produce valid output."""
        annotations = np.array([[0], [1], [0], [1]])
        mace = MACEAlgorithm(
            num_annotators=1, num_labels=2, num_instances=4,
            num_restarts=3, num_iters=20, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        assert predicted.shape == (4,)
        assert competence.shape == (1,)
        assert np.all(np.isfinite(predicted))
        assert np.all(np.isfinite(competence))

    def test_two_labels_minimum(self):
        """Edge case: minimum 2 labels."""
        annotations = np.array([
            [0, 0],
            [1, 1],
            [0, 1],
        ])
        mace = MACEAlgorithm(
            num_annotators=2, num_labels=2, num_instances=3,
            num_restarts=3, num_iters=20, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        assert predicted.shape == (3,)
        # Agreed items should be predicted correctly
        assert predicted[0] == 0
        assert predicted[1] == 1

    def test_all_same_label(self):
        """When all annotations are the same label, should predict that label."""
        annotations = np.array([
            [0, 0, 0],
            [0, 0, 0],
            [0, 0, 0],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=2, num_instances=3,
            num_restarts=3, num_iters=20, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        np.testing.assert_array_equal(predicted, [0, 0, 0])

    def test_marginals_sum_to_one(self):
        """Marginals should be valid probability distributions (sum to 1)."""
        annotations = np.array([
            [0, 1, 0],
            [1, 0, 1],
            [2, 2, 1],
            [0, 0, 2],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=3, num_instances=4,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        # Each row should sum to 1
        row_sums = marginals.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-6)

    def test_competence_between_zero_and_one(self):
        """Competence scores should be in [0, 1]."""
        annotations = np.array([
            [0, 1, 0, 0],
            [1, 0, 1, 1],
            [0, 0, 0, 1],
            [1, 1, 1, 0],
            [0, 1, 0, 0],
        ])
        mace = MACEAlgorithm(
            num_annotators=4, num_labels=2, num_instances=5,
            num_restarts=5, num_iters=30, seed=42
        )
        predicted, competence, marginals, ll = mace.fit(annotations)

        assert np.all(competence >= 0.0)
        assert np.all(competence <= 1.0)

    def test_reproducible_with_seed(self):
        """Same seed should produce identical results."""
        annotations = np.array([
            [0, 1, 0],
            [1, 0, 1],
            [0, 0, 1],
        ])
        kwargs = dict(
            num_annotators=3, num_labels=2, num_instances=3,
            num_restarts=5, num_iters=30, seed=123
        )

        mace1 = MACEAlgorithm(**kwargs)
        pred1, comp1, marg1, ll1 = mace1.fit(annotations)

        mace2 = MACEAlgorithm(**kwargs)
        pred2, comp2, marg2, ll2 = mace2.fit(annotations)

        np.testing.assert_array_equal(pred1, pred2)
        np.testing.assert_allclose(comp1, comp2)
        np.testing.assert_allclose(marg1, marg2)
        assert ll1 == ll2

    def test_log_likelihood_finite(self):
        """Log-likelihood should be a finite negative number."""
        annotations = np.array([
            [0, 0, 1],
            [1, 1, 0],
            [0, 1, 0],
        ])
        mace = MACEAlgorithm(
            num_annotators=3, num_labels=2, num_instances=3,
            num_restarts=3, num_iters=20, seed=42
        )
        _, _, _, ll = mace.fit(annotations)

        assert np.isfinite(ll)
