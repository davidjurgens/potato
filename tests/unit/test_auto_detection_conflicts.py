"""
Cross-format auto-detection conflict tests.

Ensures each sample format is only detected by its own converter,
preventing false positive matches between formats with similar structures.
"""

import pytest

from potato.trace_converter.registry import converter_registry


class TestAutoDetectionConflicts:
    """Verify that format auto-detection is unambiguous across all converters."""

    # --- Sample data for each format ---

    def _react_sample(self):
        return [{"id": "1", "task": "test", "steps": [
            {"thought": "t", "action": "a", "observation": "o"}
        ]}]

    def _langchain_sample(self):
        return [{"id": "1", "run_type": "chain", "child_runs": [],
                 "inputs": {"input": "test"}, "outputs": {}}]

    def _langfuse_sample(self):
        return [{"id": "1", "observations": [{"type": "GENERATION", "name": "gpt"}]}]

    def _webarena_sample(self):
        return [{"task_id": "1", "intent": "Click button", "actions": [
            {"action_type": "click", "element": {"tag": "button"}}
        ]}]

    def _openai_sample(self):
        return [{"id": "chatcmpl-1", "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]}]

    def _anthropic_sample(self):
        return [{"id": "msg_1", "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}
        ]}]

    def _swebench_sample(self):
        return [{"instance_id": "django__django-11133",
                 "problem_statement": "Bug in X",
                 "patch": "diff --git a/..."}]

    def _otel_flat_sample(self):
        return [{"trace_id": "abc", "span_id": "s1", "name": "test",
                 "attributes": {}}]

    def _otel_otlp_sample(self):
        return {"resourceSpans": [{"scopeSpans": [{"spans": [
            {"traceId": "abc", "spanId": "s1", "name": "test"}
        ]}]}]}

    def _mcp_sample(self):
        return [{"id": "session_1", "interactions": [
            {"method": "tools/call", "params": {"name": "test"}, "result": {}}
        ]}]

    def _crewai_sample(self):
        return [{"id": "crew_1", "task": "test",
                 "agents": [{"role": "R", "goal": "G"}],
                 "steps": [{"agent": "R", "thought": "t", "action": "a"}]}]

    def _autogen_sample(self):
        return [{"id": "ag_1", "task": "test",
                 "messages": [{"sender": "user_proxy", "receiver": "asst", "content": "hi"}]}]

    def _langgraph_sample(self):
        return [{"id": "lg_1", "events": [
            {"node": "agent", "type": "on_chain_start", "data": {"input": "test"}}
        ]}]

    # --- Tests ---

    def test_react_detected_correctly(self):
        assert converter_registry.detect_format(self._react_sample()) == "react"

    def test_langchain_detected_correctly(self):
        assert converter_registry.detect_format(self._langchain_sample()) == "langchain"

    def test_langfuse_detected_correctly(self):
        assert converter_registry.detect_format(self._langfuse_sample()) == "langfuse"

    def test_webarena_detected_correctly(self):
        assert converter_registry.detect_format(self._webarena_sample()) == "webarena"

    def test_openai_detected_correctly(self):
        assert converter_registry.detect_format(self._openai_sample()) == "openai"

    def test_anthropic_detected_correctly(self):
        assert converter_registry.detect_format(self._anthropic_sample()) == "anthropic"

    def test_swebench_detected_correctly(self):
        assert converter_registry.detect_format(self._swebench_sample()) == "swebench"

    def test_otel_flat_detected_correctly(self):
        assert converter_registry.detect_format(self._otel_flat_sample()) == "otel"

    def test_otel_otlp_detected_correctly(self):
        assert converter_registry.detect_format(self._otel_otlp_sample()) == "otel"

    def test_mcp_detected_correctly(self):
        assert converter_registry.detect_format(self._mcp_sample()) == "mcp"

    def test_crewai_detected_correctly(self):
        assert converter_registry.detect_format(self._crewai_sample()) == "multi_agent"

    def test_autogen_detected_correctly(self):
        assert converter_registry.detect_format(self._autogen_sample()) == "multi_agent"

    def test_langgraph_detected_correctly(self):
        assert converter_registry.detect_format(self._langgraph_sample()) == "multi_agent"

    def test_unknown_returns_none(self):
        assert converter_registry.detect_format([{"random": "data"}]) is None

    def test_openai_not_detected_as_anthropic(self):
        """OpenAI (string content) should not be detected as Anthropic (content blocks)."""
        from potato.trace_converter.converters.anthropic_converter import AnthropicConverter
        converter = AnthropicConverter()
        assert converter.detect(self._openai_sample()) is False

    def test_anthropic_not_detected_as_openai(self):
        """Anthropic (content blocks) should not be detected as OpenAI (string content)."""
        from potato.trace_converter.converters.openai_converter import OpenAIConverter
        converter = OpenAIConverter()
        assert converter.detect(self._anthropic_sample()) is False

    def test_react_not_detected_as_multi_agent(self):
        """ReAct (thought/action/observation) should not be detected as multi-agent."""
        from potato.trace_converter.converters.multi_agent_converter import MultiAgentConverter
        converter = MultiAgentConverter()
        assert converter.detect(self._react_sample()) is False

    def test_openai_not_detected_as_autogen(self):
        """OpenAI messages (role-based) should not be detected as AutoGen (sender-based)."""
        from potato.trace_converter.converters.multi_agent_converter import MultiAgentConverter
        converter = MultiAgentConverter()
        assert converter.detect(self._openai_sample()) is False

    def test_all_formats_registered(self):
        """All 11 formats should be registered."""
        formats = converter_registry.get_supported_formats()
        expected = ["react", "langchain", "langfuse", "atif", "webarena",
                    "swebench", "otel", "mcp", "anthropic", "openai", "multi_agent"]
        for fmt in expected:
            assert fmt in formats, f"Format '{fmt}' not registered"
