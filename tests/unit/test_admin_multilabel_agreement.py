"""
/admin/api/agreement on a multi-label schema compares sets of labels.

The 2.13.0 audit saw a multiselect where annotators chose {neutrophil, T cell}
and {neutrophil} reported Fleiss' kappa -0.5: each whole set was one nominal
category, so any partial overlap was total disagreement. The endpoint now uses
the same measures as /admin/iaa for multi-label schemas.

Expected alphas are NLTK's ``AnnotationTask(distance=masi_distance)`` on the
same data. NLTK rounds MASI's weights to 0.67 and 0.33 where Potato uses 2/3
and 1/3, so the two differ in the fourth decimal; the tolerance allows that.
"""

import pytest

from potato.admin import AdminDashboard


def _valid_items(items):
    return {item: [{"user": f"u{k}", "names": sorted(labels)}
                   for k, labels in enumerate(answers)]
            for item, answers in items.items()}


def _agreement(items):
    dashboard = AdminDashboard.__new__(AdminDashboard)   # needs no state
    return dashboard._multilabel_agreement(_valid_items(items))


def test_three_annotators_who_mostly_agree_score_as_mostly_agreeing():
    result = _agreement({
        "c1": [{"neutrophil", "T cell"}, {"neutrophil"}, {"neutrophil"}],
        "c2": [{"B cell"}, {"B cell"}, {"B cell", "T cell"}],
        "c3": [{"T cell"}, {"T cell"}, {"T cell"}],
        "c4": [{"neutrophil"}, {"B cell"}, {"neutrophil"}],
    })
    assert result["metric_type"] == "masi"
    assert result["krippendorff_alpha"] == pytest.approx(0.4826, abs=1e-3)
    # Pairwise Jaccard by hand: c1 1/2,1/2,1; c2 1,1/2,1/2; c3 1,1,1; c4 0,1,0.
    assert result["mean_jaccard"] == pytest.approx(8 / 12, abs=1e-4)
    assert result["items_evaluated"] == 4
    assert result["total_annotations"] == 12
    assert "fleiss_kappa" not in result and "cohen_kappa" not in result


def test_identical_sets_everywhere_are_undefined_not_an_error():
    result = _agreement({
        "c1": [{"neutrophil", "T cell"}, {"neutrophil", "T cell"}],
        "c2": [{"neutrophil", "T cell"}, {"neutrophil", "T cell"}],
    })
    assert result["krippendorff_alpha"] is None
    assert result["percent_agreement"] == 1.0
    assert result["mean_jaccard"] == pytest.approx(1.0)
    assert result["interpretation"] == "Undefined"


@pytest.mark.parametrize("items", [
    {"c1": [{"a"}]},                              # one annotator
    {"c1": [{"a"}], "c2": [{"b"}]},               # two who share no item
], ids=["one_annotator", "no_shared_item"])
def test_no_pair_of_annotators_gives_valid_json(items):
    import json
    # min_overlap: 1 keeps single-annotator items; "no_shared_item" puts u0 on
    # both, so give c2 a second user to make them disjoint.
    rows = _valid_items(items)
    if "c2" in rows:
        rows["c2"][0]["user"] = "u1"
    dashboard = AdminDashboard.__new__(AdminDashboard)
    result = dashboard._multilabel_agreement(rows)
    json.dumps(result, allow_nan=False)           # raises on NaN
    assert result["error"] == "No items with 2+ annotators"
