"""
Agreement over captions.

The point of this module is that two annotators describing the same thing
rarely use the same words, so every exact-match coefficient scores correct
paraphrases as total disagreement. These tests pin what the measure does about
that — and, just as importantly, pin that the cheap default is honest about
being a poor proxy rather than being presented as a semantic measure.
"""

import math

import pytest

from potato.server_utils.iaa import captions as C


def box(x, y=0.2, w=0.3, h=0.3):
    return {"type": "bbox", "label": "r",
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


class TestTokenDistance:
    def test_identical_captions_are_zero(self):
        assert C.token_distance("a red cup", "a red cup") == 0.0

    def test_stopwords_do_not_count(self):
        assert C.token_distance("a red cup", "the red cup") == 0.0

    def test_case_and_punctuation_do_not_count(self):
        assert C.token_distance("A Red Cup.", "red cup") == 0.0

    def test_a_correct_paraphrase_scores_total_disagreement(self):
        """
        The documented weakness, asserted rather than described. If this ever
        stops being 1.0 the default has quietly become something else and the
        caveat in the docs is wrong.
        """
        assert C.token_distance("a man in a red shirt",
                                "person wearing a crimson top") == 1.0

    def test_two_empty_captions_are_identical_not_undefined(self):
        assert C.token_distance("", "") == 0.0

    def test_partial_overlap_is_between(self):
        value = C.token_distance("a red cup on a table", "a red cup")
        assert 0.0 < value < 1.0


class TestCaptionAlpha:
    def test_perfect_agreement(self):
        rows = [("a", "u1", "red cup"), ("b", "u1", "a red cup"),
                ("a", "u2", "blue plate"), ("b", "u2", "the blue plate")]
        result = C.caption_alpha(rows)
        assert result["alpha"] == pytest.approx(1.0)
        assert result["mean_pairwise_distance"] == 0.0

    def test_total_disagreement_is_reported_as_such(self):
        rows = [("a", "u1", "red cup"), ("b", "u1", "green tractor"),
                ("a", "u2", "blue plate"), ("b", "u2", "yellow submarine")]
        result = C.caption_alpha(rows)
        assert result["mean_pairwise_distance"] == 1.0
        assert result["alpha"] is None or result["alpha"] <= 0.0

    def test_the_distance_actually_used_is_reported(self):
        """
        An alpha computed with a lexical fallback while the caller asked for
        embeddings is a different number. Silently substituting it is how a
        weak result gets quoted as a semantic one.
        """
        result = C.caption_alpha([("a", "u1", "x"), ("b", "u1", "y")],
                                 distance="token")
        assert result["distance_requested"] == "token"
        assert result["distance_used"] == "token"

    def test_a_missing_embedding_backend_says_so_loudly(self, monkeypatch):
        monkeypatch.setattr(C, "embedding_distance_fn", lambda *a, **k: None)
        result = C.caption_alpha([("a", "u1", "a red cup"),
                                  ("b", "u1", "a crimson mug")],
                                 distance="embedding")
        assert result["distance_requested"] == "embedding"
        assert result["distance_used"] == "token"
        assert "LOWER BOUND" in result["note"]
        assert "sentence-transformers" in result["note"]

    def test_one_annotator_is_not_agreement(self):
        result = C.caption_alpha([("a", "u1", "red cup"), ("a", "u2", "blue")])
        assert result["alpha"] is None
        assert "two annotators" in result["note"]

    def test_blank_captions_are_dropped_not_compared(self):
        """
        "Did not write one" is not an answer two annotators can agree on, and
        counting it as one manufactures agreement between two people who both
        skipped.
        """
        rows = [("a", "u1", "red cup"), ("b", "u1", "   "),
                ("a", "u2", "blue plate"), ("b", "u2", "blue plate")]
        result = C.caption_alpha(rows)
        assert result["n_captions"] == 3

    def test_an_embedding_distance_is_used_when_available(self, monkeypatch):
        """A stub, so the test does not need torch to prove the wiring."""
        monkeypatch.setattr(
            C, "embedding_distance_fn",
            lambda *a, **k: (lambda x, y: 0.0 if x[:3] == y[:3] else 1.0))
        result = C.caption_alpha([("a", "u1", "redcup"), ("b", "u1", "redmug"),
                                  ("a", "u2", "bluething"), ("b", "u2", "bluestuff")],
                                 distance="embedding")
        assert result["distance_used"] == "embedding"
        assert result["mean_pairwise_distance"] == 0.0


class TestRegionMatching:
    def test_captions_are_compared_within_matched_regions(self):
        """
        Not by position. Two annotators who each wrote three captions did not
        necessarily write them about the same three things, and comparing
        caption k with caption k measures the order they happened to draw in.
        """
        items = {"i1": {
            "a": [{"region": box(0.1), "caption": "red cup"},
                  {"region": box(0.6), "caption": "blue plate"}],
            # Same regions, drawn in the opposite order.
            "b": [{"region": box(0.62), "caption": "a blue plate"},
                  {"region": box(0.12), "caption": "a red cup"}],
        }}
        report = C.region_caption_report(items)
        assert report["matching"]["n_matched_regions"] == 2
        assert report["mean_pairwise_distance"] == 0.0
        assert report["alpha"] == pytest.approx(1.0)

    def test_a_region_only_one_annotator_drew_is_a_detection_disagreement(self):
        """
        Counted as unmatched, not scored as a caption disagreement — that would
        blame the wrong thing.
        """
        items = {"i1": {
            "a": [{"region": box(0.1), "caption": "red cup"},
                  {"region": box(0.9), "caption": "a thing only A saw"}],
            "b": [{"region": box(0.12), "caption": "a red cup"}],
        }}
        report = C.region_caption_report(items)
        assert report["matching"]["n_matched_regions"] == 1
        assert report["matching"]["n_unmatched_regions"] == 1

    def test_regions_that_do_not_overlap_do_not_match(self):
        items = {"i1": {
            "a": [{"region": box(0.0), "caption": "red cup"}],
            "b": [{"region": box(0.8), "caption": "red cup"}],
        }}
        report = C.region_caption_report(items)
        assert report["matching"]["n_matched_regions"] == 0
        assert report["matching"]["n_unmatched_regions"] == 1

    def test_the_match_threshold_is_configurable_and_reported(self):
        items = {"i1": {
            "a": [{"region": box(0.10), "caption": "cup"}],
            "b": [{"region": box(0.22), "caption": "cup"}],
        }}
        strict = C.region_caption_report(items, match_iou=0.9)
        loose = C.region_caption_report(items, match_iou=0.2)
        assert strict["matching"]["n_matched_regions"] == 0
        assert loose["matching"]["n_matched_regions"] == 1
        assert loose["matching"]["match_iou"] == 0.2

    def test_a_single_annotator_item_contributes_nothing(self):
        items = {"i1": {"a": [{"region": box(0.1), "caption": "red cup"}]}}
        report = C.region_caption_report(items)
        assert report["n_captions"] == 0


class TestDispatcherWiring:
    def test_region_caption_is_classified(self):
        from potato.server_utils.iaa.dispatcher import SchemaKind, classify_schema

        assert classify_schema({"annotation_type": "region_caption"}) == \
            SchemaKind.CAPTION

    def test_the_declared_metrics_exist_in_the_report(self):
        from potato.server_utils.iaa.dispatcher import metrics_for_schema

        items = {"i1": {
            "a": [{"region": box(0.1), "caption": "red cup"}],
            "b": [{"region": box(0.12), "caption": "a red cup"}],
        }}
        report = C.region_caption_report(items)
        for name in metrics_for_schema({"annotation_type": "region_caption"}):
            node = report
            for part in name.split("."):
                assert part in node, f"{name} is declared but not reported"
                node = node[part]

    def test_stored_blobs_parse_into_the_report_shape(self):
        """
        The client writes `{"captions": [{region, caption}]}` as a JSON string
        under a single key. A parser that expected the parsed shape would
        silently produce an empty report.
        """
        import json

        from potato.server_utils.iaa.dispatcher import _parse_caption_rows

        stored = json.dumps({"captions": [
            {"region": box(0.1), "caption": "red cup"}]})
        rows = {"i1": {"a": {"_data": stored}, "b": {"_data": stored}}}
        parsed = _parse_caption_rows(rows)
        assert set(parsed["i1"]) == {"a", "b"}
        assert parsed["i1"]["a"][0]["caption"] == "red cup"

    def test_the_distance_metric_is_not_banded_as_agreement(self):
        """0 means the annotators wrote the same thing — the bands invert."""
        from potato.server_utils.iaa.presentation import band_for, metric_scale

        assert metric_scale("mean_pairwise_distance") == "lower"
        assert band_for("mean_pairwise_distance", 0.05) == ""
