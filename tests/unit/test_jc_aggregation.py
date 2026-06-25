"""Unit tests for judge_calibration k-sample aggregation."""

from potato.judge_calibration.aggregation import aggregate, ModelItemResult


class TestCategorical:
    def test_radio_modal_and_vote_fraction(self):
        r = aggregate("m", "i", "s", "radio", ["pos", "pos", "pos", "neg", "pos"], 5)
        assert r.modal_label == "pos"
        assert r.confidence == 0.8

    def test_unanimous(self):
        r = aggregate("m", "i", "s", "radio", ["a"] * 4, 4)
        assert r.modal_label == "a"
        assert r.confidence == 1.0

    def test_none_samples_count_in_denominator(self):
        r = aggregate("m", "i", "s", "radio", ["pos", "pos", None, None, None], 5)
        assert r.modal_label == "pos"
        assert r.confidence == 0.4

    def test_all_failed(self):
        r = aggregate("m", "i", "s", "radio", [None, None], 2)
        assert r.modal_label is None
        assert r.confidence == 0.0

    def test_likert_preserves_value_type(self):
        r = aggregate("m", "i", "s", "likert", ["4", "4", "5"], 3)
        assert r.modal_label == "4"
        assert round(r.confidence, 4) == round(2 / 3, 4)


class TestMultiselect:
    def test_threshold_selection(self):
        samples = [["a", "b"], ["a"], ["a", "b"], ["a"], ["c"]]
        r = aggregate("m", "i", "s", "multiselect", samples, 5, multiselect_threshold=0.5)
        # a=4/5>=.5 kept; b=2/5 dropped; c=1/5 dropped
        assert r.modal_label == ["a"]
        assert r.per_label_confidence["a"] == 0.8
        assert r.per_label_confidence["b"] == 0.4
        assert r.confidence == 0.8

    def test_empty_predictions_confidence(self):
        # every label seen only once across 5 draws -> none clears 0.5
        samples = [["a"], ["b"], ["c"], ["d"], ["e"]]
        r = aggregate("m", "i", "s", "multiselect", samples, 5, multiselect_threshold=0.5)
        assert r.modal_label == []
        # confidence = 1 - mean(per-label fractions) = 1 - 0.2 = 0.8
        assert r.confidence == 0.8

    def test_all_selected_nothing(self):
        r = aggregate("m", "i", "s", "multiselect", [[], [], []], 3)
        assert r.modal_label == []
        assert r.confidence == 1.0


class TestSerialization:
    def test_roundtrip(self):
        r = aggregate("m", "i", "s", "radio", ["pos", "neg"], 2)
        d = r.to_dict()
        r2 = ModelItemResult.from_dict(d)
        assert r2.model == r.model
        assert r2.modal_label == r.modal_label
        assert r2.confidence == r.confidence
        assert r2.samples == r.samples
