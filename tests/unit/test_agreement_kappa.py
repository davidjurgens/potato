"""Unit tests for Cohen's kappa and Fleiss' kappa helpers in potato.agreement."""

import pandas as pd
import pytest

from potato.agreement import (
    cohen_kappa_pairwise,
    fleiss_kappa,
    interpret_kappa,
)


def _df(rows):
    return pd.DataFrame(rows, columns=["unit", "annotator", "annotation"])


class TestCohenKappaPairwise:
    def test_perfect_agreement_two_raters(self):
        df = _df([
            ("i1", "a", "yes"), ("i1", "b", "yes"),
            ("i2", "a", "no"),  ("i2", "b", "no"),
            ("i3", "a", "yes"), ("i3", "b", "yes"),
            ("i4", "a", "no"),  ("i4", "b", "no"),
        ])
        result = cohen_kappa_pairwise(df)
        assert result["n_pairs_evaluated"] == 1
        assert result["mean_kappa"] == 1.0
        assert result["pairs"][0]["n_items"] == 4

    def test_disagreement_two_raters(self):
        df = _df([
            ("i1", "a", "yes"), ("i1", "b", "no"),
            ("i2", "a", "no"),  ("i2", "b", "yes"),
            ("i3", "a", "yes"), ("i3", "b", "no"),
            ("i4", "a", "no"),  ("i4", "b", "yes"),
        ])
        result = cohen_kappa_pairwise(df)
        # Systematic flipping is worse-than-chance agreement -> kappa < 0
        assert result["mean_kappa"] is not None
        assert result["mean_kappa"] < 0

    def test_three_raters_averages_pairs(self):
        df = _df([
            ("i1", "a", "x"), ("i1", "b", "x"), ("i1", "c", "x"),
            ("i2", "a", "y"), ("i2", "b", "y"), ("i2", "c", "y"),
            ("i3", "a", "x"), ("i3", "b", "x"), ("i3", "c", "x"),
            ("i4", "a", "y"), ("i4", "b", "y"), ("i4", "c", "y"),
        ])
        result = cohen_kappa_pairwise(df)
        assert result["n_pairs_evaluated"] == 3  # (a,b), (a,c), (b,c)
        assert result["mean_kappa"] == 1.0

    def test_skips_pairs_without_shared_items(self):
        df = _df([
            ("i1", "a", "x"), ("i2", "a", "y"),
            ("i3", "b", "x"), ("i4", "b", "y"),
        ])
        result = cohen_kappa_pairwise(df)
        assert result["n_pairs_evaluated"] == 0
        assert result["n_pairs_skipped"] == 1
        assert result["mean_kappa"] is None

    def test_empty_dataframe_returns_no_pairs(self):
        df = _df([])
        result = cohen_kappa_pairwise(df)
        assert result["mean_kappa"] is None
        assert result["n_pairs_evaluated"] == 0


class TestFleissKappa:
    def test_perfect_agreement(self):
        df = _df([
            ("i1", "a", "x"), ("i1", "b", "x"), ("i1", "c", "x"),
            ("i2", "a", "y"), ("i2", "b", "y"), ("i2", "c", "y"),
            ("i3", "a", "x"), ("i3", "b", "x"), ("i3", "c", "x"),
            ("i4", "a", "y"), ("i4", "b", "y"), ("i4", "c", "y"),
        ])
        result = fleiss_kappa(df)
        assert result["kappa"] == 1.0
        assert result["n_raters"] == 3
        assert result["n_items_evaluated"] == 4
        assert result["n_categories"] == 2

    def test_no_agreement_above_chance(self):
        # Two categories, three raters; each item randomly split -> kappa ~ 0
        df = _df([
            ("i1", "a", "x"), ("i1", "b", "y"), ("i1", "c", "x"),
            ("i2", "a", "y"), ("i2", "b", "x"), ("i2", "c", "y"),
            ("i3", "a", "x"), ("i3", "b", "y"), ("i3", "c", "x"),
            ("i4", "a", "y"), ("i4", "b", "x"), ("i4", "c", "y"),
        ])
        result = fleiss_kappa(df)
        assert result["kappa"] is not None
        # Roughly chance-level: |kappa| should be small
        assert -0.5 < result["kappa"] < 0.5

    def test_drops_items_with_single_rater(self):
        df = _df([
            ("i1", "a", "x"),  # only one rater on i1 -> dropped
            ("i2", "a", "y"), ("i2", "b", "y"),
            ("i3", "a", "x"), ("i3", "b", "x"),
        ])
        result = fleiss_kappa(df)
        assert result["n_items_evaluated"] == 2

    def test_empty_dataframe(self):
        df = _df([])
        result = fleiss_kappa(df)
        assert result["kappa"] is None
        assert result["n_items_evaluated"] == 0


class TestInterpretKappa:
    @pytest.mark.parametrize("k,expected", [
        (-0.1, "Worse than chance"),
        (0.10, "Slight"),
        (0.30, "Fair"),
        (0.50, "Moderate"),
        (0.70, "Substantial"),
        (0.95, "Almost perfect"),
        (None, "No agreement computable"),
    ])
    def test_bands(self, k, expected):
        assert interpret_kappa(k) == expected
