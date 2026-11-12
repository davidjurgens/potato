"""Every language-model endpoint answers a chat.

`BaseAIEndpoint.chat_query` flattens the conversation and calls
`self.query(prompt)` with one argument. Six endpoint classes -- huggingface,
gemini, openrouter, openai_vision, anthropic_vision, ollama_vision -- had no
chat_query of their own, and their query() requires an output format, so the
call raised TypeError before any request was sent. ChatManager caught it and
told the annotator "Sorry, I encountered an error" on every message; the coding
proxy and the simulator failed the same way.

Gemini's query() was broken independently: it passed `generation_config=` to
`generate_content`, which has no such parameter, so every Gemini call failed.

The stubs below stand in for each provider's transport and record what they
were sent. The Gemini stub checks its arguments against the installed SDK's own
signature, so it fails on the keyword the real client rejects.
"""

import inspect
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from potato.ai.ai_endpoint import AIEndpointFactory, BaseAIEndpoint

MESSAGES = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "earlier reply"},
    {"role": "user", "content": "second"},
]

#: Registered types that are not language models: they detect or segment and
#: have nothing to say in a conversation. A new endpoint type must either
#: answer chat_query itself or be added here on purpose.
NOT_CHAT_MODELS = {"yolo", "sam", "sam3"}


def _bare(cls, **attrs):
    """An endpoint without its constructor, so no SDK client or network."""
    endpoint = object.__new__(cls)
    endpoint.model = "m"
    endpoint.max_tokens = 50
    endpoint.temperature = 0.1
    endpoint.ai_config = {"api_key": "k"}
    for name, value in attrs.items():
        setattr(endpoint, name, value)
    return endpoint


def _openai_style_reply(text="the answer", finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason,
        message=SimpleNamespace(content=text))])


class TestEveryChatModelOverridesTheFlatteningFallback:

    def test_no_registered_language_model_relies_on_the_base_chat_query(self):
        inherited, checked = [], 0
        types = set(AIEndpointFactory._lazy_endpoints) | set(
            AIEndpointFactory._endpoints)
        for endpoint_type in sorted(types - NOT_CHAT_MODELS):
            try:
                cls = AIEndpointFactory._resolve_endpoint_class(endpoint_type)
            except Exception:
                continue  # optional SDK not installed here
            checked += 1
            if cls.chat_query is BaseAIEndpoint.chat_query:
                inherited.append(endpoint_type)
        assert checked >= 10, (
            f"only {checked} endpoint classes resolved; the check is not "
            f"reaching the registry")
        assert not inherited, (
            f"{inherited} inherit the base chat_query, which calls "
            f"query(prompt) with no output format")


class TestChatSupportAcceptsOnlyTypesThatCanChat:

    def test_every_accepted_type_answers_chat_query_itself(self):
        """Validation must not let a config through to a chat that cannot answer.

        Reads the accepted list by asking the validator about every registered
        type, rather than from a copy of the list.
        """
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_chat_support_config)
        accepted = []
        for endpoint_type in sorted(set(AIEndpointFactory._lazy_endpoints)
                                    | set(AIEndpointFactory._endpoints)):
            try:
                validate_chat_support_config({"chat_support": {
                    "enabled": True, "endpoint_type": endpoint_type}})
            except ConfigValidationError:
                continue
            accepted.append(endpoint_type)
            try:
                cls = AIEndpointFactory._resolve_endpoint_class(endpoint_type)
            except Exception:
                continue  # optional SDK not installed here
            assert cls.chat_query is not BaseAIEndpoint.chat_query, (
                f"chat_support accepts {endpoint_type!r}, which has no "
                f"chat_query of its own")
        assert {"openai_vision", "anthropic_vision", "ollama_vision"} <= set(
            accepted), f"vision endpoints refused; accepted {accepted}"

    @pytest.mark.parametrize("endpoint_type", sorted(NOT_CHAT_MODELS))
    def test_detectors_and_segmenters_are_refused(self, endpoint_type):
        from potato.server_utils.config_module import (
            ConfigValidationError, validate_chat_support_config)
        with pytest.raises(ConfigValidationError):
            validate_chat_support_config({"chat_support": {
                "enabled": True, "endpoint_type": endpoint_type}})


class TestHuggingface:

    def test_the_conversation_reaches_chat_completion_as_free_text(self):
        from potato.ai.huggingface_endpoint import HuggingfaceEndpoint
        sent = {}

        def chat_completion(**kw):
            sent.update(kw)
            return _openai_style_reply()

        endpoint = _bare(HuggingfaceEndpoint,
                         client=SimpleNamespace(chat_completion=chat_completion))
        assert endpoint.chat_query(MESSAGES) == "the answer"
        assert sent["messages"] == MESSAGES
        assert "response_format" not in sent


class TestOpenAIVision:

    def test_the_conversation_is_sent_without_json_mode(self):
        """`_create` would force JSON on a conversational reply."""
        from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint
        sent = {}

        def create(**kw):
            sent.update(kw)
            return _openai_style_reply()

        client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create)))
        endpoint = _bare(OpenAIVisionEndpoint, client=client, json_mode=True,
                         _schema_mode_refused=False)
        assert endpoint.chat_query(MESSAGES) == "the answer"
        assert sent["messages"] == MESSAGES
        assert "response_format" not in sent


class TestAnthropicVision:

    def test_the_system_prompt_goes_in_the_system_field(self):
        from potato.ai.anthropic_vision_endpoint import AnthropicVisionEndpoint
        sent = {}

        def create(**kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(text="the answer")])

        endpoint = _bare(AnthropicVisionEndpoint,
                         client=SimpleNamespace(messages=SimpleNamespace(create=create)))
        assert endpoint.chat_query(MESSAGES) == "the answer"
        assert sent["system"] == "SYS"
        assert sent["messages"] == MESSAGES[1:]


class TestOllamaVision:

    def test_the_conversation_is_sent_without_a_format_schema(self):
        from potato.ai.ollama_vision_endpoint import OllamaVisionEndpoint
        sent = {}

        def chat(**kw):
            sent.update(kw)
            return {"done_reason": "stop", "message": {"content": "the answer"}}

        endpoint = _bare(OllamaVisionEndpoint, client=SimpleNamespace(chat=chat))
        assert endpoint.chat_query(MESSAGES) == "the answer"
        assert sent["messages"] == MESSAGES
        assert "format" not in sent


class TestOpenRouter:

    @pytest.fixture
    def post(self, monkeypatch):
        import potato.ai.openrouter_endpoint as module
        sent = {}

        def fake_post(url, **kw):
            sent["url"] = url
            sent.update(kw)
            return SimpleNamespace(status_code=200, text="", json=lambda: {
                "choices": [{"finish_reason": "stop",
                             "message": {"content": "the answer"}}]})

        monkeypatch.setattr(module.requests, "post", fake_post)
        return sent

    def _endpoint(self, **ai_config):
        from potato.ai.openrouter_endpoint import OpenRouterEndpoint
        endpoint = _bare(OpenRouterEndpoint)
        endpoint.ai_config = {"api_key": "k", **ai_config}
        endpoint._initialize_client()
        return endpoint

    def test_the_conversation_is_posted_as_free_text(self, post):
        assert self._endpoint().chat_query(MESSAGES) == "the answer"
        assert post["json"]["messages"] == MESSAGES
        assert "response_format" not in post["json"]

    @pytest.mark.parametrize("written, expected", [(None, 30), (7, 7)])
    def test_every_request_carries_a_timeout(self, post, written, expected):
        """requests.post without a timeout waits forever on a stalled provider."""
        ai_config = {} if written is None else {"timeout": written}
        self._endpoint(**ai_config).chat_query(MESSAGES)
        assert post["timeout"] == expected


class TestGemini:

    @pytest.fixture
    def client(self):
        """A client whose generate_content accepts what the real one accepts."""
        from google.genai import types
        from google.genai.models import Models
        real = inspect.signature(Models.generate_content)
        sent = {}

        def generate_content(**kw):
            real.bind(None, **kw)  # TypeError on a keyword the SDK lacks
            types.GenerateContentConfig(**kw.get("config") or {})
            sent.update(kw)
            return SimpleNamespace(
                text='{"label": "a"}',
                candidates=[SimpleNamespace(finish_reason="STOP")])

        return SimpleNamespace(models=SimpleNamespace(
            generate_content=generate_content)), sent

    def test_chat_maps_roles_and_passes_the_system_instruction(self, client):
        from potato.ai.gemini_endpoint import GeminiEndpoint
        stub, sent = client
        endpoint = _bare(GeminiEndpoint, client=stub)
        assert endpoint.chat_query(MESSAGES) == '{"label": "a"}'
        assert sent["config"]["system_instruction"] == "SYS"
        assert [(c["role"], c["parts"][0]["text"]) for c in sent["contents"]] == [
            ("user", "first"), ("model", "earlier reply"), ("user", "second")]

    def test_query_uses_a_keyword_generate_content_accepts(self, client):
        from potato.ai.gemini_endpoint import GeminiEndpoint

        class Format(BaseModel):
            label: str

        stub, sent = client
        endpoint = _bare(GeminiEndpoint, client=stub)
        assert endpoint.query("classify this", Format) == '{"label": "a"}'
        assert sent["config"]["response_json_schema"] == Format.model_json_schema()
        assert sent["config"]["response_mime_type"] == "application/json"
