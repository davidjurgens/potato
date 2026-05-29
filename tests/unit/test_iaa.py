"""
Unit tests for the IAA metrics package.

Each metric is exercised on small hand-computed examples so failures
are interpretable. Span tests cover both the nominal-by-position metrics
(BIO-kappa, alpha_U) and the dedicated set-alignment metrics (F1, gamma).
"""

from __future__ import annotations

import math

import pytest

from potato.server_utils.iaa import (
    nominal,
    ordinal,
    continuous,
    multilabel,
    ranking,
    span,
    alpha,
    classify_schema,
    metrics_for_schema,
    SchemaKind,
)


def isclose(a, b, tol=1e-3):
    return math.isclose(a, b, abs_tol=tol)


# ---------------------------------------------------------------------------
# Nominal
# ---------------------------------------------------------------------------

class TestNominal:
    def test_percent_agreement_perfect(self):
        assert nominal.percent_agreement(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_percent_agreement_partial(self):
        assert isclose(
            nominal.percent_agreement(["a", "b", "c", "d"], ["a", "x", "c", "y"]), 0.5
        )

    def test_cohen_kappa_perfect(self):
        assert nominal.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0

    def test_cohen_kappa_inverse(self):
        # Two annotators perfectly inverting each other -> negative kappa
        k = nominal.cohen_kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"])
        assert k < 0

    def test_fleiss_kappa_unanimous(self):
        # 4 items, 3 raters, all agree on category 'a'
        items = [{"a": 3}, {"a": 3}, {"a": 3}, {"a": 3}]
        # Marginal probability is 1.0 → degenerate; convention: 1.0 when observed agreement is 1.0.
        assert nominal.fleiss_kappa(items) == 1.0

    def test_fleiss_kappa_mixed(self):
        # 4 items, 3 raters: 3a, 3b, 2a/1b, 1a/2b → some agreement above chance
        items = [{"a": 3}, {"b": 3}, {"a": 2, "b": 1}, {"a": 1, "b": 2}]
        k = nominal.fleiss_kappa(items)
        assert 0 < k < 1


# ---------------------------------------------------------------------------
# Ordinal
# ---------------------------------------------------------------------------

class TestOrdinal:
    def test_weighted_kappa_perfect(self):
        assert isclose(
            ordinal.weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], weights="quadratic"),
            1.0,
        )

    def test_weighted_kappa_near_miss_better_than_unweighted(self):
        # Near misses on ordinal scale -> weighted kappa > raw Cohen kappa
        a = [1, 2, 3, 4, 5]
        b = [1, 2, 3, 4, 4]  # one off-by-one
        w = ordinal.weighted_kappa(a, b, weights="quadratic")
        c = nominal.cohen_kappa(a, b)
        assert w > c

    def test_spearman_rho_monotone(self):
        rho = ordinal.spearman_rho([1, 2, 3, 4], [1, 2, 3, 4])
        assert isclose(rho, 1.0)


# ---------------------------------------------------------------------------
# Continuous
# ---------------------------------------------------------------------------

class TestContinuous:
    def test_pearson_perfect(self):
        assert isclose(continuous.pearson_r([1, 2, 3], [2, 4, 6]), 1.0)

    def test_mae(self):
        assert isclose(continuous.mae([1.0, 2.0, 3.0], [1.0, 2.0, 5.0]), 2 / 3)

    def test_rmse_zero(self):
        assert continuous.rmse([1, 2, 3], [1, 2, 3]) == 0.0

    def test_icc_2_k_high_agreement(self):
        matrix = [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]]
        assert continuous.icc_2_k(matrix) > 0.99

    def test_icc_2_k_lower_for_noisy_ratings(self):
        # Two raters that disagree noisily -> lower ICC than perfect agreement
        high = continuous.icc_2_k([[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]])
        noisy = continuous.icc_2_k([[1, 2], [2, 5], [3, 1], [4, 3], [5, 4]])
        assert high > noisy


# ---------------------------------------------------------------------------
# Multilabel
# ---------------------------------------------------------------------------

class TestMultilabel:
    def test_jaccard_identical(self):
        assert multilabel.jaccard_distance({"a", "b"}, {"a", "b"}) == 0.0

    def test_jaccard_disjoint(self):
        assert multilabel.jaccard_distance({"a"}, {"b"}) == 1.0

    def test_masi_subset(self):
        # MASI rewards monotone (subset) disagreement
        assert (
            multilabel.masi_distance({"a"}, {"a", "b"})
            < multilabel.masi_distance({"a"}, {"c"})
        )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_kendall_tau_perfect(self):
        assert isclose(ranking.kendall_tau([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)

    def test_spearman_footrule_zero(self):
        assert ranking.spearman_footrule([1, 2, 3], [1, 2, 3]) == 0.0

    def test_spearman_footrule_reversed(self):
        # Worst case
        d = ranking.spearman_footrule([1, 2, 3, 4], [4, 3, 2, 1])
        assert 0.5 < d <= 1.0


# ---------------------------------------------------------------------------
# Alpha
# ---------------------------------------------------------------------------

class TestAlpha:
    def test_alpha_nominal_perfect(self):
        long_format = [
            ("u1", "i1", "a"), ("u2", "i1", "a"),
            ("u1", "i2", "b"), ("u2", "i2", "b"),
            ("u1", "i3", "a"), ("u2", "i3", "a"),
        ]
        assert isclose(alpha.krippendorff_alpha(long_format, level="nominal"), 1.0)

    def test_alpha_ordinal_reasonable(self):
        long_format = [
            ("u1", "i1", 1), ("u2", "i1", 1),
            ("u1", "i2", 2), ("u2", "i2", 3),
            ("u1", "i3", 4), ("u2", "i3", 5),
            ("u1", "i4", 5), ("u2", "i4", 5),
        ]
        a = alpha.krippendorff_alpha(long_format, level="ordinal")
        assert a == a  # not NaN
        assert -1.0 <= a <= 1.0


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------

class TestSpan:
    def test_spans_to_bio(self):
        tags = span.spans_to_bio([(0, 3, "X"), (5, 8, "Y")], length=10)
        assert tags == ["B-X", "I-X", "I-X", "O", "O", "B-Y", "I-Y", "I-Y", "O", "O"]

    def test_token_level_kappa_perfect(self):
        spans_by_user = {
            "u1": [(0, 3, "X")],
            "u2": [(0, 3, "X")],
        }
        assert isclose(span.token_level_kappa(spans_by_user, length=5), 1.0)

    def test_span_f1_exact_match(self):
        p, r, f = span.span_f1_exact([(0, 3, "X")], [(0, 3, "X")])
        assert (p, r, f) == (1.0, 1.0, 1.0)

    def test_span_f1_exact_label_mismatch(self):
        # Boundaries match but label differs → exact match fails
        p, r, f = span.span_f1_exact([(0, 3, "X")], [(0, 3, "Y")])
        assert (p, r, f) == (0.0, 0.0, 0.0)

    def test_span_f1_partial_overlap(self):
        # 50% overlap should count under default threshold=0.5
        p, r, f = span.span_f1_partial([(0, 4, "X")], [(2, 6, "X")], threshold=0.5)
        assert f > 0

    def test_alpha_u_perfect(self):
        spans_by_user = {
            "u1": [(0, 3, "X")],
            "u2": [(0, 3, "X")],
        }
        au = span.krippendorff_alpha_u(spans_by_user, length=10)
        assert isclose(au, 1.0)

    def test_alpha_u_partial_disagreement(self):
        spans_by_user = {
            "u1": [(0, 3, "X")],
            "u2": [(0, 4, "X")],  # one extra character
        }
        au = span.krippendorff_alpha_u(spans_by_user, length=10)
        # Mostly agree -> high alpha
        assert au > 0.5

    def test_gamma_perfect(self):
        spans_by_user = {
            "u1": [(0, 3, "X"), (5, 8, "Y")],
            "u2": [(0, 3, "X"), (5, 8, "Y")],
        }
        g = span.gamma(spans_by_user, length=10, n_samples=10, seed=1)
        assert isclose(g, 1.0)

    def test_gamma_handles_unequal_counts(self):
        # One annotator marks two spans, the other marks one
        spans_by_user = {
            "u1": [(0, 3, "X"), (5, 8, "Y")],
            "u2": [(0, 3, "X")],
        }
        g = span.gamma(spans_by_user, length=10, n_samples=10, seed=1)
        assert -1.0 <= g <= 1.0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_classify_radio_is_nominal(self):
        assert classify_schema({"annotation_type": "radio", "name": "x"}) == SchemaKind.NOMINAL

    def test_classify_likert_is_ordinal(self):
        assert classify_schema({"annotation_type": "likert", "name": "x"}) == SchemaKind.ORDINAL

    def test_classify_slider_is_continuous(self):
        assert classify_schema({"annotation_type": "slider", "name": "x"}) == SchemaKind.CONTINUOUS

    def test_classify_multiselect_max1_is_nominal(self):
        scheme = {"annotation_type": "multiselect", "name": "x", "max_choices": 1}
        assert classify_schema(scheme) == SchemaKind.NOMINAL

    def test_classify_multiselect_default_is_multilabel(self):
        assert classify_schema({"annotation_type": "multiselect", "name": "x"}) == SchemaKind.MULTILABEL

    def test_classify_span_is_span(self):
        assert classify_schema({"annotation_type": "span", "name": "x"}) == SchemaKind.SPAN

    def test_metrics_for_span_contains_gamma(self):
        ms = metrics_for_schema({"annotation_type": "span", "name": "x"})
        assert "gamma_mathet" in ms
        assert "krippendorff_alpha_u" in ms
        assert "span_f1_partial" in ms

    def test_metrics_for_textbox_is_empty(self):
        assert metrics_for_schema({"annotation_type": "textbox", "name": "x"}) == []
