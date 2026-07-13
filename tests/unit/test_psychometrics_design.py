"""Unit tests for the psychometrics study designer (power analysis)."""

import numpy as np
import pytest

from potato.psychometrics.design import (
    nominal_alpha,
    power_analysis,
    simulate_responses,
)


class TestNominalAlpha:
    @pytest.mark.parametrize(
        "num_classes,m,accuracy", [(2, 3, 0.8), (3, 5, 0.6), (4, 2, 0.9)]
    )
    def test_matches_simpledorff(self, num_classes, m, accuracy):
        pd = pytest.importorskip("pandas")
        from simpledorff import calculate_krippendorffs_alpha_for_df

        rng = np.random.default_rng(7)
        _, responses = simulate_responses(150, m, accuracy, num_classes, rng)
        fast = nominal_alpha(responses, num_classes)

        rows = [
            (i, j, responses[i, j])
            for i in range(responses.shape[0])
            for j in range(m)
        ]
        df = pd.DataFrame(rows, columns=["e", "a", "c"])
        reference = calculate_krippendorffs_alpha_for_df(
            df, experiment_col="e", annotator_col="a", class_col="c"
        )
        assert fast == pytest.approx(reference, abs=1e-9)

    def test_perfect_agreement_is_degenerate(self):
        responses = np.zeros((50, 3), dtype=int)
        assert np.isnan(nominal_alpha(responses, 2))

    def test_single_annotator_is_nan(self):
        assert np.isnan(nominal_alpha(np.zeros((10, 1), dtype=int), 2))


class TestPowerAnalysis:
    def test_ci_width_shrinks_with_redundancy(self):
        report = power_analysis(
            n_items=200, annotator_accuracy=0.75, num_classes=3,
            max_annotators=6, n_simulations=40,
        )
        widths = {r.annotators_per_item: r.alpha_ci_width for r in report.rows}
        assert widths[6] < widths[2]

    def test_majority_accuracy_grows_with_redundancy(self):
        report = power_analysis(
            n_items=200, annotator_accuracy=0.7, num_classes=2,
            max_annotators=7, n_simulations=40,
        )
        accs = {r.annotators_per_item: r.majority_accuracy for r in report.rows}
        assert accs[7] > accs[2]

    def test_recommendation_meets_target(self):
        report = power_analysis(
            n_items=300, annotator_accuracy=0.8, num_classes=2,
            target_ci_width=0.12, n_simulations=40,
        )
        assert report.recommended is not None
        row = next(
            r for r in report.rows if r.annotators_per_item == report.recommended
        )
        assert row.alpha_ci_width <= 0.12
        # It must be the SMALLEST qualifying m.
        for r in report.rows:
            if r.annotators_per_item < report.recommended:
                assert r.alpha_ci_width > 0.12

    def test_cost_column(self):
        report = power_analysis(
            n_items=100, annotator_accuracy=0.8, num_classes=2,
            max_annotators=3, n_simulations=20, cost_per_judgment=0.10,
        )
        for r in report.rows:
            assert r.cost == pytest.approx(100 * r.annotators_per_item * 0.10)

    def test_deterministic_given_seed(self):
        kwargs = dict(
            n_items=100, annotator_accuracy=0.7, num_classes=3,
            max_annotators=3, n_simulations=20, seed=5,
        )
        assert power_analysis(**kwargs).to_dict() == power_analysis(**kwargs).to_dict()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"n_items": 1, "annotator_accuracy": 0.8},
            {"n_items": 100, "annotator_accuracy": 0.0},
            {"n_items": 100, "annotator_accuracy": 1.5},
            {"n_items": 100, "annotator_accuracy": 0.8, "num_classes": 1},
            {"n_items": 100, "annotator_accuracy": 0.8, "min_annotators": 1},
            {"n_items": 100, "annotator_accuracy": 0.8, "max_annotators": 1},
            {"n_items": 100, "annotator_accuracy": 0.8, "n_simulations": 5},
        ],
    )
    def test_validation_errors(self, kwargs):
        with pytest.raises(ValueError):
            power_analysis(**kwargs)
