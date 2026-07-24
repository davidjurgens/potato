"""Unit tests for chain-of-thought (CoT) step segmentation."""

import pytest

from potato.server_utils.cot_segmentation import (
    segment_cot,
    apply_cot_segmentation,
    VALID_STRATEGIES,
)


class TestSegmentCot:
    def test_numbered_strategy(self):
        text = ("Step 1: read the problem.\n"
                "Step 2: compute the derivative which is 2x.\n"
                "Step 3: set it to zero to find x = 0.")
        steps = segment_cot(text, strategy="numbered", opts={"min_step_chars": 10})
        assert len(steps) == 3
        assert steps[0]["text"].startswith("Step 1")
        assert [s["index"] for s in steps] == [0, 1, 2]

    def test_blank_line_strategy(self):
        text = "First paragraph of reasoning here.\n\nSecond paragraph here.\n\nThird one."
        steps = segment_cot(text, strategy="blank_line", opts={"min_step_chars": 5})
        assert len(steps) == 3

    def test_markers_strategy(self):
        text = "<step>plan the approach</step><step>execute the plan</step>"
        steps = segment_cot(text, strategy="markers",
                            opts={"markers": ["<step>", "</step>"], "min_step_chars": 3})
        assert len(steps) == 2
        assert "plan" in steps[0]["text"]

    def test_sentence_strategy(self):
        text = "I need the sum. The pattern is squares. The formula is n(n+1)(2n+1)/6. The answer is 30."
        steps = segment_cot(text, strategy="sentence", opts={"min_step_chars": 5})
        assert len(steps) >= 3

    def test_sentences_per_step_grouping(self):
        text = "One. Two. Three. Four."
        one = segment_cot(text, strategy="sentence", opts={"sentences_per_step": 1})
        grouped = segment_cot(text, strategy="sentence", opts={"sentences_per_step": 2})
        assert len(grouped) < len(one)

    def test_auto_picks_a_working_strategy(self):
        numbered = "1. alpha reasoning\n2. beta reasoning\n3. gamma reasoning"
        steps = segment_cot(numbered, strategy="auto", opts={"min_step_chars": 5})
        assert len(steps) == 3

    def test_auto_single_step_when_no_boundaries(self):
        text = "just one contiguous thought with no delimiters at all here"
        steps = segment_cot(text, strategy="auto")
        assert len(steps) == 1
        assert steps[0]["text"].strip() == text

    def test_empty_and_non_string_input(self):
        assert segment_cot("", strategy="auto") == []
        assert segment_cot("   ", strategy="auto") == []
        assert segment_cot(None, strategy="auto") == []  # type: ignore[arg-type]

    def test_offsets_are_valid_slices(self):
        text = "Step 1: first.\nStep 2: second.\nStep 3: third."
        steps = segment_cot(text, strategy="numbered")
        for s in steps:
            assert text[s["char_start"]:s["char_end"]] == s["text"]

    def test_type_is_inferred(self):
        text = "I need to plan this.\n\nresult(x) returns 5.\n\nThe environment responded ok."
        steps = segment_cot(text, strategy="blank_line", opts={"min_step_chars": 3})
        types = {s["type"] for s in steps}
        assert types  # each step got some type
        assert all(s["type"] in
                   {"thought", "action", "observation", "system", "error"} for s in steps)

    def test_min_step_chars_merges_short(self):
        text = "ok.\n\nThis is a much longer paragraph that clears the threshold easily."
        steps = segment_cot(text, strategy="blank_line", opts={"min_step_chars": 40})
        # The tiny "ok." fragment is merged, not left as its own step.
        assert all(len(s["text"]) >= 3 for s in steps)
        assert len(steps) == 1

    def test_max_steps_cap(self):
        text = "\n\n".join(f"paragraph number {i} with enough text" for i in range(50))
        steps = segment_cot(text, strategy="blank_line", opts={"max_steps": 10})
        assert len(steps) == 10

    def test_unknown_strategy_falls_back(self):
        steps = segment_cot("a. one\nb. two", strategy="nonsense")
        assert isinstance(steps, list)

    def test_llm_strategy_without_endpoint_falls_back(self):
        text = "1. first step here\n2. second step here"
        steps = segment_cot(text, strategy="llm", opts={"min_step_chars": 5}, endpoint=None)
        assert len(steps) == 2  # fell back to heuristics

    def test_all_strategies_listed(self):
        assert set(VALID_STRATEGIES) == {
            "blank_line", "numbered", "markers", "sentence", "llm", "auto"}


class TestLlmSegmentation:
    def test_llm_strategy_uses_endpoint(self):
        class FakeEndpoint:
            def parseStringToJson(self, s):
                import json
                return json.loads(s)

            def query(self, prompt, output_format=None):
                import json
                return json.dumps({"steps": ["alpha part", "beta part", "gamma part"]})

        text = "alpha part beta part gamma part"
        steps = segment_cot(text, strategy="llm", opts={}, endpoint=FakeEndpoint())
        assert len(steps) == 3
        assert steps[0]["text"] == "alpha part"


class TestConfigValidation:
    def test_valid_block_passes(self):
        from potato.server_utils.config_module import validate_cot_segmentation_config
        validate_cot_segmentation_config(
            {"cot_segmentation": {"source_key": "reasoning", "strategy": "auto"}})

    def test_absent_block_is_noop(self):
        from potato.server_utils.config_module import validate_cot_segmentation_config
        validate_cot_segmentation_config({})

    def test_missing_source_key_raises(self):
        from potato.server_utils.config_module import (
            validate_cot_segmentation_config, ConfigValidationError)
        with pytest.raises(ConfigValidationError):
            validate_cot_segmentation_config({"cot_segmentation": {"strategy": "auto"}})

    def test_bad_strategy_raises(self):
        from potato.server_utils.config_module import (
            validate_cot_segmentation_config, ConfigValidationError)
        with pytest.raises(ConfigValidationError):
            validate_cot_segmentation_config(
                {"cot_segmentation": {"source_key": "r", "strategy": "wat"}})

    def test_bad_numeric_type_raises(self):
        from potato.server_utils.config_module import (
            validate_cot_segmentation_config, ConfigValidationError)
        with pytest.raises(ConfigValidationError):
            validate_cot_segmentation_config(
                {"cot_segmentation": {"source_key": "r", "min_step_chars": "lots"}})


class TestApplyCotSegmentation:
    def test_writes_target_key(self):
        item = {"id": "1", "reasoning": "1. one here\n2. two here\n3. three here"}
        apply_cot_segmentation(item, {"source_key": "reasoning",
                                     "target_key": "cot_steps",
                                     "strategy": "auto", "min_step_chars": 3})
        assert isinstance(item["cot_steps"], list)
        assert len(item["cot_steps"]) == 3

    def test_idempotent_when_already_populated(self):
        item = {"id": "1", "reasoning": "a\n\nb\n\nc", "cot_steps": [{"index": 0, "text": "pre"}]}
        apply_cot_segmentation(item, {"source_key": "reasoning", "target_key": "cot_steps"})
        assert item["cot_steps"] == [{"index": 0, "text": "pre"}]

    def test_noop_without_source_key_value(self):
        item = {"id": "1"}
        apply_cot_segmentation(item, {"source_key": "reasoning", "target_key": "cot_steps"})
        assert "cot_steps" not in item

    def test_missing_source_key_config(self):
        item = {"id": "1", "reasoning": "text"}
        out = apply_cot_segmentation(item, {"target_key": "cot_steps"})
        assert out is item
        assert "cot_steps" not in item
