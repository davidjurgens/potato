"""Tests for the OpenAI Chat/Assistants trace converter."""

import pytest

from potato.trace_converter.converters.openai_converter import OpenAIConverter


class TestOpenAIConverterDetect:
    """Detection tests for OpenAI format."""

    def test_detect_chat_completions(self):
        converter = OpenAIConverter()
        data = [{
            "id": "chatcmpl-123",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_with_tool_calls(self):
        converter = OpenAIConverter()
        data = [{
            "messages": [
                {"role": "user", "content": "What is the weather?"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "get_weather", "arguments": '{"loc": "NYC"}'}}
                ]},
                {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_assistants_format(self):
        converter = OpenAIConverter()
        data = [{
            "id": "run_123",
            "assistant_id": "asst_abc",
            "steps": [
                {"type": "message_creation", "message": {"content": [{"text": {"value": "Hello"}}]}}
            ]
        }]
        assert converter.detect(data) is True

    def test_reject_anthropic_format(self):
        """Should NOT detect Anthropic-style content blocks."""
        converter = OpenAIConverter()
        data = [{
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}
            ]
        }]
        assert converter.detect(data) is False

    def test_reject_empty_data(self):
        converter = OpenAIConverter()
        assert converter.detect([]) is False
        assert converter.detect([{"random": "data"}]) is False

    def test_reject_non_dict(self):
        converter = OpenAIConverter()
        assert converter.detect(["string"]) is False


class TestOpenAIConverterChat:
    """Conversion tests for Chat Completions format."""

    def get_sample_chat(self):
        return [{
            "id": "chatcmpl-abc123",
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the weather in NYC?"},
                {"role": "assistant", "content": "Let me check.", "tool_calls": [
                    {"id": "call_1", "type": "function",
                     "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'}}
                ]},
                {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 72F"},
                {"role": "assistant", "content": "It's sunny and 72F in NYC."}
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        }]

    def test_basic_conversion(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_chat())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "chatcmpl-abc123"
        assert trace.agent_name == "gpt-4"

    def test_task_description_from_system(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_chat())
        assert traces[0].task_description == "You are a helpful assistant."

    def test_conversation_structure(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_chat())
        conv = traces[0].conversation
        # system skipped, user, tool_call action, thought, tool result, final assistant
        assert conv[0]["speaker"] == "User"
        assert "weather" in conv[0]["text"]
        assert conv[1]["speaker"] == "Agent (Action)"
        assert "get_weather" in conv[1]["text"]
        assert conv[2]["speaker"] == "Agent (Thought)"
        assert "check" in conv[2]["text"]
        assert conv[3]["speaker"] == "Environment"
        assert "Sunny" in conv[3]["text"]
        assert conv[4]["speaker"] == "Agent"
        assert "72F" in conv[4]["text"]

    def test_metadata_includes_usage(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_chat())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Model" and m["Value"] == "gpt-4" for m in meta)
        assert any(m["Property"] == "total_tokens" and m["Value"] == "150" for m in meta)

    def test_legacy_function_call(self):
        converter = OpenAIConverter()
        data = [{
            "id": "legacy_1",
            "messages": [
                {"role": "user", "content": "Calculate 2+2"},
                {"role": "assistant", "content": None,
                 "function_call": {"name": "calculator", "arguments": '{"expr": "2+2"}'}},
                {"role": "function", "name": "calculator", "content": "4"}
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        actions = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert len(actions) == 1
        assert "calculator" in actions[0]["text"]

    def test_single_item_not_list(self):
        converter = OpenAIConverter()
        data = self.get_sample_chat()[0]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_task_description_fallback_to_user(self):
        """When no system message, use first user message as task description."""
        converter = OpenAIConverter()
        data = [{"id": "t1", "messages": [
            {"role": "user", "content": "Tell me a joke"},
            {"role": "assistant", "content": "Why did the chicken..."}
        ]}]
        traces = converter.convert(data)
        assert traces[0].task_description == "Tell me a joke"

    def test_to_dict(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_chat())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
        assert isinstance(d["conversation"], list)


class TestOpenAIConverterAssistants:
    """Conversion tests for Assistants API format."""

    def get_sample_assistants(self):
        return [{
            "id": "run_abc123",
            "assistant_id": "asst_xyz",
            "model": "gpt-4-turbo",
            "instructions": "Help with travel planning",
            "steps": [
                {
                    "type": "message_creation",
                    "message": {"content": [{"text": {"value": "I'll help you plan your trip."}}]}
                },
                {
                    "type": "tool_calls",
                    "tool_calls": [{
                        "type": "function",
                        "function": {"name": "search_flights", "arguments": '{"from": "JFK"}'}
                    }]
                },
                {
                    "type": "tool_calls",
                    "tool_calls": [{
                        "type": "code_interpreter",
                        "code_interpreter": {
                            "input": "import pandas as pd\ndf.describe()",
                            "outputs": [{"type": "logs", "logs": "count    100\nmean     42.5"}]
                        }
                    }]
                }
            ]
        }]

    def test_convert_assistants(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_assistants())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "run_abc123"
        assert trace.task_description == "Help with travel planning"

    def test_assistants_conversation(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_assistants())
        conv = traces[0].conversation
        # message_creation, function tool_call, code_interpreter input, code output
        assert any("I'll help you" in t["text"] for t in conv)
        assert any("search_flights" in t["text"] for t in conv)
        assert any("pandas" in t["text"] for t in conv)
        assert any("count" in t["text"] for t in conv)

    def test_assistants_metadata(self):
        converter = OpenAIConverter()
        traces = converter.convert(self.get_sample_assistants())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Assistant ID" and m["Value"] == "asst_xyz" for m in meta)
        assert any(m["Property"] == "Steps" and m["Value"] == "3" for m in meta)
