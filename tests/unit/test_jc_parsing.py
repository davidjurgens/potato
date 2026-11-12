"""Unit tests for judge_calibration response parsing + prompt building."""

import json
from potato.judge_calibration.generation import build_prompt, parse_sample, _SingleLabel, _MultiLabel


class FakeEndpoint:
    """Minimal endpoint stub exposing parseStringToJson (used for str inputs)."""
    def parseStringToJson(self, s):
        # The real one strips fences/think tags; for tests just return as-is.
        return s


SCHEMA = {
    "name": "sentiment",
    "annotation_type": "radio",
    "description": "Sentiment",
    "labels": ["positive", "negative", "neutral"],
}


class TestParseSample:
    def setup_method(self):
        self.ep = FakeEndpoint()

    def test_pydantic_object(self):
        resp = _SingleLabel(label="positive")
        assert parse_sample(self.ep, resp, "radio", ["positive", "negative"]) == "positive"

    def test_dict_response(self):
        assert parse_sample(self.ep, {"label": "negative"}, "radio", ["positive", "negative"]) == "negative"

    def test_str_json_response(self):
        s = json.dumps({"label": "neutral"})
        assert parse_sample(self.ep, s, "radio", ["positive", "negative", "neutral"]) == "neutral"

    def test_fuzzy_match_case(self):
        assert parse_sample(self.ep, {"label": "Positive"}, "radio", ["positive"]) == "positive"

    def test_invalid_label_returns_none(self):
        assert parse_sample(self.ep, {"label": "purple"}, "radio", ["positive", "negative"]) is None

    def test_empty_label_returns_none(self):
        assert parse_sample(self.ep, {"label": ""}, "radio", ["positive"]) is None

    def test_multiselect_matches_subset(self):
        resp = _MultiLabel(labels=["A", "c"])
        out = parse_sample(self.ep, resp, "multiselect", ["a", "b", "c"])
        assert out == ["a", "c"]

    def test_multiselect_empty_is_valid(self):
        out = parse_sample(self.ep, {"labels": []}, "multiselect", ["a", "b"])
        assert out == []

    def test_garbage_str_returns_none(self):
        assert parse_sample(self.ep, "not json at all", "radio", ["a"]) is None


class TestBuildPrompt:
    def test_includes_labels_and_text(self):
        p = build_prompt("Judge this.", SCHEMA, "I love it")
        assert "positive" in p and "negative" in p
        assert "I love it" in p
        assert "JSON" in p

    def test_placeholder_substitution(self):
        p = build_prompt("Rate: {text}\nLabels: {labels}", SCHEMA, "great")
        assert "great" in p
        assert "positive, negative, neutral" in p
        # when substituted, the raw item block is not appended again
        assert p.count("great") == 1

    def test_multiselect_instruction(self):
        ms = dict(SCHEMA, annotation_type="multiselect")
        p = build_prompt("x", ms, "t")
        assert '"labels"' in p
