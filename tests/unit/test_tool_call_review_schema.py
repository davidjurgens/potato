"""Unit tests for the tool_call_review schema (M12)."""

import pytest

from potato.server_utils.schemas.tool_call_review import generate_tool_call_review_layout
from potato.server_utils.schemas.registry import schema_registry


def _scheme(**kw):
    base = {"annotation_type": "tool_call_review", "name": "tools",
            "description": "Review each tool call", "steps_key": "steps"}
    base.update(kw)
    return base


class TestToolCallReview:
    def test_generates_container_and_input(self):
        html, kb = generate_tool_call_review_layout(_scheme())
        assert "tool-call-review-container" in html
        assert "tool-call-review-input" in html
        assert kb == []

    def test_default_verdict_options(self):
        html, _ = generate_tool_call_review_layout(_scheme())
        for v in ("correct", "wrong_tool", "wrong_args"):
            assert v in html

    def test_custom_verdict_options(self):
        html, _ = generate_tool_call_review_layout(_scheme(verdict_options=["ok", "bad", "ordering"]))
        assert '"verdict_options": ["ok", "bad", "ordering"]' in html

    def test_extracts_tool_calls_js(self):
        html, _ = generate_tool_call_review_layout(_scheme())
        assert "tool_calls" in html and "extractCalls" in html

    def test_persistence_seeds_from_hidden(self):
        html, _ = generate_tool_call_review_layout(_scheme())
        assert "function restore()" in html and "JSON.parse(h.value)" in html

    def test_registered(self):
        assert "tool_call_review" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        html, _ = schema_registry.generate({
            "annotation_type": "tool_call_review", "name": "x", "description": "d"})
        assert "tool-call-review-container" in html
