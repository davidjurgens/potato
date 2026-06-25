"""Unit tests for judge_calibration span support (experimental)."""

from potato.judge_calibration.aggregation import aggregate, span_iou, _aggregate_span
from potato.judge_calibration.generation import parse_sample, _SpanList, _SpanItem
from potato.judge_calibration.metrics import (
    compute_span_report,
    _match_spans,
    _pairwise_span_f1,
)


class FakeEndpoint:
    def parseStringToJson(self, s):
        return s


class TestSpanIoU:
    def test_identical(self):
        assert span_iou((0, 10), (0, 10)) == 1.0

    def test_disjoint(self):
        assert span_iou((0, 5), (10, 20)) == 0.0

    def test_half_overlap(self):
        # [0,10) vs [5,15): inter 5, union 15 -> 1/3
        assert round(span_iou((0, 10), (5, 15)), 4) == round(5 / 15, 4)


class TestSpanAggregation:
    def test_consistent_span_high_confidence(self):
        # same span in 3/4 samples -> kept, confidence 0.75
        samples = [
            [{"start": 0, "end": 5, "label": "PER"}],
            [{"start": 0, "end": 5, "label": "PER"}],
            [{"start": 0, "end": 5, "label": "PER"}],
            [],
        ]
        r = aggregate("m", "i", "ner", "span", samples, 4)
        assert len(r.modal_label) == 1
        sp = r.modal_label[0]
        assert sp["start"] == 0 and sp["end"] == 5 and sp["label"] == "PER"
        assert sp["confidence"] == 0.75

    def test_low_support_dropped(self):
        # span appears once in 4 -> confidence 0.25 < 0.5 keep threshold -> dropped
        samples = [[{"start": 0, "end": 5, "label": "PER"}], [], [], []]
        r = aggregate("m", "i", "ner", "span", samples, 4)
        assert r.modal_label == []

    def test_overlapping_spans_cluster(self):
        # near-identical offsets cluster together (IoU >= 0.5)
        samples = [
            [{"start": 0, "end": 10, "label": "LOC"}],
            [{"start": 0, "end": 9, "label": "LOC"}],
            [{"start": 0, "end": 10, "label": "LOC"}],
            [{"start": 0, "end": 10, "label": "LOC"}],
        ]
        r = aggregate("m", "i", "ner", "span", samples, 4)
        assert len(r.modal_label) == 1
        assert r.modal_label[0]["confidence"] == 1.0
        # representative = modal exact offsets (0,10 appears 3x)
        assert r.modal_label[0]["end"] == 10

    def test_different_labels_separate(self):
        samples = [
            [{"start": 0, "end": 5, "label": "PER"}, {"start": 0, "end": 5, "label": "ORG"}],
        ] * 4
        r = aggregate("m", "i", "ner", "span", samples, 4)
        labels = sorted(s["label"] for s in r.modal_label)
        assert labels == ["ORG", "PER"]


class TestSpanParsing:
    def setup_method(self):
        self.ep = FakeEndpoint()

    def test_pydantic_spanlist(self):
        resp = _SpanList(spans=[_SpanItem(start=0, end=4, label="PER")])
        out = parse_sample(self.ep, resp, "span", ["PER", "LOC"])
        assert out == [{"start": 0, "end": 4, "label": "PER"}]

    def test_invalid_label_dropped(self):
        resp = {"spans": [{"start": 0, "end": 4, "label": "NOPE"}]}
        assert parse_sample(self.ep, resp, "span", ["PER"]) == []

    def test_bad_offsets_dropped(self):
        resp = {"spans": [{"start": 5, "end": 2, "label": "PER"}]}
        assert parse_sample(self.ep, resp, "span", ["PER"]) == []

    def test_empty_spans_valid(self):
        assert parse_sample(self.ep, {"spans": []}, "span", ["PER"]) == []

    def test_fuzzy_label(self):
        resp = {"spans": [{"start": 0, "end": 4, "label": "per"}]}
        assert parse_sample(self.ep, resp, "span", ["PER"]) == [{"start": 0, "end": 4, "label": "PER"}]


class TestSpanMatching:
    def test_match_exact(self):
        pred = [{"start": 0, "end": 5, "label": "PER"}]
        gold = [{"start": 0, "end": 5, "label": "PER"}]
        tp, fp, fn, ious, matched = _match_spans(pred, gold, 0.5)
        assert (tp, fp, fn) == (1, 0, 0)
        assert matched == [True]

    def test_label_mismatch_no_match(self):
        pred = [{"start": 0, "end": 5, "label": "PER"}]
        gold = [{"start": 0, "end": 5, "label": "ORG"}]
        tp, fp, fn, _, _ = _match_spans(pred, gold, 0.5)
        assert (tp, fp, fn) == (0, 1, 1)

    def test_below_threshold_no_match(self):
        pred = [{"start": 0, "end": 3, "label": "PER"}]
        gold = [{"start": 10, "end": 20, "label": "PER"}]
        tp, fp, fn, _, _ = _match_spans(pred, gold, 0.5)
        assert (tp, fp, fn) == (0, 1, 1)


class TestSpanReport:
    def test_perfect_model(self):
        gold = {"i1": [{"start": 0, "end": 5, "label": "PER"}],
                "i2": [{"start": 2, "end": 8, "label": "LOC"}]}
        preds = {
            "i1": [{"start": 0, "end": 5, "label": "PER", "confidence": 1.0}],
            "i2": [{"start": 2, "end": 8, "label": "LOC", "confidence": 1.0}],
        }
        rep = compute_span_report("ner", ["PER", "LOC"], {"m1": preds}, {"h1": gold})
        m = rep["per_model"]["m1"]
        assert m["f1"] == 1.0
        assert m["precision"] == 1.0 and m["recall"] == 1.0
        assert m["mean_iou"] == 1.0
        assert m["calibration"]["ece"] == 0.0  # conf 1.0, all correct
        assert rep["experimental"] is True

    def test_partial_with_fp(self):
        gold = {"i1": [{"start": 0, "end": 5, "label": "PER"}]}
        preds = {"i1": [
            {"start": 0, "end": 5, "label": "PER", "confidence": 0.9},   # TP
            {"start": 20, "end": 25, "label": "PER", "confidence": 0.6}, # FP
        ]}
        rep = compute_span_report("ner", ["PER"], {"m1": preds}, {"h1": gold})
        m = rep["per_model"]["m1"]
        assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 0)
        assert m["precision"] == 0.5
        assert m["recall"] == 1.0

    def test_iaa_llm_llm(self):
        gold = {"i1": [{"start": 0, "end": 5, "label": "PER"}]}
        m = {"i1": [{"start": 0, "end": 5, "label": "PER", "confidence": 1.0}]}
        rep = compute_span_report("ner", ["PER"], {"m1": m, "m2": m}, {"h1": gold})
        assert rep["iaa"]["span_f1"]["mean_llm_llm"] == 1.0

    def test_pairwise_f1_symmetric(self):
        a = {"i1": [{"start": 0, "end": 5, "label": "PER"}]}
        b = {"i1": [{"start": 0, "end": 5, "label": "PER"}]}
        assert _pairwise_span_f1(a, b, 0.5) == 1.0
