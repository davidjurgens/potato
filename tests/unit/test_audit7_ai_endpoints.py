"""
Audit 7: the model-in-the-loop subsystem, which no earlier audit had touched.

The headline was that `ai_support` did not work against a local
OpenAI-compatible server through any endpoint_type: the model answered
correctly every time, the server returned 200, tokens were spent, and the
annotator was shown "No hint available". Four separate defects each produced
that one symptom, which is what made them expensive to tell apart.

These are offline: the request each endpoint would send, and what the shared
code does with the reply. The live half — driving a real vLLM server — is in
tests/integration/test_audit7_live_endpoints.py, which skips without one.
"""

import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from potato.ai.ai_endpoint import BaseAIEndpoint, ModelCapabilities
from potato.ai.prompt.models_module import (
    GeneralHintFormat, GeneralKeywordFormat, GeneralRationaleFormat)


class _Endpoint(BaseAIEndpoint):
    """Concrete subclass so the base class's own behaviour can be exercised."""

    def _initialize_client(self):
        self.client = None

    def _get_default_model(self):
        return "test-model"

    def query(self, prompt, output_format):
        return self._canned


def make_endpoint(canned=None, **ai_config):
    ep = _Endpoint({"annotation_type": "radio", "description": "d",
                    "ai_config": ai_config})
    ep._canned = canned
    return ep


class TestVLLMSendsAParameterVLLMReads:
    """
    `guided_json` is not read by vLLM's /v1/chat/completions. No error, no
    warning, 200 with unconstrained output -- so every schema-shaped request
    came back as markdown prose, `parseStringToJson` wrapped it as
    {"response": "<prose>"}, and the caller got none of the keys it asked for.
    The blast radius is wider than ai_support: judge.py, icl_labeler and
    solo_mode's labeling models all call `query(prompt, Model)` the same way,
    and scored every item with an empty label.
    """

    def _sent_payload(self, output_format):
        from potato.ai.vllm_endpoint import VLLMEndpoint

        with patch("potato.ai.vllm_endpoint.requests") as requests_mod:
            requests_mod.get.return_value = MagicMock(status_code=200)
            post = MagicMock(status_code=200)
            post.json.return_value = {
                "choices": [{"message": {"content": '{"hint":"h"}'},
                             "finish_reason": "stop"}]}
            requests_mod.post.return_value = post
            requests_mod.exceptions.RequestException = Exception

            ep = VLLMEndpoint({"ai_config": {"base_url": "http://x:8000",
                                             "model": "m"}})
            ep.query("p", output_format)
            return requests_mod.post.call_args.kwargs["json"]

    def test_guided_json_is_not_sent(self):
        assert "guided_json" not in self._sent_payload(GeneralHintFormat)

    def test_the_schema_travels_in_response_format(self):
        payload = self._sent_payload(GeneralHintFormat)
        rf = payload["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "GeneralHintFormat"
        assert set(rf["json_schema"]["schema"]["properties"]) == {
            "hint", "suggestive_choice"}

    def test_a_nested_schema_travels_whole(self):
        # Nested schemas were never the problem: both multi-label formats carry
        # $defs/$ref and both constrain correctly under response_format.
        schema = self._sent_payload(
            GeneralRationaleFormat)["response_format"]["json_schema"]["schema"]
        assert "$defs" in schema
        assert "rationales" in schema["properties"]

    def test_no_schema_means_no_response_format(self):
        # Free-text callers (the model arena) must not be constrained.
        assert "response_format" not in self._sent_payload(None)


class TestOneReturnTypeForTheAIHelpPath:
    """
    ollama, vllm and openrouter returned a dict; openai, huggingface, anthropic
    and gemini returned a string. `/get_ai_suggestion` read the difference as
    success versus failure and shipped the string to the browser as
    {"error": "<the correct answer>"}. The endpoint that gets structured output
    RIGHT was the one whose answer was thrown away.
    """

    def test_a_json_string_becomes_a_dict(self):
        ep = make_endpoint()
        out = ep._as_structured(
            '{"hint": "h", "suggestive_choice": "negative"}', GeneralHintFormat)
        assert out == {"hint": "h", "suggestive_choice": "negative"}

    def test_a_fenced_json_string_becomes_a_dict(self):
        ep = make_endpoint()
        out = ep._as_structured(
            '```json\n{"hint": "h", "suggestive_choice": "neg"}\n```',
            GeneralHintFormat)
        assert out["hint"] == "h"

    def test_a_dict_is_returned_unchanged(self):
        ep = make_endpoint()
        payload = {"hint": "h"}
        assert ep._as_structured(payload, GeneralHintFormat) is payload

    def test_free_text_is_left_alone_when_no_schema_was_asked_for(self):
        # The model arena and chat want prose, and prose that happens to look
        # like JSON is still prose.
        ep = make_endpoint()
        assert ep._as_structured('{"hint": "h"}', None) == '{"hint": "h"}'

    def test_an_error_message_stays_a_string(self):
        # parseStringToJson never fails: text it cannot read comes back as
        # {"response": "<the text>"}. Without a check on the keys, get_ai's own
        # "Unable to generate suggestion" messages would reach the tooltip as
        # data and the route would report success.
        ep = make_endpoint()
        message = "Unable to generate suggestion - prompt not configured"
        assert ep._as_structured(message, GeneralHintFormat) == message

    def test_json_of_the_wrong_shape_stays_a_string(self):
        ep = make_endpoint()
        wrong = '{"annotation_guidance": {"analysis": "a", "hint": "h"}}'
        assert ep._as_structured(wrong, GeneralHintFormat) == wrong


class TestMaxTokensFitsTheFormatsWeShip:
    """
    At 100 the generation is cut mid-object and parseStringToJson's salvage
    returns the inner fragment -- a plausible-looking dict of the WRONG type
    (LabelRationale rather than GeneralRationaleFormat). The tooltip read "No
    rationales available", and nothing said the reply had been truncated.
    """

    def test_the_default_can_finish_a_multi_label_format(self):
        assert make_endpoint().max_tokens == 800

    def test_an_explicit_value_still_wins(self):
        assert make_endpoint(max_tokens=120).max_tokens == 120

    def test_truncation_is_reported(self, caplog):
        ep = make_endpoint(max_tokens=100)
        with caplog.at_level(logging.WARNING, logger="potato.ai.ai_endpoint"):
            ep._warn_if_truncated("length")
        assert "max_tokens" in caplog.text
        assert "cut off" in caplog.text

    def test_a_complete_reply_is_silent(self, caplog):
        ep = make_endpoint()
        with caplog.at_level(logging.WARNING, logger="potato.ai.ai_endpoint"):
            ep._warn_if_truncated("stop")
        assert caplog.text == ""


class TestVisionEndpointsConstrainTheShape:
    """
    openai_vision took an output_format and ignored it, setting only
    `{"type": "json_object"}` -- some JSON of some shape. The same task one
    click apart returned {"rationales": [...]} and
    {"annotation_guidance": {...}}, and the second rendered as "No hint
    available". The hint that did work worked because the model followed the
    prompt, not because anything held it to the format.
    """

    def _kwargs(self, output_format, json_mode=True):
        from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint

        ep = OpenAIVisionEndpoint.__new__(OpenAIVisionEndpoint)
        ep.model = "m"
        ep.max_tokens = 800
        ep.temperature = 0.1
        ep.json_mode = json_mode
        ep._schema_mode_refused = False
        ep.client = MagicMock()
        ep._create([{"role": "user", "content": "p"}], output_format)
        return ep.client.chat.completions.create.call_args.kwargs

    def test_the_schema_is_sent_when_one_is_asked_for(self):
        rf = self._kwargs(GeneralHintFormat)["response_format"]
        assert rf["type"] == "json_schema"
        assert set(rf["json_schema"]["schema"]["properties"]) == {
            "hint", "suggestive_choice"}

    def test_plain_json_mode_when_no_schema_is_asked_for(self):
        assert self._kwargs(None)["response_format"] == {"type": "json_object"}

    def test_json_mode_off_sends_nothing(self):
        assert "response_format" not in self._kwargs(GeneralHintFormat,
                                                     json_mode=False)

    def test_a_server_that_refuses_the_schema_falls_back_once(self):
        from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint

        ep = OpenAIVisionEndpoint.__new__(OpenAIVisionEndpoint)
        ep.model, ep.max_tokens, ep.temperature = "m", 800, 0.1
        ep.json_mode, ep._schema_mode_refused = True, False
        ep.client = MagicMock()

        calls = []

        def create(**kwargs):
            calls.append(kwargs.get("response_format"))
            if (kwargs.get("response_format") or {}).get("type") == "json_schema":
                raise ValueError("400: response_format json_schema unsupported")
            return MagicMock()

        ep.client.chat.completions.create.side_effect = create
        ep._create([{"role": "user", "content": "p"}], GeneralHintFormat)
        assert [c["type"] for c in calls] == ["json_schema", "json_object"]

        # Sticky: the refused round trip is paid once, not per click.
        assert ep._schema_mode_refused is True
        calls.clear()
        ep._create([{"role": "user", "content": "p"}], GeneralHintFormat)
        assert [c["type"] for c in calls] == ["json_object"]


class TestKeywordsAreGatedPerItemNotPerEndpoint:
    """
    `keyword_extraction=False` on the vision endpoints was declared as if every
    item were an image. `supports_assistant` already returns
    `keyword_extraction and not has_image_input`, and the capability filter
    runs per item -- so on a text-only task through a vision endpoint the
    Keyword button was absent and only two of the three assistants were
    reachable.
    """

    @pytest.mark.parametrize("module,name", [
        ("potato.ai.openai_vision_endpoint", "OpenAIVisionEndpoint"),
        ("potato.ai.ollama_vision_endpoint", "OllamaVisionEndpoint"),
        ("potato.ai.anthropic_vision_endpoint", "AnthropicVisionEndpoint"),
    ])
    def test_a_vision_endpoint_offers_keywords_on_text(self, module, name):
        import importlib

        caps = getattr(importlib.import_module(module), name).CAPABILITIES
        assert caps.supports_assistant("keyword", has_image_input=False) is True
        assert caps.supports_assistant("keyword", has_image_input=True) is False

    def test_the_filter_agrees_with_the_capability(self):
        # Through _filter_assistants_by_capability, which is what actually
        # decides which buttons the page renders.
        from potato.ai.ai_help_wrapper import DynamicAIHelp
        from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint

        wrapper = DynamicAIHelp()
        manager = MagicMock()
        manager.get_endpoint_capabilities.return_value = (
            OpenAIVisionEndpoint.CAPABILITIES)
        keys = ["hint", "keyword", "rationale"]

        assert wrapper._filter_assistants_by_capability(
            manager, keys, False) == ["hint", "keyword", "rationale"]
        assert wrapper._filter_assistants_by_capability(
            manager, keys, True) == ["hint", "rationale"]

    def test_a_detector_still_offers_none(self):
        # yolo has no text generation at all; this is not the same case.
        from potato.ai.yolo_endpoint import YOLOEndpoint

        caps = YOLOEndpoint.CAPABILITIES
        assert caps.supports_assistant("keyword", has_image_input=False) is False


class TestTheKeyCheckKnowsHowKeysAreSupplied:
    """
    The validator demanded `api_key` unconditionally for openai, so the code
    path written for self-hosted servers -- which substitute "EMPTY" themselves
    -- could not be reached through it, and a shell with OPENAI_API_KEY set
    still failed `validate --strict`.
    """

    def check(self, endpoint_type, cfg):
        from potato.server_utils.config_module import _api_key_is_reachable

        _api_key_is_reachable(endpoint_type, cfg, "ai_support")

    @pytest.fixture(autouse=True)
    def no_ambient_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_a_base_url_is_enough_for_openai(self):
        self.check("openai", {"base_url": "http://localhost:8000/v1"})

    def test_api_base_is_accepted_too(self):
        self.check("openai_vision", {"api_base": "http://localhost:8000/v1"})

    def test_the_environment_is_enough(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        self.check("openai", {})

    def test_an_explicit_key_is_enough(self):
        self.check("openai", {"api_key": "sk-x"})

    def test_openai_with_no_way_to_authenticate_is_refused(self):
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError) as exc:
            self.check("openai", {})
        # The message has to name all three ways out, or it sends the author
        # to write the placeholder the endpoint would have supplied anyway.
        assert "OPENAI_API_KEY" in str(exc.value)
        assert "base_url" in str(exc.value)

    @pytest.mark.parametrize("endpoint_type", ["anthropic", "huggingface", "gemini"])
    def test_a_key_is_still_required_where_the_endpoint_needs_one(self, endpoint_type):
        # These three read neither a base_url nor the environment, so for them
        # the requirement is real.
        from potato.server_utils.config_module import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self.check(endpoint_type, {"base_url": "http://x"})
        self.check(endpoint_type, {"api_key": "k"})


class TestAiConfigKeysAreCheckedAndDocumented:
    """
    `ai_support.ai_config` was opaque to the key checker and to the docs, so
    the keys that decide whether the feature works had no documented path and a
    typo inside the block passed silently.
    """

    def _warnings(self, cfg):
        from potato.server_utils.config_module import validate_unknown_keys

        records = []

        class _Collect(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = _Collect()
        logger = logging.getLogger("potato.server_utils.config_module")
        logger.addHandler(handler)
        try:
            validate_unknown_keys(cfg)
        finally:
            logger.removeHandler(handler)
        return records

    def test_a_typo_inside_ai_config_is_caught(self):
        warnings = self._warnings(
            {"ai_support": {"ai_config": {"modle": "m"}}})
        assert any("ai_support.ai_config.modle" in w for w in warnings)

    def test_a_typo_in_include_is_caught(self):
        # include.all is the switch most authors want, and its absence is
        # otherwise completely silent.
        warnings = self._warnings(
            {"ai_support": {"ai_config": {"include": {"al": True}}}})
        assert any("ai_support.ai_config.include.al" in w for w in warnings)

    def test_a_real_config_is_quiet(self):
        assert not self._warnings({"ai_support": {
            "enabled": True, "endpoint_type": "vllm",
            "ai_config": {"model": "m", "base_url": "u", "max_tokens": 800,
                          "temperature": 0.1, "include": {"all": True}}}})

    @pytest.mark.parametrize("key", [
        "ai_support.ai_config",
        "ai_support.ai_config.base_url",
        "ai_support.ai_config.max_tokens",
        "ai_support.ai_config.include.all",
        "ai_support.ai_config_file",
        "ai_support.endpoint_type",
    ])
    def test_the_keys_that_decide_whether_it_works_are_documented(self, key):
        from potato.server_utils.config_key_docs import iter_key_docs

        assert key in dict(iter_key_docs())

    def test_the_merge_shape_of_ai_config_file_is_written_down(self):
        # Writing the file with its own `ai_config:` block produces
        # ai_config.ai_config and is ignored, with a clean validate and an
        # "OpenAI API key is required" at boot that points at the wrong key.
        from potato.server_utils.config_key_docs import iter_key_docs

        summary = dict(iter_key_docs())["ai_support.ai_config_file"].summary
        assert "flat" in summary.lower()
