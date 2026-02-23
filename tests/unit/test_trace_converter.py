"""
Tests for the trace converter module.

Tests converter registration, format detection, and conversion
for all supported trace formats.
"""

import json
import pytest

from potato.trace_converter.base import BaseTraceConverter, CanonicalTrace
from potato.trace_converter.registry import TraceConverterRegistry
from potato.trace_converter.converters.react_converter import ReActConverter
from potato.trace_converter.converters.langchain_converter import LangChainConverter
from potato.trace_converter.converters.langfuse_converter import LangfuseConverter
from potato.trace_converter.converters.atif_converter import ATIFConverter
from potato.trace_converter.converters.webarena_converter import WebArenaConverter


class TestConverterRegistry:
    """Tests for the TraceConverterRegistry."""

    def test_registry_has_builtin_converters(self):
        """All built-in converters should be registered."""
        from potato.trace_converter.registry import converter_registry
        formats = converter_registry.get_supported_formats()
        assert "react" in formats
        assert "langchain" in formats
        assert "langfuse" in formats
        assert "atif" in formats
        assert "webarena" in formats

    def test_registry_list_converters(self):
        """list_converters should return metadata for all converters."""
        from potato.trace_converter.registry import converter_registry
        converters = converter_registry.list_converters()
        assert len(converters) >= 5
        for info in converters:
            assert "format_name" in info
            assert "description" in info

    def test_registry_convert_unknown_format(self):
        """Converting with unknown format should raise ValueError."""
        registry = TraceConverterRegistry()
        with pytest.raises(ValueError, match="Unknown trace format"):
            registry.convert("nonexistent", [])

    def test_registry_duplicate_registration(self):
        """Registering same format twice should raise ValueError."""
        registry = TraceConverterRegistry()
        converter = ReActConverter()
        registry.register(converter)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(converter)


class TestReActConverter:
    """Tests for the ReAct JSON converter."""

    def get_sample_data(self):
        return [{
            "id": "trace_001",
            "task": "Book a flight",
            "agent": "GPT-4",
            "steps": [
                {
                    "thought": "I need to search for flights",
                    "action": "search_flights(origin='JFK')",
                    "observation": "Found 3 flights"
                },
                {
                    "thought": "The cheapest is BA117",
                    "action": "book_flight(id='BA117')",
                    "observation": "Booking confirmed"
                }
            ],
            "metadata": {"tokens": 1200}
        }]

    def test_detect(self):
        converter = ReActConverter()
        assert converter.detect(self.get_sample_data()) is True
        assert converter.detect([{"no_steps": True}]) is False
        assert converter.detect([]) is False

    def test_convert_basic(self):
        converter = ReActConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1

        trace = traces[0]
        assert trace.id == "trace_001"
        assert trace.task_description == "Book a flight"
        assert trace.agent_name == "GPT-4"
        assert len(trace.conversation) == 6  # 2 steps x 3 turns each

    def test_convert_conversation_structure(self):
        converter = ReActConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation

        assert conv[0]["speaker"] == "Agent (Thought)"
        assert conv[1]["speaker"] == "Agent (Action)"
        assert conv[2]["speaker"] == "Environment"
        assert "search for flights" in conv[0]["text"]

    def test_convert_metadata(self):
        converter = ReActConverter()
        traces = converter.convert(self.get_sample_data())
        meta = traces[0].metadata_table

        assert any(m["Property"] == "Steps" for m in meta)
        assert any(m["Property"] == "tokens" for m in meta)

    def test_convert_single_item(self):
        """Should handle a single dict (not wrapped in list)."""
        converter = ReActConverter()
        data = self.get_sample_data()[0]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_to_dict(self):
        converter = ReActConverter()
        traces = converter.convert(self.get_sample_data())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
        assert isinstance(d["conversation"], list)


class TestLangChainConverter:
    """Tests for the LangChain/LangSmith converter."""

    def get_sample_data(self):
        return [{
            "id": "run-123",
            "name": "AgentExecutor",
            "run_type": "chain",
            "inputs": {"input": "What is the weather?"},
            "outputs": {"output": "It's sunny"},
            "child_runs": [
                {
                    "name": "ChatOpenAI",
                    "run_type": "llm",
                    "inputs": {},
                    "outputs": {"generations": [[{"text": "I should check the weather"}]]}
                },
                {
                    "name": "get_weather",
                    "run_type": "tool",
                    "inputs": {"location": "NYC"},
                    "outputs": {"output": "Sunny, 72F"}
                }
            ]
        }]

    def test_detect(self):
        converter = LangChainConverter()
        assert converter.detect(self.get_sample_data()) is True
        assert converter.detect([{"no_run_type": True}]) is False

    def test_convert(self):
        converter = LangChainConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1

        trace = traces[0]
        assert trace.id == "run-123"
        assert trace.task_description == "What is the weather?"
        assert len(trace.conversation) == 3  # thought + action + observation

    def test_convert_conversation_speakers(self):
        converter = LangChainConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation

        assert conv[0]["speaker"] == "Agent (Thought)"
        assert conv[1]["speaker"] == "Agent (Action)"
        assert "get_weather" in conv[1]["text"]
        assert conv[2]["speaker"] == "Environment"


class TestLangfuseConverter:
    """Tests for the Langfuse converter."""

    def get_sample_data(self):
        return [{
            "id": "trace-456",
            "name": "my-agent",
            "input": {"query": "Translate hello to French"},
            "observations": [
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "I need to translate"},
                    "model": "gpt-4",
                    "usage": {"totalTokens": 100}
                },
                {
                    "type": "SPAN",
                    "name": "translate",
                    "input": {"text": "hello", "lang": "fr"},
                    "output": {"result": "bonjour"}
                }
            ]
        }]

    def test_detect(self):
        converter = LangfuseConverter()
        assert converter.detect(self.get_sample_data()) is True
        assert converter.detect([{"no_observations": True}]) is False

    def test_convert(self):
        converter = LangfuseConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1

        trace = traces[0]
        assert trace.id == "trace-456"
        assert trace.task_description == "Translate hello to French"
        assert len(trace.conversation) == 3


class TestATIFConverter:
    """Tests for the ATIF converter."""

    def get_sample_data(self):
        return [{
            "trace_id": "atif_001",
            "task": {"description": "Solve math problem", "domain": "math"},
            "agent": {"name": "MathAgent", "model": "gpt-4"},
            "steps": [
                {
                    "thought": "I need to calculate",
                    "action": {"tool": "calculator", "params": {"expr": "2+2"}},
                    "observation": "4"
                }
            ],
            "outcome": {"success": True, "reward": 1.0},
            "metrics": {"total_tokens": 500}
        }]

    def test_detect(self):
        converter = ATIFConverter()
        assert converter.detect(self.get_sample_data()) is True
        assert converter.detect([{"steps": []}]) is False  # No trace_id

    def test_convert(self):
        converter = ATIFConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1

        trace = traces[0]
        assert trace.id == "atif_001"
        assert trace.task_description == "Solve math problem"
        assert trace.agent_name == "MathAgent"

    def test_metadata_includes_outcome(self):
        converter = ATIFConverter()
        traces = converter.convert(self.get_sample_data())
        meta = traces[0].metadata_table

        assert any(m["Property"] == "Success" and m["Value"] == "True" for m in meta)
        assert any(m["Property"] == "Domain" and m["Value"] == "math" for m in meta)


class TestWebArenaConverter:
    """Tests for the WebArena converter."""

    def get_sample_data(self):
        return [{
            "task_id": "wa_001",
            "intent": "Search for wireless headphones",
            "url": "https://amazon.com",
            "actions": [
                {
                    "action_type": "type",
                    "element": {"tag": "input", "text": "Search", "id": "search"},
                    "value": "wireless headphones",
                    "thought": "I need to type the search query"
                },
                {
                    "action_type": "click",
                    "element": {"tag": "button", "text": "Go"},
                    "thought": "Click the search button",
                    "observation": "Results loaded"
                }
            ],
            "evaluation": {"success": True, "reward": 1.0}
        }]

    def test_detect(self):
        converter = WebArenaConverter()
        assert converter.detect(self.get_sample_data()) is True
        assert converter.detect([{"no_actions": True}]) is False

    def test_convert(self):
        converter = WebArenaConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1

        trace = traces[0]
        assert trace.id == "wa_001"
        assert trace.task_description == "Search for wireless headphones"

    def test_action_formatting(self):
        converter = WebArenaConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation

        # Should have formatted action strings
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert len(action_turns) == 2
        assert "type_text" in action_turns[0]["text"]
        assert "click" in action_turns[1]["text"]


class TestAutoDetection:
    """Tests for format auto-detection."""

    def test_detect_react(self):
        from potato.trace_converter.registry import converter_registry
        data = [{"id": "1", "task": "test", "steps": [{"thought": "t", "action": "a"}]}]
        assert converter_registry.detect_format(data) == "react"

    def test_detect_langchain(self):
        from potato.trace_converter.registry import converter_registry
        data = [{"id": "1", "run_type": "chain", "child_runs": []}]
        assert converter_registry.detect_format(data) == "langchain"

    def test_detect_langfuse(self):
        from potato.trace_converter.registry import converter_registry
        data = [{"id": "1", "observations": [{"type": "GENERATION"}]}]
        assert converter_registry.detect_format(data) == "langfuse"

    def test_detect_returns_none_for_unknown(self):
        from potato.trace_converter.registry import converter_registry
        data = [{"random": "data"}]
        assert converter_registry.detect_format(data) is None


class TestCanonicalTrace:
    """Tests for the CanonicalTrace data model."""

    def test_to_dict_minimal(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test task",
            conversation=[{"speaker": "Agent", "text": "Hello"}]
        )
        d = trace.to_dict()
        assert d["id"] == "test"
        assert d["task_description"] == "Test task"
        assert len(d["conversation"]) == 1
        # Should not include empty optional fields
        assert "agent_name" not in d
        assert "metadata_table" not in d

    def test_to_dict_full(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test task",
            conversation=[],
            agent_name="TestAgent",
            metadata_table=[{"Property": "Steps", "Value": "3"}],
            screenshots=["img1.png"],
            extra_fields={"custom": "value"}
        )
        d = trace.to_dict()
        assert d["agent_name"] == "TestAgent"
        assert d["metadata_table"][0]["Property"] == "Steps"
        assert d["screenshots"] == ["img1.png"]
        assert d["custom"] == "value"
