"""
Regressions for the audit-10 findings that are not IAA or parquet.

Each of these produced a plausible-looking result rather than an error, which
is why none of them was caught by the suite that already existed:

* a judge eval card certified an unmeasured judge "trustworthy"
* a labelled likert could not be pre-annotated, and said nothing about it
* every vision prompt was built without the item's text
* the documented `instance_display` image fallback read a key that does not
  exist, so it had never once run
* `chat_support.system_prompt` was read by the code and rejected by the
  validator; `llm_labeling` was accepted by the validator and read by nothing
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from potato.server_utils.judge_bias import build_eval_card, eval_cards_from_pairs


# ---------------------------------------------------------------------- 4 --

class TestJudgeVerdictNeedsEvidence:
    def test_zero_pairs_is_not_trustworthy(self):
        card = build_eval_card("category", kappa=None, agreement_rate=0.0, n=0)
        assert card["verdict"] == "not yet measured"
        assert card["concerns"] == []
        assert card["agreement"]["n"] == 0

    def test_the_card_agrees_with_the_per_schema_block(self):
        """`per_schema` said "no overlap" from the same numbers the card used."""
        cards = eval_cards_from_pairs(
            {"category": []},
            {"category": {"kappa": None, "agreement_rate": 0.0}},
            lambda iid: 100)
        assert cards["category"]["verdict"] == "not yet measured"

    def test_one_pair_is_measured_again(self):
        cards = eval_cards_from_pairs(
            {"category": [("i1", "Bug", "Other", 0.9, "")]},
            {"category": {"kappa": None, "agreement_rate": 0.0}},
            lambda iid: 100)
        assert cards["category"]["verdict"] != "not yet measured"
        assert cards["category"]["agreement"]["n"] == 1

    def test_a_clean_measured_judge_is_still_trustworthy(self):
        card = build_eval_card("category", kappa=0.9, agreement_rate=0.95, n=40)
        assert card["verdict"] == "trustworthy"


# ---------------------------------------------------------------------- 6 --

class TestVisionPromptsCarryTheItemText:
    def test_text_is_included_beside_the_image(self):
        from potato.ai.ai_cache import _item_text_block
        block = _item_text_block(
            "The export button spins forever", "http://host/shot.png")
        assert "The export button spins forever" in block

    def test_an_image_only_item_is_unchanged(self):
        """`text_key` pointing at the image must not repeat the URL as prose."""
        from potato.ai.ai_cache import _item_text_block
        url = "http://host/photo.jpg"
        assert _item_text_block(url, url) == ""
        assert _item_text_block("http://other/pic.png", url) == ""

    def test_absent_text_adds_nothing(self):
        from potato.ai.ai_cache import _item_text_block
        assert _item_text_block("", None) == ""
        assert _item_text_block("   ", None) == ""
        assert _item_text_block(None, None) == ""

    def test_every_vision_prompt_interpolates_it(self):
        """Nine prompt sites across three generators; none may be missed."""
        import inspect
        from potato.ai import ai_cache

        source = inspect.getsource(ai_cache)
        opening = source.count('"""Look at this image')
        assert opening == 9, f"expected 9 vision prompts, found {opening}"
        assert source.count("{text_block}") == opening


# ---------------------------------------------------------------------- 7 --

class TestInstanceDisplayImageFallback:
    """`fields[]` entries are keyed `key`; the fallback read `field`."""

    def _resolve(self, item_data, cfg):
        from potato.ai import ai_cache

        class FakeItem:
            def get_data(self):
                return item_data

        class FakeISM:
            def items(self):
                return {0: FakeItem()}

        with patch.object(ai_cache, "config", cfg), \
             patch.object(ai_cache, "get_item_state_manager", lambda: FakeISM()):
            return ai_cache._get_instance_image(0)

    def test_sniffs_a_displayed_field(self):
        found = self._resolve(
            {"body": "the ticket text", "shot": "http://host/a.png"},
            {"instance_display": {"fields": [{"key": "body", "type": "text"},
                                             {"key": "shot", "type": "text"}]}})
        assert found == "http://host/a.png"

    def test_a_field_declared_as_an_image_is_taken_at_its_word(self):
        """A path with no recognisable extension is still the image."""
        found = self._resolve(
            {"body": "text", "pic": "/media/item-42"},
            {"instance_display": {"fields": [{"key": "body", "type": "text"},
                                             {"key": "pic", "type": "image"}]}})
        assert found == "/media/item-42"

    def test_no_image_field_resolves_to_none(self):
        assert self._resolve(
            {"body": "just text"},
            {"instance_display": {"fields": [{"key": "body", "type": "text"}]}}
        ) is None

    def test_an_explicit_key_still_wins(self):
        found = self._resolve(
            {"body": "text", "shot": "http://host/a.png",
             "other": "http://host/b.png"},
            {"ai_support": {"image_key": "other"},
             "instance_display": {"fields": [{"key": "shot", "type": "image"}]}})
        assert found == "http://host/b.png"


# ------------------------------------------------------------------- 8, 9 --

class TestConfigKeyRegistration:
    def test_chat_support_system_prompt_is_accepted(self):
        """chat_manager.py reads it; the validator rejected it."""
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
        assert "system_prompt" in KNOWN_CONFIG_KEYS["chat_support"]

    def test_top_level_llm_labeling_is_not_a_key(self):
        """Recognized and read by nothing is worse than unrecognized."""
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
        assert "llm_labeling" not in KNOWN_CONFIG_KEYS

    def test_llm_labeling_points_at_icl_labeling(self, caplog):
        """Unlisted is only an improvement if the warning names the real key."""
        import logging

        from potato.server_utils.config_module import validate_unknown_keys

        with caplog.at_level(logging.WARNING,
                             logger="potato.server_utils.config_module"):
            validate_unknown_keys({"llm_labeling": {"enabled": True}})

        warnings = [r.getMessage() for r in caplog.records]
        assert any("llm_labeling" in w and "icl_labeling" in w
                   for w in warnings), warnings


# ---------------------------------------------------------------------- 10 --

class TestDiagnosticsGoToTheLogNotThePage:
    def test_missing_prompt_type_renders_nothing(self):
        from potato.ai.ai_help_wrapper import DynamicAIHelp

        helper = DynamicAIHelp()
        with patch("potato.ai.ai_help_wrapper.get_ai_prompt",
                   return_value={"radio": {}}):
            context = helper.get_ai_help_data(0, 0, "multirate")

        assert context["ai_assistant"] is None
        # Not `annotation type multirate does not exist in ai_prompts`.
        assert context["error_message"] is None

    def test_the_image_advice_is_not_addressed_to_the_annotator(self):
        import inspect
        from potato.server_utils.schemas import image_annotation

        source = inspect.getsource(image_annotation)
        # The advice itself survives -- in console.warn, where the person who
        # wrote the config will find it. Asserted on the property, not on the
        # sentence: this guard is about WHO the advice is addressed to, and
        # pinning the wording made it fail when the wording improved.
        assert "console.warn(" in source
        warn_call = source.split("console.warn(", 1)[1][:400]
        assert "source_field" in warn_call, (
            "the console advice must still name the key that fixes it")
        # ...but it is not inside the message painted on the canvas.
        canvas_call = source.split("_showCanvasMessage(", 1)[1][:200]
        assert "text_key" not in canvas_call
        assert "source_field" not in canvas_call
