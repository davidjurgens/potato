"""A cut-off reply says so, and the documented timeout is a value you can set.

Two defects with the same shape: a check that exists, is correct, and is not
reached on the path that needs it.

`_warn_if_truncated` was called from four methods in three of fifteen endpoint
modules, and from no `chat_query` anywhere. `vllm_endpoint.query` called it;
`vllm_endpoint.chat_query`, 28 lines below, did not. It also compared the reason
against the literal `"length"`, which is OpenAI's spelling -- Anthropic says
`max_tokens`, Gemini says `MAX_TOKENS`, Ollama reports `done_reason` rather than
`finish_reason` -- so three providers could not have matched even where the call
was made. This matters past the log line: a truncated structured reply goes
through `parseStringToJson`'s salvage step and arrives as a plausible dict of
the wrong shape, which renders as "No rationales available" -- exactly what a
dead endpoint renders. Without the warning there is nothing to tell them apart.

`ModelConfig.timeout` declared `int = 60` and passed the key on only when it
differed from 60, so the documented default was the one value you could not set:
`timeout: 61` gave you 61, and `timeout: 60` gave you the endpoint's own
fallback, which is 30, 60 or 120 depending on type.

Both halves of each fix are pinned here: that the vocabulary is wide enough, and
that every call site exists to use it.
"""

import ast
import logging
import pathlib

import pytest

from potato.ai.ai_endpoint import BaseAIEndpoint
from potato.solo_mode.config import ModelConfig
from potato.solo_mode.llm_labeler import LLMLabelingThread

AI_DIR = pathlib.Path(__file__).resolve().parents[2] / "potato" / "ai"

#: Endpoint modules that talk to a token-budgeted language model. The
#: segmentation and detection endpoints (sam, sam3, yolo, visual_ai) have no
#: max_tokens to overrun and are deliberately absent.
LLM_ENDPOINT_MODULES = [
    "anthropic_endpoint", "anthropic_vision_endpoint", "gemini_endpoint",
    "huggingface_endpoint", "ollama_endpoint", "ollama_vision_endpoint",
    "openai_endpoint", "openai_vision_endpoint", "openrouter_endpoint",
    "vllm_endpoint",
]

GENERATING_METHODS = (
    "query", "chat_query", "query_with_image", "chat_query_with_image")


class TestTheVocabularyIsWideEnoughForEveryProvider:
    """The check has to recognise the word each provider actually sends."""

    @pytest.mark.parametrize("reason,provider", [
        ("length", "openai / vllm / openrouter / huggingface / ollama"),
        ("max_tokens", "anthropic"),
        ("MAX_TOKENS", "gemini"),
        ("model_length", "vllm, context exhausted"),
    ])
    def test_each_providers_spelling_counts_as_truncation(self, reason, provider):
        assert BaseAIEndpoint._is_truncation_reason(reason), (
            f"{provider} reports truncation as {reason!r} and it was not "
            f"recognised, so that provider can cut a reply in silence")

    @pytest.mark.parametrize("reason", ["stop", "end_turn", "STOP", "tool_use"])
    def test_a_normal_finish_is_not_reported(self, reason):
        # A warning on every reply teaches nobody anything.
        assert not BaseAIEndpoint._is_truncation_reason(reason)

    def test_no_reason_at_all_is_not_truncation(self):
        # A provider that reports nothing is not evidence either way, and
        # guessing "truncated" would fire on every OpenRouter model that omits
        # the field.
        assert not BaseAIEndpoint._is_truncation_reason(None)
        assert not BaseAIEndpoint._is_truncation_reason("")

    def test_an_sdk_enum_is_read_by_name(self):
        """Gemini hands back an enum, not a string.

        `str(FinishReason.MAX_TOKENS)` renders as `"FinishReason.MAX_TOKENS"` on
        some SDK versions and `"MAX_TOKENS"` on others, so comparing the whole
        rendered string works on one and fails on the other.
        """
        import enum

        class FinishReason(enum.Enum):
            MAX_TOKENS = "MAX_TOKENS"
            STOP = "STOP"

        assert BaseAIEndpoint._is_truncation_reason(FinishReason.MAX_TOKENS)
        assert not BaseAIEndpoint._is_truncation_reason(FinishReason.STOP)


class TestEveryGeneratingMethodChecks:
    """The completeness half: a new endpoint cannot ship silent.

    This is structural rather than driven, because driving fifteen providers
    needs fifteen live servers. The driven half is below; this one is what
    notices the sixteenth endpoint module.
    """

    def _methods_missing_the_check(self):
        missing, seen = [], 0
        for stem in LLM_ENDPOINT_MODULES:
            path = AI_DIR / f"{stem}.py"
            assert path.exists(), (
                f"{stem}.py is gone; this list names a module that no longer "
                f"exists, so it vouches for nothing")
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in GENERATING_METHODS:
                    continue
                seen += 1
                if not any(isinstance(call, ast.Call)
                           and isinstance(call.func, ast.Attribute)
                           and call.func.attr == "_warn_if_truncated"
                           for call in ast.walk(node)):
                    missing.append(f"{stem}.{node.name}")
        # Without this the loop could match nothing -- a renamed method, a
        # moved directory -- and report a clean sweep having examined zero
        # functions.
        assert seen >= 18, (
            f"only {seen} generating methods found across "
            f"{len(LLM_ENDPOINT_MODULES)} modules; the scan has stopped "
            f"reaching them and is measuring nothing")
        return missing

    def test_no_generating_method_is_silent(self):
        missing = self._methods_missing_the_check()
        assert not missing, (
            f"these can cut a reply off and log nothing: {sorted(missing)}. A "
            f"truncated structured reply parses into a plausible dict of the "
            f"wrong shape and renders exactly like a dead endpoint.")


class TestItActuallyLogs:
    """The driven half, on the two providers whose spelling used to be missed."""

    class _Response:
        def __init__(self, stop_reason):
            self.stop_reason = stop_reason
            self.content = [type("B", (), {"text": "a cut off repl"})()]

    def _anthropic(self):
        from potato.ai.ai_endpoint import AIEndpointFactory
        return AIEndpointFactory.create_endpoint({"ai_support": {
            "enabled": True, "endpoint_type": "anthropic",
            "ai_config": {"model": "m", "api_key": "k", "max_tokens": 50}}})

    def test_anthropic_max_tokens_is_reported(self, caplog):
        endpoint = self._anthropic()
        endpoint.client = type("C", (), {"messages": type("M", (), {
            "create": staticmethod(
                lambda **kw: TestItActuallyLogs._Response("max_tokens"))})()})()

        with caplog.at_level(logging.WARNING):
            assert endpoint.query("hello") == "a cut off repl"

        assert any("hit max_tokens" in r.getMessage()
                   for r in caplog.records), (
            f"no truncation warning; records were "
            f"{[r.getMessage() for r in caplog.records]}")

    def test_anthropic_normal_stop_logs_nothing(self, caplog):
        endpoint = self._anthropic()
        endpoint.client = type("C", (), {"messages": type("M", (), {
            "create": staticmethod(
                lambda **kw: TestItActuallyLogs._Response("end_turn"))})()})()

        with caplog.at_level(logging.WARNING):
            endpoint.query("hello")

        assert not [r for r in caplog.records
                    if "hit max_tokens" in r.getMessage()]

    def test_ollama_reports_done_reason_not_finish_reason(self, caplog):
        """Ollama puts the reason under a different key at a different level.

        Reading `finish_reason` off an Ollama response returns None forever, so
        this is the case a copy of the OpenAI call site would have missed even
        after the vocabulary was widened.
        """
        from potato.ai.ollama_endpoint import OllamaEndpoint

        endpoint = object.__new__(OllamaEndpoint)
        endpoint.max_tokens = 50
        endpoint.temperature = 0.1
        endpoint.model = "m"
        endpoint.ai_config = {}
        endpoint.client = type("C", (), {"chat": staticmethod(lambda **kw: {
            "done_reason": "length",
            "message": {"content": '{"label": "a"'},
        })})()

        with caplog.at_level(logging.WARNING):
            endpoint.chat_query([{"role": "user", "content": "hi"}])

        assert any("hit max_tokens" in r.getMessage() for r in caplog.records), (
            f"Ollama truncation went unreported; records were "
            f"{[r.getMessage() for r in caplog.records]}")


class TestTheDocumentedTimeoutIsSettable:
    """`timeout: 60` has to mean 60 seconds."""

    @pytest.mark.parametrize("endpoint_type", ["openai", "anthropic"])
    @pytest.mark.parametrize("written", [60, 61, 600])
    def test_an_explicit_timeout_reaches_the_endpoint(self, endpoint_type,
                                                      written):
        model = ModelConfig(endpoint_type=endpoint_type, model="m",
                            api_key="k", timeout=written)
        config = model.to_endpoint_config()["ai_support"]["ai_config"]
        assert config.get("timeout") == written, (
            f"timeout: {written} did not reach the endpoint config. 60 was "
            f"once the one value you could not set, because it was the "
            f"sentinel for 'unset'.")

        endpoint = LLMLabelingThread.create_endpoint_from_model_config(model)
        effective = getattr(endpoint, "timeout", None)
        if effective is None:
            effective = getattr(endpoint.client, "timeout", None)
        assert effective == written

    def test_leaving_it_out_does_not_overwrite_the_endpoint_default(self):
        """Absent still means "the endpoint decides".

        Passing a blanket 60 would have quietly halved ollama_vision's 120s,
        which is the one endpoint type that needs the longest of them.
        """
        model = ModelConfig(endpoint_type="openai", model="m", api_key="k")
        config = model.to_endpoint_config()["ai_support"]["ai_config"]
        assert "timeout" not in config
        assert model.timeout is None

    def test_the_sentinel_is_outside_the_range_of_valid_values(self):
        """The defect in one line.

        Any int sentinel makes that int unsettable. Only a value no author can
        write -- None -- can mean "not set".
        """
        assert ModelConfig.timeout is None or not isinstance(
            ModelConfig(endpoint_type="openai", model="m").timeout, int), (
            "the unset sentinel is an integer again, so that integer is now "
            "the one timeout nobody can configure")

    def test_a_config_dict_without_a_timeout_stays_unset(self):
        """`from_dict` must not re-introduce the numeric default.

        It read `model_data.get('timeout', 60)`, which would hand the dataclass
        a 60 that the guard below then could not distinguish from an author
        writing 60 on purpose.
        """
        from potato.solo_mode.config import _parse_model_config as parse_model_config

        model = parse_model_config({"endpoint_type": "openai", "model": "m"})
        assert model.timeout is None
        assert "timeout" not in model.to_endpoint_config()[
            "ai_support"]["ai_config"]

        model = parse_model_config(
            {"endpoint_type": "openai", "model": "m", "timeout": 60})
        assert model.timeout == 60
        assert model.to_endpoint_config()[
            "ai_support"]["ai_config"]["timeout"] == 60


class TestAnInertSelectionArmSaysSo:
    """The largest of the five selection weights can route nothing, silently.

    `_select_weighted_pool` skips empty pools and renormalises their weight onto
    the rest, which is correct behaviour and completely invisible. The default
    `direct_confidence` estimator self-reports in the 0.95-1.0 band while
    `confidence_threshold` defaults to 0.5, so on an unmodified config the
    low-confidence pool is empty on every refresh and `low_confidence_weight`
    (0.4, the largest) never fires. Seven measured runs over two prompts and
    five token budgets produced no confidence within 0.45 of the threshold.

    The threshold that would fix it depends on the estimator, and a
    self-reported confidence moves with the prompt wording, so this pins the
    diagnostic rather than a number.
    """

    def _selector(self):
        from potato.solo_mode.instance_selector import InstanceSelector
        return InstanceSelector()

    def test_an_always_empty_pool_is_reported_with_the_number_to_change(
            self, caplog):
        predictions = {f"i{n}": {"scheme": {"confidence_score": c}}
                       for n, c in enumerate([1.0, 0.95, 1.0, 0.95])}

        with caplog.at_level(logging.WARNING):
            self._selector().refresh_pools(set(predictions),
                                           llm_predictions=predictions)

        warnings = [r.getMessage() for r in caplog.records
                    if "low-confidence pool is empty" in r.getMessage()]
        assert warnings, (
            f"the arm carrying the largest weight routed nothing and said "
            f"nothing; records were {[r.getMessage() for r in caplog.records]}")
        # Naming the observed floor is the whole point: without it the reader
        # knows the pool is empty but not which direction to move the threshold.
        assert "0.95" in warnings[0] and "0.50" in warnings[0], warnings[0]

    def test_a_genuinely_uncertain_prediction_produces_no_warning(self, caplog):
        # A warning on every run is a warning nobody reads.
        predictions = {f"i{n}": {"scheme": {"confidence_score": c}}
                       for n, c in enumerate([1.0, 0.30, 1.0, 0.95])}

        with caplog.at_level(logging.WARNING):
            selector = self._selector()
            selector.refresh_pools(set(predictions),
                                   llm_predictions=predictions)

        assert selector._low_confidence_pool
        assert not [r for r in caplog.records
                    if "low-confidence pool is empty" in r.getMessage()]

    def test_having_no_predictions_at_all_is_not_this_warning(self, caplog):
        # Before the labeler has run there is nothing to be confident about,
        # and reporting a miscalibrated threshold then would be noise.
        with caplog.at_level(logging.WARNING):
            self._selector().refresh_pools({"i0", "i1"}, llm_predictions=None)

        assert not [r for r in caplog.records
                    if "low-confidence pool is empty" in r.getMessage()]


class TestTheKeyDocDoesNotQuoteADefaultThereIsNoneOf:
    """`ai_support.ai_config.timeout` claimed `default=30`.

    That is true for five of the nine endpoint types and wrong for the other
    four, and the one that is furthest out is ollama_vision at 120 -- the type
    most likely to need the number. A doc that names a single figure invites an
    author to write it, which is how the solo-mode bug above stayed invisible:
    60 looked like the documented value on both sides.

    Reads the real defaults out of the endpoint modules, so it stops applying
    on its own the day they agree.
    """

    def _declared_timeout_defaults(self):
        """`self.ai_config.get("timeout", N)` from every endpoint module."""
        defaults = {}
        for path in sorted(AI_DIR.glob("*endpoint*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and len(node.args) == 2):
                    continue
                key = node.args[0]
                fallback = node.args[1]
                if not (isinstance(key, ast.Constant) and key.value == "timeout"):
                    continue
                if isinstance(fallback, ast.Constant) and isinstance(
                        fallback.value, int):
                    defaults.setdefault(path.stem, set()).add(fallback.value)
        return defaults

    def test_the_defaults_really_do_disagree(self):
        # The premise. If this stops holding, the test below is asserting
        # against a fact that no longer exists and should be deleted.
        defaults = self._declared_timeout_defaults()
        assert len(defaults) >= 5, (
            f"only found timeout defaults in {sorted(defaults)}; the scan has "
            f"stopped reaching the endpoint modules")
        values = {v for vals in defaults.values() for v in vals}
        assert len(values) > 1, (
            f"every endpoint now defaults to {values}, so a single documented "
            f"default would be honest -- delete this class and put it back")

    def test_the_key_doc_names_no_single_default(self):
        from potato.server_utils.config_key_docs import CONFIG_KEY_DOCS

        doc = CONFIG_KEY_DOCS["ai_support.ai_config.timeout"]
        rendered = repr(getattr(doc, "default", None))
        assert "30" not in rendered, (
            "the key doc quotes 30 as the default timeout, which is right for "
            "openai/anthropic/gemini/huggingface/vllm and wrong for ollama "
            "(60), the vision endpoints (60) and ollama_vision (120)")

    def test_the_summary_says_what_actually_happens(self):
        from potato.server_utils.config_key_docs import CONFIG_KEY_DOCS

        summary = CONFIG_KEY_DOCS["ai_support.ai_config.timeout"].summary
        values = {v for vals in self._declared_timeout_defaults().values()
                  for v in vals}
        missing = [v for v in sorted(values) if str(v) not in summary]
        assert not missing, (
            f"the summary does not mention the {missing} second default(s), so "
            f"an author configuring one of those endpoint types cannot learn "
            f"what they are changing from. Summary was: {summary!r}")
