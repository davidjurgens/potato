"""Regression test: OpenAI endpoint free-text query (output_format=None).

Before the D3 fix, ``query()`` unconditionally called
``output_format.model_json_schema()``, so every free-text query (e.g. the model
arena) crashed with ``'NoneType' object has no attribute 'model_json_schema'``.
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_endpoint():
    from potato.ai.openai_endpoint import OpenAIEndpoint
    # The base endpoint reads config["ai_config"] directly (the factory unwraps
    # ai_support before constructing the endpoint).
    cfg = {"ai_config": {"base_url": "http://localhost:9/v1", "model": "gpt-x"}}
    with patch("potato.ai.openai_endpoint.OpenAI") as MockOpenAI:
        client = MagicMock()
        msg = MagicMock(); msg.content = "hello world"
        client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=msg)])
        MockOpenAI.return_value = client
        ep = OpenAIEndpoint(cfg)
        ep.client = client
        return ep, client


class TestFreeTextQuery:
    def test_free_text_query_does_not_crash(self):
        ep, client = _make_endpoint()
        out = ep.query("Explain DPO in one sentence.", None)  # output_format=None
        assert out == "hello world"

    def test_free_text_query_omits_response_format(self):
        ep, client = _make_endpoint()
        ep.query("prompt", None)
        _, kwargs = client.chat.completions.create.call_args
        assert "response_format" not in kwargs
        assert "text_format" not in kwargs  # the old buggy param is gone

    def test_structured_query_adds_response_format(self):
        ep, client = _make_endpoint()

        class Schema:
            @staticmethod
            def model_json_schema():
                return {"type": "object", "properties": {}}
        ep.query("prompt", Schema)
        _, kwargs = client.chat.completions.create.call_args
        assert kwargs["response_format"]["type"] == "json_schema"
