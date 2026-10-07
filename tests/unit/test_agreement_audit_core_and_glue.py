"""
Agreement coefficients and the IAA glue, checked against independent
references (scipy, sklearn, statsmodels, hand computation) on the inputs the
earlier tests never used: uneven coverage, unused scale points, variable rater
counts, unanimity, empty answers, a value of 0, and value-carrying widgets.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from potato.server_utils.iaa import dispatcher, drift, nominal, ordinal, ranking
from tests.unit.test_iaa_dispatcher_gathering import (
    FakeUserState, run_report,
)


class TestRankingCorrelatesPositions:
    def test_kendall_tau_is_over_ranks_not_names(self):
        kendalltau = pytest.importorskip("scipy.stats").kendalltau
        a, b = list("ABCED"), list("ABDEC")
        expected = kendalltau([a.index(x) for x in a], [b.index(x) for x in a])[0]
        assert ranking.kendall_tau(a, b) == pytest.approx(expected)  # 0.4
        assert ranking.kendall_tau(a, b) != pytest.approx(0.8)

    def test_renaming_items_does_not_change_tau(self):
        a, b = ["x", "y", "z", "w"], ["y", "x", "w", "z"]
        rename = {"x": "q", "y": "a", "z": "m", "w": "b"}
        assert ranking.kendall_tau(a, b) == pytest.approx(ranking.kendall_tau(
            [rename[i] for i in a], [rename[i] for i in b]))

    def test_footrule_stays_in_range(self):
        assert math.isnan(ranking.spearman_footrule(["x"], ["y"]))
        assert ranking.spearman_footrule(list("abcd"), list("dcba")) == 1.0


class TestWeightedKappaUsesTheWholeScale:
    def test_unused_middle_point_still_counts_as_a_step(self):
        cohen = pytest.importorskip("sklearn.metrics").cohen_kappa_score
        a = [1, 2, 4, 5, 1, 2, 4, 5]
        b = [2, 1, 5, 4, 2, 4, 2, 5]
        for weights in ("linear", "quadratic"):
            expected = cohen(a, b, weights=weights, labels=[1, 2, 3, 4, 5])
            assert ordinal.weighted_kappa(a, b, weights) == pytest.approx(expected)

    def test_declared_ordering_covers_unused_labels(self):
        cohen = pytest.importorskip("sklearn.metrics").cohen_kappa_score
        names = {1: "VL", 2: "L", 3: "M", 4: "H", 5: "VH"}
        order = {"VL": 0, "L": 1, "M": 2, "H": 3, "VH": 4}
        a = [1, 2, 4, 5, 1, 2, 4, 5]
        b = [2, 1, 5, 4, 2, 4, 2, 5]
        assert ordinal.weighted_kappa(
            [names[x] for x in a], [names[x] for x in b], "linear", order
        ) == pytest.approx(cohen(a, b, weights="linear", labels=[1, 2, 3, 4, 5]))


class TestFleissWithVariableRaterCounts:
    ITEMS = [{"a": 2}, {"b": 1, "a": 1}, {"a": 3}, {"b": 2, "a": 1}]

    def test_independent_of_item_order(self):
        assert nominal.fleiss_kappa(self.ITEMS) == pytest.approx(
            nominal.fleiss_kappa(self.ITEMS[::-1]))

    def test_matches_hand_computation(self):
        # P_i over each item's own pairs; marginals pooled over all 10 ratings.
        p_bar = (1 + 0 + 1 + 1 / 3) / 4
        p_e = 0.7 ** 2 + 0.3 ** 2
        assert nominal.fleiss_kappa(self.ITEMS) == pytest.approx(
            (p_bar - p_e) / (1 - p_e))

    def test_equal_counts_match_statsmodels(self):
        sm = pytest.importorskip("statsmodels.stats.inter_rater")
        items = [{"a": 2, "b": 1}, {"a": 1, "b": 2}, {"a": 3}, {"b": 3}, {"a": 2, "b": 1}]
        table = [[d.get("a", 0), d.get("b", 0)] for d in items]
        assert nominal.fleiss_kappa(items) == pytest.approx(sm.fleiss_kappa(table))

    def test_dashboard_fleiss_does_not_rescale_items(self):
        from potato.agreement import fleiss_kappa
        rows = [{"unit": u, "annotator": f"r{j}", "annotation": label}
                for u, labels in enumerate(["aab", "abb", "aaa", "bba", "ab"])
                for j, label in enumerate(labels)]
        # Generalised Fleiss: a 2-rater disagreement has P_i = 0, not 0.25.
        assert fleiss_kappa(pd.DataFrame(rows))["kappa"] == pytest.approx(-0.225)


class TestUndefinedIsNotPerfect:
    def test_unanimous_fleiss_is_nan(self):
        assert math.isnan(nominal.fleiss_kappa([{"x": 3}, {"x": 3}]))

    def test_unanimous_cohen_is_nan(self):
        assert math.isnan(nominal.cohen_kappa(["a", "a"], ["a", "a"]))

    def test_pairwise_mean_skips_undefined_pairs(self):
        from potato.agreement import cohen_kappa_pairwise
        rows = []
        for i, (x, y) in enumerate(zip("abba", "aaba")):
            rows += [{"unit": i, "annotator": "u1", "annotation": x},
                     {"unit": i, "annotator": "u2", "annotation": y},
                     {"unit": i, "annotator": "u3", "annotation": "a"},
                     {"unit": i, "annotator": "u4", "annotation": "a"}]
        result = cohen_kappa_pairwise(pd.DataFrame(rows))
        assert result["mean_kappa"] == pytest.approx(0.1)
        assert result["n_pairs_skipped"] == 1

    def test_report_explains_a_unanimous_schema(self):
        scheme = {"name": "s", "annotation_type": "radio", "labels": ["pos", "neg"]}
        per_user = {u: {f"i{n}": {("s", "pos"): "true"} for n in range(3)}
                    for u in ("u1", "u2")}
        metrics = run_report(per_user, scheme)
        assert math.isnan(metrics["fleiss_kappa"])
        assert metrics["percent_agreement"] == 1.0
        assert "same label" in metrics["note"]


class TestPairsShareItems:
    """Pairwise measures used to pair two annotators' i-th values, which are
    different items as soon as coverage is uneven."""

    @staticmethod
    def _rows():
        rows = {"i1": {"u1": [1], "u3": [1]}}
        for n, v in zip(range(2, 7), range(1, 6)):
            rows[f"i{n}"] = {"u1": [v], "u2": [v]}
        return rows

    def test_continuous(self):
        report = dispatcher._aggregate_continuous(self._rows())
        assert report["mae"] == 0.0
        assert report["rmse"] == 0.0
        assert report["pearson_r"] == pytest.approx(1.0)

    def test_ordinal(self):
        report = dispatcher._aggregate_ordinal(self._rows())
        assert report["weighted_kappa_linear"] == pytest.approx(1.0)
        assert report["weighted_kappa_quadratic"] == pytest.approx(1.0)

    def test_ranking(self):
        x, y = list("abc"), list("cba")
        report = dispatcher._aggregate_ranking(
            {"i1": {"A": x, "B": x}, "i2": {"B": y, "C": y}, "i3": {"A": y, "C": y}})
        assert report["kendall_tau"] == pytest.approx(1.0)
        assert report["spearman_footrule"] == 0.0


class _SpanUser(FakeUserState):
    def __init__(self, spans, saved):
        super().__init__({})
        self.spans, self.saved = spans, saved

    def get_span_annotations(self, iid):
        return self.spans.get(iid, {})

    def has_annotated(self, iid):
        return iid in self.saved


class TestEmptySpanAnswersCount:
    def test_a_missed_entity_is_disagreement(self):
        span = lambda a, b: {"start": a, "end": b, "name": "PER"}
        users = {
            "A": _SpanUser({i: {"ner": [span(n, n + 3)]}
                            for n, i in enumerate(("i1", "i2", "i3"))},
                           {"i1", "i2", "i3"}),
            "B": _SpanUser({"i1": {"ner": [span(0, 3)]}}, {"i1", "i2", "i3"}),
        }
        rows = dispatcher._gather_spans(["i1", "i2", "i3"], users, "ner")
        assert set(rows) == {"i1", "i2", "i3"}
        assert rows["i2"]["B"] == []
        report = dispatcher._aggregate_span(rows, lambda _iid: _Text())
        assert report["span_f1_exact"] == pytest.approx(1 / 3)


class _Text:
    def get_text(self):
        return "x" * 40


class TestValueCarryingWidgets:
    @pytest.mark.parametrize("scheme,expected", [
        ({"annotation_type": "vas"}, dispatcher.SchemaKind.CONTINUOUS),
        ({"annotation_type": "range_slider"}, dispatcher.SchemaKind.MATRIX),
        ({"annotation_type": "semantic_differential"}, dispatcher.SchemaKind.MATRIX),
        ({"annotation_type": "confidence", "scale_type": "slider"},
         dispatcher.SchemaKind.CONTINUOUS),
        ({"annotation_type": "confidence"}, dispatcher.SchemaKind.ORDINAL),
    ])
    def test_classified_by_what_they_store(self, scheme, expected):
        assert dispatcher.classify_schema(scheme) == expected

    def test_vas_disagreement_is_measured(self):
        scheme = {"name": "v", "annotation_type": "vas"}
        a, b = [10, 50, 90], [90, 50, 10]
        per_user = {
            "u1": {f"i{n}": {("v", "v"): str(x)} for n, x in enumerate(a)},
            "u2": {f"i{n}": {("v", "v"): str(x)} for n, x in enumerate(b)},
        }
        metrics = run_report(per_user, scheme)
        assert metrics["mae"] == pytest.approx(160 / 3)

    def test_semantic_differential_scores_each_pair(self):
        scheme = {"name": "sd", "annotation_type": "semantic_differential",
                  "pairs": [["Formal", "Informal"]]}
        a, b = ["1", "4", "7"], ["7", "4", "1"]
        per_user = {
            "u1": {f"i{n}": {("sd", "Formal__Informal"): x} for n, x in enumerate(a)},
            "u2": {f"i{n}": {("sd", "Formal__Informal"): x} for n, x in enumerate(b)},
        }
        metrics = run_report(per_user, scheme)
        pooled = metrics["pooled"]
        value = next(v for k, v in pooled.items() if k.startswith("alpha_"))
        assert value < 0


class TestZeroIsAnAnswer:
    def test_slider_zero_keeps_the_item(self):
        scheme = {"name": "s", "annotation_type": "slider"}
        a, b = [10, 50, 90, 0], [12, 48, 88, 95]
        per_user = {
            "u1": {f"i{n}": {("s", "s"): str(x)} for n, x in enumerate(a)},
            "u2": {f"i{n}": {("s", "s"): str(x)} for n, x in enumerate(b)},
        }
        metrics = run_report(per_user, scheme)
        assert metrics["mae"] == pytest.approx((2 + 2 + 2 + 95) / 4)


class TestDrift:
    def test_a_defined_none_latest_window_fires_nothing(self):
        series = {"s": {"baseline": 0.8, "metric": "alpha_nominal", "points": [
            {"window": 0, "value": 0.85, "sparse": False, "n_items": 10},
            {"window": 1, "value": 0.40, "sparse": False, "n_items": 10},
            {"window": 2, "value": None, "sparse": False, "n_items": 10},
        ]}}
        assert drift._find_drops(series, [], 0.15) == []

    @pytest.mark.parametrize("report,name", [
        ({"pooled": {"alpha_ordinal": 0.6}}, "pooled.alpha_ordinal"),
        ({"alpha": 0.5}, "alpha"),
        ({"detection": {"alpha": 0.4}}, "detection.alpha"),
    ])
    def test_every_report_shape_has_a_headline(self, report, name):
        assert drift.headline_metric(report)[0] == name
