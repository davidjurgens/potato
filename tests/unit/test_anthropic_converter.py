"""Tests for the Anthropic Claude Messages trace converter."""

import pytest

from potato.trace_converter.converters.anthropic_converter import AnthropicConverter


class TestAnthropicConverterDetect:
    """Detection tests for Anthropic format."""

    def test_detect_content_blocks(self):
        converter = AnthropicConverter()
        data = [{
            "id": "msg_123",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "Hi there!"}
                ]}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_tool_use_blocks(self):
        converter = AnthropicConverter()
        data = [{
            "messages": [
                {"role": "user", "content": "What is the weather?"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"location": "NYC"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny, 72F"}
                ]}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_request_response_format(self):
        converter = AnthropicConverter()
        data = [{
            "id": "trace_001",
            "request": {
                "model": "claude-sonnet-4-20250514",
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}
                ]
            },
            "response": {"content": [{"type": "text", "text": "response"}]}
        }]
        assert converter.detect(data) is True

    def test_reject_openai_format(self):
        """Should NOT detect OpenAI-style string content."""
        converter = AnthropicConverter()
        data = [{
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"}
            ]
        }]
        assert converter.detect(data) is False

    def test_reject_empty(self):
        converter = AnthropicConverter()
        assert converter.detect([]) is False
        assert converter.detect([{"random": "data"}]) is False


class TestAnthropicConverterConvert:
    """Conversion tests for Anthropic Messages format."""

    def get_sample_data(self):
        return [{
            "id": "msg_abc123",
            "model": "claude-sonnet-4-20250514",
            "system": "You are a helpful weather assistant.",
            "messages": [
                {"role": "user", "content": "What is the weather in NYC?"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "Let me check the weather for you."},
                    {"type": "tool_use", "id": "toolu_1", "name": "get_weather",
                     "input": {"location": "NYC"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1",
                     "content": "Sunny, 72F"}
                ]},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "It's sunny and 72F in NYC."}
                ]}
            ],
            "usage": {"input_tokens": 200, "output_tokens": 100}
        }]

    def test_basic_conversion(self):
        converter = AnthropicConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "msg_abc123"
        assert trace.agent_name == "claude-sonnet-4-20250514"

    def test_task_description_from_system(self):
        converter = AnthropicConverter()
        traces = converter.convert(self.get_sample_data())
        assert traces[0].task_description == "You are a helpful weather assistant."

    def test_conversation_structure(self):
        converter = AnthropicConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        assert conv[0]["speaker"] == "User"
        assert "weather" in conv[0]["text"]
        assert conv[1]["speaker"] == "Agent"
        assert "check" in conv[1]["text"]
        assert conv[2]["speaker"] == "Agent (Action)"
        assert "get_weather" in conv[2]["text"]
        assert conv[3]["speaker"] == "Environment"
        assert "Sunny" in conv[3]["text"]
        assert conv[4]["speaker"] == "Agent"
        assert "72F" in conv[4]["text"]

    def test_metadata_includes_usage(self):
        converter = AnthropicConverter()
        traces = converter.convert(self.get_sample_data())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Model" for m in meta)
        assert any(m["Property"] == "input_tokens" and m["Value"] == "200" for m in meta)
        assert any(m["Property"] == "output_tokens" and m["Value"] == "100" for m in meta)

    def test_tool_result_error(self):
        converter = AnthropicConverter()
        data = [{
            "id": "err_1",
            "messages": [
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1",
                     "content": "Connection timeout", "is_error": True}
                ]}
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert any(t["speaker"] == "Environment (Error)" for t in conv)

    def test_thinking_blocks(self):
        converter = AnthropicConverter()
        data = [{
            "id": "think_1",
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "Let me reason about this..."},
                    {"type": "text", "text": "Here's my answer."}
                ]}
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert conv[0]["speaker"] == "Agent (Thought)"
        assert "reason" in conv[0]["text"]
        assert conv[1]["speaker"] == "Agent"

    def test_request_response_format(self):
        converter = AnthropicConverter()
        data = [{
            "id": "rr_001",
            "request": {
                "model": "claude-sonnet-4-20250514",
                "system": "You help with math.",
                "messages": [
                    {"role": "user", "content": "What is 2+2?"}
                ]
            },
            "response": {
                "content": [{"type": "text", "text": "The answer is 4."}],
                "usage": {"input_tokens": 50, "output_tokens": 20}
            }
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        trace = traces[0]
        assert trace.task_description == "You help with math."
        conv = trace.conversation
        assert any(t["speaker"] == "User" and "2+2" in t["text"] for t in conv)
        assert any(t["speaker"] == "Agent" and "4" in t["text"] for t in conv)

    def test_single_item_not_list(self):
        converter = AnthropicConverter()
        data = self.get_sample_data()[0]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_system_as_content_blocks(self):
        converter = AnthropicConverter()
        data = [{
            "id": "sys_blocks",
            "system": [{"type": "text", "text": "You are a helpful assistant."}],
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": [{"type": "text", "text": "Hello!"}]}
            ]
        }]
        traces = converter.convert(data)
        assert traces[0].task_description == "You are a helpful assistant."

    def test_to_dict(self):
        converter = AnthropicConverter()
        traces = converter.convert(self.get_sample_data())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
        assert isinstance(d["conversation"], list)

    def test_task_description_fallback_to_user(self):
        converter = AnthropicConverter()
        data = [{
            "id": "fb_1",
            "messages": [
                {"role": "user", "content": "Tell me a joke"},
                {"role": "assistant", "content": [{"type": "text", "text": "Why did the chicken..."}]}
            ]
        }]
        traces = converter.convert(data)
        assert traces[0].task_description == "Tell me a joke"
