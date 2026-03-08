"""Tests for the MCP (Model Context Protocol) interaction log converter."""

import pytest

from potato.trace_converter.converters.mcp_converter import MCPConverter


class TestMCPConverterDetect:
    """Detection tests for MCP format."""

    def test_detect_session_format(self):
        converter = MCPConverter()
        data = [{
            "id": "session_001",
            "server": "my-server",
            "interactions": [
                {"method": "tools/call", "params": {"name": "search"}, "result": {}}
            ]
        }]
        assert converter.detect(data) is True

    def test_detect_flat_interaction(self):
        converter = MCPConverter()
        data = [{"method": "tools/call", "params": {"name": "test"}}]
        assert converter.detect(data) is True

    def test_detect_resources_method(self):
        converter = MCPConverter()
        data = [{
            "interactions": [
                {"method": "resources/read", "params": {"uri": "file:///test"}}
            ]
        }]
        assert converter.detect(data) is True

    def test_reject_non_mcp_methods(self):
        converter = MCPConverter()
        data = [{
            "interactions": [
                {"method": "some/other/method", "params": {}}
            ]
        }]
        assert converter.detect(data) is False

    def test_reject_empty(self):
        converter = MCPConverter()
        assert converter.detect([]) is False
        assert converter.detect([{"random": "data"}]) is False


class TestMCPConverterConvert:
    """Conversion tests for MCP format."""

    def get_sample_data(self):
        return [{
            "id": "session_001",
            "server": "weather-server",
            "interactions": [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                    "result": {
                        "tools": [
                            {"name": "get_weather", "description": "Get weather"},
                            {"name": "get_forecast", "description": "Get forecast"}
                        ]
                    }
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_weather", "arguments": {"location": "NYC"}},
                    "result": {
                        "content": [{"type": "text", "text": "Sunny, 72F in New York City"}]
                    }
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "resources/read",
                    "params": {"uri": "file:///weather-data.json"},
                    "result": {
                        "contents": [{"text": "{\"temp\": 72, \"condition\": \"sunny\"}"}]
                    }
                },
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {"progressToken": "abc", "progress": 100, "total": 100}
                }
            ]
        }]

    def test_basic_conversion(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        assert len(traces) == 1
        trace = traces[0]
        assert trace.id == "session_001"
        assert trace.agent_name == "weather-server"

    def test_tool_call_conversation(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        # tools/list should show available tools
        assert any("Available tools" in t["text"] for t in conv)
        # tools/call should have action + result
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert any("get_weather" in t["text"] for t in action_turns)
        env_turns = [t for t in conv if t["speaker"] == "Environment"]
        assert any("Sunny" in t["text"] for t in env_turns)

    def test_resource_read(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert any("read_resource" in t["text"] for t in action_turns)

    def test_notification(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        conv = traces[0].conversation
        sys_turns = [t for t in conv if t["speaker"] == "System"]
        assert any("Progress" in t["text"] for t in sys_turns)

    def test_metadata(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        meta = traces[0].metadata_table
        assert any(m["Property"] == "Server" and m["Value"] == "weather-server" for m in meta)
        assert any(m["Property"] == "Tool Calls" and m["Value"] == "1" for m in meta)
        assert any(m["Property"] == "Resource Reads" and m["Value"] == "1" for m in meta)

    def test_error_handling(self):
        converter = MCPConverter()
        data = [{
            "id": "err_session",
            "interactions": [{
                "method": "tools/call",
                "params": {"name": "failing_tool", "arguments": {}},
                "result": {},
                "error": {"code": -32000, "message": "Tool execution failed"}
            }]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        err_turns = [t for t in conv if "Error" in t["speaker"]]
        assert len(err_turns) == 1
        assert "failed" in err_turns[0]["text"]

    def test_prompts_get(self):
        converter = MCPConverter()
        data = [{
            "id": "prompt_session",
            "interactions": [{
                "method": "prompts/get",
                "params": {"name": "summarize"},
                "result": {
                    "messages": [
                        {"role": "user", "content": {"type": "text", "text": "Summarize this text"}}
                    ]
                }
            }]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert any("get_prompt" in t["text"] for t in conv)

    def test_single_item(self):
        converter = MCPConverter()
        data = self.get_sample_data()[0]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_to_dict(self):
        converter = MCPConverter()
        traces = converter.convert(self.get_sample_data())
        d = traces[0].to_dict()
        assert "id" in d
        assert "conversation" in d
