"""
Agreement for schemes whose stored answer is several answers, and for scales
whose labels are words rather than numbers.

Two bugs from the audit-10 pass, both of which reported a plausible number
rather than failing:

1. ``multirate`` was classified CONTINUOUS. Its store is ``{row_name: label}``,
   so the numeric reader was handed the row name "Urgency" and the label "Low"
   and could make a number of neither -- the report said ``n_annotators: 0``
   over a study where both annotators rated every row of every item, which on
   a dashboard reads as "nobody answered this". ``constant_sum`` and
   ``soft_label`` share the shape and fared differently but no better: they
   scored their *first* option and called the result the scheme.

2. Every ordinal measure ranked word labels by sorting them. On the canonical
   ``[Low, Medium, High]`` that gives High < Low < Medium, and Krippendorff's
   ordinal distance degraded further still -- it cannot parse "Serious", so it
   fell back to the nominal 0-or-1 distance and ``alpha_ordinal`` was the
   nominal alpha under another name.
"""

from __future__ import annotations

import math

import pytest

from potato.server_utils.iaa import dispatcher, ordinal


MULTIRATE = {
    "name": "handling",
    "annotation_type": "multirate",
    "options": ["Reproducibility", "Customer tone", "Urgency"],
    "labels": ["Low", "Medium", "High"],
}

CONSTANT_SUM = {
    "name": "budget",
    "annotation_type": "constant_sum",
    "options": ["A", "B", "C"],
}

LABELLED_LIKERT = {
    "name": "severity",
    "annotation_type": "likert",
    "labels": ["Trivial", "Minor", "Serious", "Critical", "Blocker"],
}


def matrix_rows(pairs):
    """``{item: {user: {sub_key: value}}}`` from a list of (alice, bob)."""
    return {f"i{i}": {"alice": a, "bob": b} for i, (a, b) in enumerate(pairs)}


class TestMatrixIsScoredAtAll:
    def test_multirate_classifies_as_matrix(self):
        assert dispatcher.classify_schema(MULTIRATE) is dispatcher.SchemaKind.MATRIX

    def test_multirate_reports_annotators_and_items(self):
        """The reported bug: n_annotators 0 over a fully-rated study."""
        rows = matrix_rows([
            ({"Reproducibility": "Medium", "Customer tone": "High",
              "Urgency": "Low"},
             {"Reproducibility": "Medium", "Customer tone": "High",
              "Urgency": "Medium"}),
            ({"Reproducibility": "Low", "Customer tone": "Low",
              "Urgency": "High"},
             {"Reproducibility": "Low", "Customer tone": "Medium",
              "Urgency": "High"}),
            ({"Reproducibility": "High", "Customer tone": "Low",
              "Urgency": "Low"},
             {"Reproducibility": "High", "Customer tone": "Low",
              "Urgency": "Low"}),
        ])
        metrics = dispatcher._aggregate_matrix(rows, MULTIRATE)

        assert metrics["n_annotators"] == 2
        assert metrics["n_items"] == 3
        assert metrics["n_rows"] == 3
        assert metrics["pooled"]["alpha_ordinal"] > 0.5

    def test_every_declared_row_gets_its_own_number(self):
        """The reason to prefer this widget over N likerts is per-row detail."""
        rows = matrix_rows([
            # They agree perfectly about Urgency and never about tone.
            ({"Customer tone": "Low", "Urgency": "High"},
             {"Customer tone": "High", "Urgency": "High"}),
            ({"Customer tone": "High", "Urgency": "Low"},
             {"Customer tone": "Low", "Urgency": "Low"}),
            ({"Customer tone": "Low", "Urgency": "Medium"},
             {"Customer tone": "High", "Urgency": "Medium"}),
        ])
        metrics = dispatcher._aggregate_matrix(rows, MULTIRATE)

        assert metrics["Urgency"]["alpha_ordinal"] == pytest.approx(1.0)
        assert metrics["Customer tone"]["alpha_ordinal"] < 0.0

    def test_rows_appear_in_declared_order(self):
        rows = matrix_rows([
            ({"Urgency": "Low", "Reproducibility": "High"},
             {"Urgency": "Low", "Reproducibility": "High"}),
            ({"Urgency": "High", "Reproducibility": "Low"},
             {"Urgency": "High", "Reproducibility": "Low"}),
        ])
        metrics = dispatcher._aggregate_matrix(rows, MULTIRATE)
        groups = [k for k in metrics if k in ("Reproducibility", "Urgency")]
        assert groups == ["Reproducibility", "Urgency"]

    def test_pooled_unit_is_item_times_row(self):
        """Two annotators, 3 items, 2 rows is 6 judgements, not 3."""
        rows = matrix_rows([
            ({"Customer tone": "Low", "Urgency": "High"},
             {"Customer tone": "Low", "Urgency": "High"}),
            ({"Customer tone": "High", "Urgency": "Low"},
             {"Customer tone": "High", "Urgency": "Low"}),
            ({"Customer tone": "Low", "Urgency": "Medium"},
             {"Customer tone": "Medium", "Urgency": "Medium"}),
        ])
        metrics = dispatcher._aggregate_matrix(rows, MULTIRATE)
        assert metrics["pooled"]["n_items"] == 6

    def test_nothing_to_compare_says_so(self):
        """A schema only one annotator answered must not report a number."""
        rows = {"i0": {"alice": {"Urgency": "Low"}}}
        metrics = dispatcher._aggregate_matrix(rows, MULTIRATE)
        assert metrics["n_rows"] == 0
        assert "nothing to compare" in metrics["note"]


class TestMatrixNumericShape:
    def test_constant_sum_scores_every_option_not_just_the_first(self):
        rows = matrix_rows([
            ({"A": 50, "B": 30, "C": 20}, {"A": 45, "B": 35, "C": 20}),
            ({"A": 10, "B": 10, "C": 80}, {"A": 20, "B": 10, "C": 70}),
            ({"A": 33, "B": 33, "C": 34}, {"A": 30, "B": 40, "C": 30}),
        ])
        metrics = dispatcher._aggregate_matrix(rows, CONSTANT_SUM)

        assert metrics["scale"] == "interval"
        assert metrics["n_rows"] == 3
        # Every option, not just "A" -- the old reader took v[0] and stopped.
        for option in ("A", "B", "C"):
            assert not math.isnan(metrics[option]["alpha_interval"])
        assert metrics["pooled"]["n_items"] == 9

    def test_scale_is_read_from_the_values_not_the_type(self):
        """A multirate over numeric labels is interval, not ordinal."""
        numeric = dict(MULTIRATE, labels=[1, 2, 3])
        rows = matrix_rows([
            ({"Urgency": 1}, {"Urgency": 2}),
            ({"Urgency": 3}, {"Urgency": 3}),
        ])
        assert dispatcher._aggregate_matrix(rows, numeric)["scale"] == "interval"


class TestOrdinalUsesTheDeclaredScale:
    def test_low_medium_high_is_not_sorted_alphabetically(self):
        """Lexically High < Low < Medium, so Low->Medium looks like 2 steps."""
        ordering = dispatcher._scale_ordering(MULTIRATE)
        assert ordering == {"Low": 0, "Medium": 1, "High": 2}

    def test_labelled_likert_alpha_is_ordinal_not_nominal(self):
        """Krippendorff's ordinal distance cannot parse "Serious".

        Left as label names it falls through to the nominal 0-or-1 distance, so
        a one-step disagreement and a four-step one were penalised the same.
        """
        rows = {f"i{i}": {"a": [x], "b": [y]} for i, (x, y) in enumerate(
            [("Minor", "Serious"), ("Serious", "Serious"),
             ("Critical", "Blocker"), ("Trivial", "Minor"),
             ("Blocker", "Critical"), ("Minor", "Minor")])}

        declared = dispatcher._aggregate_ordinal(
            rows, dispatcher._scale_ordering(LABELLED_LIKERT))
        lexical = dispatcher._aggregate_ordinal(rows)

        # Every disagreement here is one step, so the declared order must score
        # it far higher than the alphabetical accident does.
        assert declared["alpha_ordinal"] > 0.5
        assert lexical["alpha_ordinal"] < 0.3
        assert declared["weighted_kappa_linear"] > lexical["weighted_kappa_linear"]

    def test_no_labels_block_means_no_ordering(self):
        assert dispatcher._scale_ordering({"annotation_type": "likert"}) is None
        assert dispatcher._scale_ordering({"labels": ["only-one"]}) is None

    def test_numeric_labels_are_left_alone(self):
        """A 1-5 likert already ranks correctly; ordering must not disturb it."""
        scheme = {"annotation_type": "likert", "labels": [1, 2, 3, 4, 5]}
        rows = {f"i{i}": {"a": [x], "b": [y]} for i, (x, y) in enumerate(
            [("1", "2"), ("3", "3"), ("5", "4"), ("2", "2")])}
        with_ordering = dispatcher._aggregate_ordinal(
            rows, dispatcher._scale_ordering(scheme))
        without = dispatcher._aggregate_ordinal(rows)
        assert with_ordering["alpha_ordinal"] == pytest.approx(
            without["alpha_ordinal"])


class TestOrdinalRankMapIsShared:
    def test_two_annotators_are_ranked_on_one_scale(self):
        """Each sequence used to be ranked against its own sorted label set.

        An annotator who only ever said "high" or "low" got a different map
        from one who also said "mid", so the two numbers being compared were
        not on the same scale -- the kappa was not wrong by a little, it was
        a comparison of two different quantities.
        """
        a = ["low", "low", "high", "high"]
        b = ["low", "mid", "high", "high"]
        rank = ordinal._shared_rank(a, b, None)
        assert rank == {"high": 0, "low": 1, "mid": 2}
        assert ordinal._coerce_ordinal(a, dict(rank)) == [1, 1, 0, 0]
        assert ordinal._coerce_ordinal(b, dict(rank)) == [1, 2, 0, 0]

    def test_an_undeclared_label_is_placed_after_the_scale(self):
        """A renamed or legacy option must not be dropped silently."""
        ranked = ordinal._coerce_ordinal(
            ["Low", "High", "Retired"], {"Low": 0, "Medium": 1, "High": 2})
        assert ranked == [0, 2, 3]
