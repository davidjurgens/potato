"""Tests for the OpenTelemetry/OTLP trace converter."""

import pytest

from potato.trace_converter.converters.otel_converter import OTELConverter


class TestOTELConverterDetect:
    """Detection tests for OTEL format."""

    def test_detect_otlp_format(self):
        converter = OTELConverter()
        data = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "traceId": "abc123",
                        "spanId": "span1",
                        "name": "LLM call"
                    }]
                }]
            }]
        }
        assert converter.detect(data) is True

    def test_detect_flat_format(self):
        converter = OTELConverter()
        data = [{
            "trace_id": "abc123",
            "span_id": "span1",
            "name": "LLM call",
            "attributes": {}
        }]
        assert converter.detect(data) is True

    def test_reject_missing_span_id(self):
        converter = OTELConverter()
        data = [{"trace_id": "abc123", "name": "test"}]
        assert converter.detect(data) is False

    def test_reject_empty(self):
        converter = OTELConverter()
        assert converter.detect([]) is False
        assert converter.detect([{"random": "data"}]) is False


class TestOTELConverterConvertOTLP:
    """Conversion tests for OTLP nested format."""

    def get_sample_otlp(self):
        return {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [
                        {
                            "traceId": "trace001",
                            "spanId": "span_root",
                            "parentSpanId": "",
                            "name": "AgentRun",
                            "startTimeUnixNano": "1700000000000000000",
                            "endTimeUnixNano": "1700000005000000000",
                            "attributes": [
                                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4"}}
                            ]
                        },
                        {
                            "traceId": "trace001",
                            "spanId": "span_llm",
                            "parentSpanId": "span_root",
                            "name": "LLM",
                            "startTimeUnixNano": "1700000001000000000",
                            "endTimeUnixNano": "1700000002000000000",
                            "attributes": [
                                {"key": "gen_ai.prompt", "value": {"stringValue": "What is 2+2?"}},
                                {"key": "gen_ai.completion", "value": {"stringValue": "The answer is 4."}},
                                {"key": "llm.token_count.prompt", "value": {"intValue": 10}},
                                {"key": "llm.token_count.completion", "value": {"intValue": 8}}
                            ]
                        },
                        {
                            "traceId": "trace001",
                            "spanId": "span_tool",
                            "parentSpanId": "span_root",
                            "name": "calculator",
                            "startTimeUnixNano": "1700000003000000000",
                            "endTimeUnixNano": "1700000003500000000",
                            "attributes": [
                                {"key": "tool.name", "value": {"stringValue": "calculator"}},
                                {"key": "tool.input", "value": {"stringValue": "2+2"}},
                                {"key": "tool.output", "value": {"stringValue": "4"}}
                            ]
                        }
                    ]
                }]
            }]
        }

    def test_convert_otlp(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_otlp())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "trace001"
        assert trace.task_description == "AgentRun"

    def test_otlp_conversation(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_otlp())
        conv = traces[0].conversation
        # Should have: prompt (User), completion (Agent), tool action, tool result
        user_turns = [t for t in conv if t["speaker"] == "User"]
        agent_turns = [t for t in conv if t["speaker"] == "Agent"]
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        env_turns = [t for t in conv if t["speaker"] == "Environment"]
        assert len(user_turns) >= 1
        assert len(agent_turns) >= 1
        assert len(action_turns) >= 1
        assert len(env_turns) >= 1

    def test_otlp_metadata(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_otlp())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Spans" and m["Value"] == "3" for m in meta)
        assert any(m["Property"] == "Model" and m["Value"] == "gpt-4" for m in meta)

    def test_otlp_attribute_flattening(self):
        converter = OTELConverter()
        attrs = [
            {"key": "string_key", "value": {"stringValue": "hello"}},
            {"key": "int_key", "value": {"intValue": 42}},
            {"key": "bool_key", "value": {"boolValue": True}},
        ]
        result = converter._flatten_otlp_attributes(attrs)
        assert result["string_key"] == "hello"
        assert result["int_key"] == 42
        assert result["bool_key"] is True


class TestOTELConverterConvertFlat:
    """Conversion tests for flattened per-span format."""

    def get_sample_flat(self):
        return [
            {
                "trace_id": "trace_flat_001",
                "span_id": "span_root",
                "parent_span_id": "",
                "name": "MainTask",
                "attributes": {
                    "gen_ai.request.model": "claude-3-opus"
                }
            },
            {
                "trace_id": "trace_flat_001",
                "span_id": "span_llm",
                "parent_span_id": "span_root",
                "name": "LLM",
                "attributes": {
                    "gen_ai.prompt": "Summarize this text",
                    "gen_ai.completion": "Here is the summary...",
                    "gen_ai.usage.prompt_tokens": 50,
                    "gen_ai.usage.completion_tokens": 30
                }
            }
        ]

    def test_convert_flat(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_flat())
        assert len(traces) == 1
        assert traces[0].id == "trace_flat_001"

    def test_flat_conversation(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_flat())
        conv = traces[0].conversation
        assert any("Summarize" in t["text"] for t in conv)
        assert any("summary" in t["text"] for t in conv)

    def test_multiple_traces(self):
        converter = OTELConverter()
        data = self.get_sample_flat() + [{
            "trace_id": "trace_flat_002",
            "span_id": "span_x",
            "parent_span_id": "",
            "name": "AnotherTask",
            "attributes": {}
        }]
        traces = converter.convert(data)
        assert len(traces) == 2

    def test_to_dict(self):
        converter = OTELConverter()
        traces = converter.convert(self.get_sample_flat())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
