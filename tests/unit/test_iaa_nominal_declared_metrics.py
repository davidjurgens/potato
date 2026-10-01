"""The nominal agreement report emits what it declares, under partial overlap too.

``metrics_for_schema`` declared ``percent_agreement`` and ``cohen_kappa`` for
nominal schemes, and ``docs/advanced/heterogeneous_coverage.md`` listed both,
but ``_aggregate_nominal`` emitted neither. Its only kappa,
``pairwise_cohen_kappa``, was computed over the items EVERY annotator rated,
which under heterogeneous coverage is often no item at all, so it came back
NaN for studies where every pair of annotators had items in common.

Expected values here are worked by hand in the comments, not read back from
the functions under test.
"""

import math
import warnings

import pytest

from potato.server_utils.iaa import dispatcher, nominal, presentation


def _rows(table):
    """``{item: {annotator: label}}`` -> the dispatcher's list-valued rows."""
    return {iid: {u: [v] for u, v in by_user.items()} for iid, by_user in table.items()}


# Everyone rated everything.
#   i1  a=x b=x c=y
#   i2  a=y b=y c=y
#   i3  a=x b=y c=x
FULL = {
    "i1": {"a": "x", "b": "x", "c": "y"},
    "i2": {"a": "y", "b": "y", "c": "y"},
    "i3": {"a": "x", "b": "y", "c": "x"},
}

# No item was rated by all three, but pairs (a,b) and (b,c) each share two
# items and agree on both, with two labels in play.
PARTIAL = {
    "i1": {"a": "x", "b": "x"},
    "i2": {"a": "y", "b": "y"},
    "i3": {"b": "x", "c": "x"},
    "i4": {"b": "y", "c": "y"},
}


class TestDeclaredMetricsAreEmitted:
    @pytest.mark.parametrize("annotation_type, aggregate, table", [
        ("radio", dispatcher._aggregate_nominal,
         _rows(FULL)),
        ("likert", dispatcher._aggregate_ordinal,
         _rows({"i1": {"a": "1", "b": "2"}, "i2": {"a": "3", "b": "3"},
                "i3": {"a": "5", "b": "4"}})),
        ("slider", dispatcher._aggregate_continuous,
         _rows({"i1": {"a": 1.0, "b": 2.0}, "i2": {"a": 3.0, "b": 3.5},
                "i3": {"a": 5.0, "b": 4.0}})),
        ("multiselect", dispatcher._aggregate_multilabel,
         {"i1": {"a": ["x", "y"], "b": ["x"]}, "i2": {"a": ["y"], "b": ["y"]},
          "i3": {"a": ["x"], "b": ["x", "y"]}}),
        ("ranking", dispatcher._aggregate_ranking,
         {"i1": {"a": ["p", "q", "r"], "b": ["q", "p", "r"]},
          "i2": {"a": ["r", "q", "p"], "b": ["r", "p", "q"]}}),
    ])
    def test_every_declared_name_is_in_the_report(self, annotation_type,
                                                  aggregate, table):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            report = aggregate(table)
        declared = dispatcher.metrics_for_schema(
            {"annotation_type": annotation_type, "name": "x"})
        missing = [name for name in declared if name not in report]
        assert not missing, f"{annotation_type} declares but never emits {missing}"


class TestTheValues:
    def test_percent_agreement_full_coverage(self):
        # Per item, the share of annotator pairs that agree:
        #   i1: ab yes, ac no, bc no -> 1/3;  i2: all -> 1;  i3: ac only -> 1/3
        # Mean (1/3 + 1 + 1/3) / 3 = 5/9.
        report = dispatcher._aggregate_nominal(_rows(FULL))
        assert report["percent_agreement"] == pytest.approx(5 / 9)

    def test_cohen_kappa_full_coverage(self):
        # (a,b): a=[x,y,x] b=[x,y,y]  po=2/3 pe=(2*1+1*2)/9=4/9  k=0.4
        # (a,c): a=[x,y,x] c=[y,y,x]  po=2/3 pe=4/9              k=0.4
        # (b,c): b=[x,y,y] c=[y,y,x]  po=1/3 pe=(1*1+2*2)/9=5/9  k=-0.5
        # Mean 0.1.
        report = dispatcher._aggregate_nominal(_rows(FULL))
        assert report["cohen_kappa"] == pytest.approx(0.1)

    def test_full_coverage_matches_the_old_aligned_computation(self):
        """Studies where everyone rated everything must not see their number move."""
        by_user = {u: [FULL[i][u] for i in ("i1", "i2", "i3")] for u in "abc"}
        old = nominal.pairwise_cohen_kappa(by_user)
        report = dispatcher._aggregate_nominal(_rows(FULL))
        assert report["cohen_kappa"] == pytest.approx(old)

    def test_partial_coverage_gives_a_kappa_at_all(self):
        # No item has all three, so the old computation had nothing to align.
        # (a,b) on i1,i2: [x,y] vs [x,y] -> 1.0; (b,c) on i3,i4 -> 1.0;
        # (a,c) share nothing and are skipped. Mean 1.0.
        report = dispatcher._aggregate_nominal(_rows(PARTIAL))
        assert report["n_aligned_items"] == 0
        assert report["cohen_kappa"] == pytest.approx(1.0)
        assert report["percent_agreement"] == pytest.approx(1.0)

    def test_the_old_name_is_an_alias(self):
        report = dispatcher._aggregate_nominal(_rows(PARTIAL))
        assert report["pairwise_cohen_kappa"] == report["cohen_kappa"]

    def test_a_single_label_pair_is_skipped_not_averaged_in(self):
        # (a,b) chose x on both shared items: chance agreement is 1, kappa 0/0.
        # (a,c) on i1,i2: [x,x] vs [y,x]  po=1/2 pe=(2*1)/4=1/2  k=0.
        table = {"i1": {"a": "x", "b": "x", "c": "y"},
                 "i2": {"a": "x", "b": "x", "c": "x"}}
        # (b,c) is the same as (a,c): k=0. So the mean over defined pairs is 0,
        # where a NaN in the mean would have made the whole coefficient NaN.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            value = nominal.mean_cohen_kappa_over_shared_items(list(table.values()))
        assert value == pytest.approx(0.0)

    def test_nothing_shared_is_nan(self):
        assert math.isnan(nominal.mean_cohen_kappa_over_shared_items(
            [{"a": "x"}, {"b": "y"}]))
        assert math.isnan(nominal.mean_pairwise_agreement([{"a": "x"}]))


class TestTheAdminTable:
    def test_both_measures_render_and_the_alias_does_not(self):
        report = dispatcher._aggregate_nominal(_rows(FULL))
        names = [row["name"] for row in presentation.flatten(report)]
        assert "percent_agreement" in names
        assert "cohen_kappa" in names
        assert "pairwise_cohen_kappa" not in names

    def test_percent_agreement_is_never_banded(self):
        """Chance agreement on a balanced binary scheme is 0.5.

        Driven live: 4 of 6 items agreed, 3/3 label split, so percent agreement
        0.667 and kappa (0.667 - 0.5) / 0.5 = 0.333. The page badged the first
        "strong" in green beside an unbanded 0.333 for the same annotators.
        """
        assert presentation.metric_scale("percent_agreement") == "raw"
        assert presentation.band_for("percent_agreement", 0.667) == ""
        assert presentation.band_for("percent_agreement", 0.05) == ""
        assert presentation.band_for("detection.percent_agreement", 0.95) == ""
        # Overlap measures keep their bands.
        assert presentation.band_for("mean_jaccard", 0.9) == "strong"
