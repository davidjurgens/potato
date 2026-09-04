"""
The AI endpoints against a real OpenAI-compatible server.

Audit 7 found that `ai_support` did not work against a local server through
any endpoint_type, and that every one of the four causes produced the same
symptom: the model answered correctly, the server returned 200, tokens were
spent, and the annotator was shown "No hint available". Separating them took a
live server, so the regression test needs one too. Everything that can be
checked offline is in tests/unit/test_audit7_ai_endpoints.py.

Point it at any OpenAI-compatible server::

    POTATO_LIVE_LLM_URL=http://localhost:8000/v1 \\
    POTATO_LIVE_LLM_MODEL=my-model \\
        pytest tests/integration/test_audit7_live_endpoints.py -v

Without POTATO_LIVE_LLM_URL the whole module skips.
"""

import os

import pytest

from potato.ai.prompt.models_module import (
    GeneralHintFormat, GeneralKeywordFormat, GeneralRationaleFormat)

LIVE_URL = os.environ.get("POTATO_LIVE_LLM_URL")
LIVE_MODEL = os.environ.get("POTATO_LIVE_LLM_MODEL", "")

pytestmark = pytest.mark.skipif(
    not LIVE_URL,
    reason="set POTATO_LIVE_LLM_URL (and POTATO_LIVE_LLM_MODEL) to run these")


def _root(url):
    """The server root, for endpoints that append /v1 themselves."""
    url = url.rstrip("/")
    return url[: -len("/v1")] if url.endswith("/v1") else url


def _with_v1(url):
    url = url.rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


def _resolve_model():
    if LIVE_MODEL:
        return LIVE_MODEL
    import requests

    listing = requests.get(f"{_with_v1(LIVE_URL)}/models", timeout=10).json()
    return listing["data"][0]["id"]


@pytest.fixture(scope="module")
def model():
    return _resolve_model()


PROMPT = ("Give a hint for classifying the sentiment of: 'The battery died "
          "after two hours and support never answered.' "
          "Labels: positive, negative, neutral.")

RATIONALE_PROMPT = ("Explain the reasoning for each label for: 'The battery "
                    "died after two hours and support never answered.' "
                    "Labels: positive, negative, neutral.")


def _vllm(model, **overrides):
    from potato.ai.vllm_endpoint import VLLMEndpoint

    config = {"model": model, "base_url": _root(LIVE_URL), "temperature": 0,
              "timeout": 180}
    config.update(overrides)
    return VLLMEndpoint({"ai_config": config})


def _openai(model, **overrides):
    from potato.ai.openai_endpoint import OpenAIEndpoint

    config = {"model": model, "base_url": _with_v1(LIVE_URL),
              "api_key": "EMPTY", "temperature": 0, "timeout": 180}
    config.update(overrides)
    return OpenAIEndpoint({"ai_config": config})


def _openai_vision(model, **overrides):
    from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint

    config = {"model": model, "base_url": _with_v1(LIVE_URL),
              "temperature": 0, "timeout": 180}
    config.update(overrides)
    return OpenAIVisionEndpoint({"ai_config": config})


class TestTheServerHonoursTheSchemaWeSend:
    """
    vLLM ignored the `guided_json` this package used to send: no error, no
    warning, 200 with prose. `response_format: json_schema` is the parameter it
    reads, and the one all three endpoints now use.
    """

    def test_vllm_hint_has_the_keys_the_caller_asked_for(self, model):
        out = _vllm(model, max_tokens=800).query(PROMPT, GeneralHintFormat)
        assert isinstance(out, dict), out
        assert "hint" in out and out["hint"], out

    def test_vllm_rationale_covers_every_label(self, model):
        out = _vllm(model, max_tokens=800).query(RATIONALE_PROMPT,
                                                 GeneralRationaleFormat)
        assert isinstance(out, dict), out
        assert len(out.get("rationales", [])) >= 3, out

    def test_vllm_keywords_come_back_as_a_label_map(self, model):
        out = _vllm(model, max_tokens=800).query(PROMPT, GeneralKeywordFormat)
        assert isinstance(out, dict), out
        assert "label_keywords" in out, out

    def test_openai_vision_hint_keeps_its_shape(self, model):
        # This endpoint took an output_format and dropped it, so the same task
        # returned {"hint": ...} one click and {"annotation_guidance": {...}}
        # the next. Only the first rendered.
        out = _openai_vision(model, max_tokens=800).query(
            PROMPT, GeneralHintFormat)
        assert isinstance(out, dict), out
        assert "hint" in out, out

    def test_openai_vision_rationale_keeps_its_shape(self, model):
        out = _openai_vision(model, max_tokens=800).query(
            RATIONALE_PROMPT, GeneralRationaleFormat)
        assert "rationales" in out, out


class TestTheAIHelpPathReturnsOneType:
    """
    openai returns the raw content string; the route reads a string as an
    error. The correct answer reached the browser as
    {"error": "{\\"hint\\": ...}"} and the tooltip said "No hint available".
    """

    def test_a_string_answer_is_normalized_to_a_dict(self, model):
        endpoint = _openai(model, max_tokens=800)
        raw = endpoint.query(PROMPT, GeneralHintFormat)
        assert isinstance(raw, str), "openai's query still returns the content"
        assert isinstance(endpoint._as_structured(raw, GeneralHintFormat), dict)

    def test_the_normalized_answer_carries_the_schema_keys(self, model):
        endpoint = _openai(model, max_tokens=800)
        out = endpoint._as_structured(
            endpoint.query(PROMPT, GeneralHintFormat), GeneralHintFormat)
        assert "hint" in out, out


class TestTheDefaultTokenBudgetFinishesTheAnswer:
    """
    At the old default of 100 the generation is cut mid-object, the salvage
    step returns the inner fragment, and the caller gets a LabelRationale where
    it asked for a GeneralRationaleFormat.
    """

    def test_the_default_completes_a_three_label_rationale(self, model):
        endpoint = _vllm(model)          # no max_tokens: use the default
        assert endpoint.max_tokens == 800
        out = endpoint.query(RATIONALE_PROMPT, GeneralRationaleFormat)
        assert len(out.get("rationales", [])) >= 3, out

    def test_the_old_default_is_what_it_looked_like(self, model, caplog):
        # Pinned so the two failure modes -- truncation and unconstrained
        # output -- stay distinguishable: this one now announces itself.
        import logging

        endpoint = _vllm(model, max_tokens=100)
        with caplog.at_level(logging.WARNING, logger="potato.ai.ai_endpoint"):
            out = endpoint.query(RATIONALE_PROMPT, GeneralRationaleFormat)
        assert "rationales" not in out, (
            "100 tokens finished a three-label rationale; re-tune this test")
        assert "max_tokens" in caplog.text, (
            "truncation was silent, which is what made it look like the "
            "unconstrained-output bug")
