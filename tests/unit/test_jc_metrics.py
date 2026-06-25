"""Unit tests for judge_calibration metrics (accuracy/IAA/gold resolution)."""

from potato.judge_calibration.metrics import (
    resolve_gold,
    compute_schema_report,
    compute_multiselect_report,
    compute_iaa,
    _majority,
    _jaccard,
)


class TestGold:
    def test_single(self):
        humans = {"h1": {"i1": "a", "i2": "b"}}
        assert resolve_gold(humans, "single") == {"i1": "a", "i2": "b"}

    def test_majority(self):
        humans = {
            "h1": {"i1": "a", "i2": "b"},
            "h2": {"i1": "a", "i2": "c"},
            "h3": {"i1": "b", "i2": "b"},
        }
        gold = resolve_gold(humans, "majority")
        assert gold["i1"] == "a"  # 2x a vs 1x b
        assert gold["i2"] == "b"  # 2x b vs 1x c

    def test_majority_tie_deterministic(self):
        # i1: a,b tie -> sorted-first 'a'
        humans = {"h1": {"i1": "a"}, "h2": {"i1": "b"}}
        assert resolve_gold(humans, "majority")["i1"] == "a"

    def test_majority_helper(self):
        assert _majority(["x", "y", "x"]) == "x"
        assert _majority([]) is None


class TestSchemaReport:
    def test_perfect_model_accuracy_and_kappa(self):
        # One model agrees perfectly with the human gold.
        gold = {"i1": "pos", "i2": "neg", "i3": "pos", "i4": "neg"}
        llm_modal = {"m1": dict(gold)}
        llm_conf = {"m1": {k: 1.0 for k in gold}}
        humans = {"h1": dict(gold)}

        rep = compute_schema_report(
            "sent", "radio", ["pos", "neg"], llm_modal, llm_conf, humans,
            gold_strategy="single", n_bins=10,
        )
        m = rep["per_model"]["m1"]
        assert m["accuracy"] == 1.0
        assert m["f1_macro"] == 1.0
        # perfect agreement -> kappa 1.0
        assert rep["iaa"]["cohen"]["mean_human_llm"] == 1.0
        # perfectly calibrated (conf 1.0, all correct) -> ECE 0
        assert m["calibration"]["ece"] == 0.0

    def test_partial_accuracy(self):
        gold = {"i1": "pos", "i2": "neg", "i3": "pos", "i4": "neg"}
        preds = {"i1": "pos", "i2": "neg", "i3": "neg", "i4": "neg"}  # 3/4 right
        rep = compute_schema_report(
            "sent", "radio", ["pos", "neg"],
            {"m1": preds}, {"m1": {k: 0.6 for k in preds}}, {"h1": gold},
        )
        assert rep["per_model"]["m1"]["accuracy"] == 0.75

    def test_two_models_llm_llm_iaa(self):
        gold = {"i1": "a", "i2": "b", "i3": "a", "i4": "b"}
        m1 = dict(gold)
        m2 = dict(gold)
        rep = compute_schema_report(
            "s", "radio", ["a", "b"],
            {"m1": m1, "m2": m2},
            {"m1": {k: 1.0 for k in gold}, "m2": {k: 1.0 for k in gold}},
            {"h1": gold},
        )
        # m1 and m2 identical -> llm_llm kappa 1.0
        assert rep["iaa"]["cohen"]["mean_llm_llm"] == 1.0

    def test_likert_mae(self):
        gold = {"i1": "3", "i2": "5", "i3": "1", "i4": "4"}
        preds = {"i1": "3", "i2": "4", "i3": "2", "i4": "4"}  # diffs 0,1,1,0 -> MAE 0.5
        rep = compute_schema_report(
            "rating", "likert", ["1", "2", "3", "4", "5"],
            {"m1": preds}, {"m1": {k: 0.7 for k in preds}}, {"h1": gold},
        )
        assert rep["per_model"]["m1"]["mae"] == 0.5

    def test_overlap_only(self):
        # model predicts i3 which has no gold; gold has i9 model didn't label.
        gold = {"i1": "a", "i2": "b", "i9": "a"}
        preds = {"i1": "a", "i2": "b", "i3": "a"}
        rep = compute_schema_report(
            "s", "radio", ["a", "b"],
            {"m1": preds}, {"m1": {k: 1.0 for k in preds}}, {"h1": gold},
        )
        assert rep["per_model"]["m1"]["n"] == 2  # only i1,i2 overlap


class TestMultiselect:
    def test_jaccard(self):
        assert _jaccard(["a", "b"], ["a", "b"]) == 1.0
        assert _jaccard(["a", "b"], ["a"]) == 0.5
        assert _jaccard([], []) == 1.0
        assert _jaccard(["a"], ["b"]) == 0.0

    def test_exact_match_and_jaccard(self):
        gold = {"i1": ["a", "b"], "i2": ["c"], "i3": [], "i4": ["a"]}
        preds = {"i1": ["a", "b"], "i2": ["c"], "i3": [], "i4": ["b"]}  # i4 wrong
        rep = compute_multiselect_report(
            "tags", ["a", "b", "c"], {"m1": preds},
            {"m1": {k: 0.8 for k in preds}}, {"h1": gold},
        )
        m = rep["per_model"]["m1"]
        assert m["exact_match_accuracy"] == 0.75
        assert m["mean_jaccard"] == 0.75

    def test_iaa_jaccard_partition(self):
        gold = {"i1": ["a"], "i2": ["b"]}
        rep = compute_multiselect_report(
            "tags", ["a", "b"],
            {"m1": dict(gold), "m2": dict(gold)},
            {"m1": {k: 1.0 for k in gold}, "m2": {k: 1.0 for k in gold}},
            {"h1": gold},
        )
        j = rep["iaa"]["jaccard"]
        assert j["mean_llm_llm"] == 1.0
        assert j["mean_human_llm"] == 1.0


class TestIAAPartition:
    def test_human_human_pair(self):
        humans = {"h1": {"i1": "a", "i2": "b"}, "h2": {"i1": "a", "i2": "b"}}
        iaa = compute_iaa({}, humans)
        assert iaa["cohen"]["mean_human_human"] == 1.0
        assert iaa["cohen"]["mean_human_llm"] is None
