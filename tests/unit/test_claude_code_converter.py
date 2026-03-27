"""
Unit tests for ClaudeCodeConverter.

Tests conversion of Claude Code traces, Anthropic Messages API format,
and generic coding agent formats. Verifies structured_turns preservation.
"""

import pytest
from potato.trace_converter.converters.claude_code_converter import ClaudeCodeConverter


class TestClaudeCodeConverter:
    """Tests for ClaudeCodeConverter."""

    @pytest.fixture
    def converter(self):
        return ClaudeCodeConverter()

    # --- Format detection ---

    def test_detect_structured_turns(self, converter):
        data = {"structured_turns": [{"role": "assistant", "content": "x", "tool_calls": []}]}
        assert converter.detect(data) is True

    def test_detect_messages_with_coding_tools(self, converter):
        data = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}}
                ]}
            ]
        }
        assert converter.detect(data) is True

    def test_detect_turns_with_tool_calls(self, converter):
        data = {
            "turns": [
                {"role": "assistant", "content": "x", "tool_calls": [
                    {"tool": "Edit", "input": {}, "output": ""}
                ]}
            ]
        }
        assert converter.detect(data) is True

    def test_no_detect_plain_conversation(self, converter):
        data = {"messages": [{"role": "user", "content": "hello"}]}
        assert converter.detect(data) is False

    def test_no_detect_non_coding_tools(self, converter):
        data = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "get_weather", "input": {"city": "NYC"}}
                ]}
            ]
        }
        assert converter.detect(data) is False

    # --- Conversion: structured_turns format ---

    def test_convert_structured_turns(self, converter):
        data = {
            "id": "sess_1",
            "task_description": "Fix the bug",
            "model": "claude-sonnet",
            "structured_turns": [
                {"role": "user", "content": "Fix it", "tool_calls": []},
                {"role": "assistant", "content": "On it.", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "a.py"}, "output": "code here"}
                ]}
            ]
        }
        traces = converter.convert(data)
        assert len(traces) == 1
        t = traces[0]
        assert t.id == "sess_1"
        assert t.task_description == "Fix the bug"
        assert "structured_turns" in t.extra_fields
        turns = t.extra_fields["structured_turns"]
        assert len(turns) == 2
        assert turns[1]["tool_calls"][0]["tool"] == "Read"
        assert turns[1]["tool_calls"][0]["output_type"] == "code"

    # --- Conversion: Anthropic Messages format ---

    def test_convert_anthropic_messages(self, converter):
        data = {
            "id": "msg_001",
            "model": "claude-sonnet-4-20250514",
            "messages": [
                {"role": "user", "content": "Fix the auth bypass"},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "I'll investigate."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Read",
                     "input": {"file_path": "login.py"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1",
                     "content": "def login(): pass"}
                ]},
                {"role": "assistant", "content": [
                    {"type": "text", "text": "Found the issue."},
                    {"type": "tool_use", "id": "toolu_2", "name": "Edit",
                     "input": {"file_path": "login.py",
                               "old_string": "pass", "new_string": "check_auth()"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_2",
                     "content": "Edit applied"}
                ]}
            ]
        }
        traces = converter.convert(data)
        t = traces[0]
        turns = t.extra_fields["structured_turns"]

        # Should have user + 2 assistant turns
        user_turns = [turn for turn in turns if turn["role"] == "user"]
        assistant_turns = [turn for turn in turns if turn["role"] == "assistant"]
        assert len(user_turns) == 1
        assert len(assistant_turns) == 2

        # First assistant turn should have Read tool
        assert assistant_turns[0]["tool_calls"][0]["tool"] == "Read"
        assert assistant_turns[0]["tool_calls"][0]["output"] == "def login(): pass"

        # Second assistant turn should have Edit tool
        assert assistant_turns[1]["tool_calls"][0]["tool"] == "Edit"
        assert assistant_turns[1]["tool_calls"][0]["output_type"] == "diff"

    def test_thinking_blocks(self, converter):
        data = {
            "messages": [
                {"role": "user", "content": "Fix it"},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "I'll fix it."},
                    {"type": "tool_use", "id": "t1", "name": "Bash",
                     "input": {"command": "ls"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "file1.py"}
                ]}
            ]
        }
        traces = converter.convert(data)
        turns = traces[0].extra_fields["structured_turns"]
        assistant = [t for t in turns if t["role"] == "assistant"][0]
        assert "[Thinking]" in assistant["content"]
        assert assistant["tool_calls"][0]["tool"] == "Bash"
        assert assistant["tool_calls"][0]["output_type"] == "terminal"

    # --- Conversion: generic turns format ---

    def test_convert_generic_turns(self, converter):
        data = {
            "id": "trace_1",
            "task": "Add pagination",
            "turns": [
                {"role": "assistant", "content": "Working on it.", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "api.py"}, "output": "code"}
                ]}
            ]
        }
        traces = converter.convert(data)
        t = traces[0]
        assert t.task_description == "Add pagination"
        assert "structured_turns" in t.extra_fields

    # --- Conversion: steps format ---

    def test_convert_steps_format(self, converter):
        data = {
            "id": "swe_1",
            "task": "Fix issue #123",
            "steps": [
                {"thought": "I should look at the code.",
                 "action": {"tool": "Read", "input": {"file_path": "x.py"}},
                 "observation": "def foo(): pass"},
                {"thought": "Need to edit.",
                 "action": "edit src/x.py",
                 "observation": "Applied"}
            ]
        }
        traces = converter.convert(data)
        turns = traces[0].extra_fields["structured_turns"]
        assert len(turns) == 2
        assert turns[0]["tool_calls"][0]["tool"] == "Read"
        assert turns[0]["tool_calls"][0]["output"] == "def foo(): pass"

    # --- Output enrichment ---

    def test_output_type_enrichment(self, converter):
        data = {
            "structured_turns": [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "x.py"}, "output": "code"},
                    {"tool": "Edit", "input": {"old_string": "a", "new_string": "b"}, "output": "ok"},
                    {"tool": "Bash", "input": {"command": "ls"}, "output": "files"},
                    {"tool": "Write", "input": {"file_path": "y.py", "content": "x"}, "output": "ok"},
                ]}
            ]
        }
        traces = converter.convert(data)
        tcs = traces[0].extra_fields["structured_turns"][0]["tool_calls"]
        assert tcs[0]["output_type"] == "code"
        assert tcs[1]["output_type"] == "diff"
        assert tcs[2]["output_type"] == "terminal"
        assert tcs[3]["output_type"] == "code"

    def test_language_enrichment(self, converter):
        data = {
            "structured_turns": [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "app.js"}, "output": "x"},
                ]}
            ]
        }
        traces = converter.convert(data)
        tc = traces[0].extra_fields["structured_turns"][0]["tool_calls"][0]
        assert tc["language"] == "javascript"

    # --- Backward compatibility ---

    def test_conversation_flattening(self, converter):
        data = {
            "structured_turns": [
                {"role": "user", "content": "Fix bug", "tool_calls": []},
                {"role": "assistant", "content": "On it.", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "x.py"}, "output": "code"}
                ]}
            ]
        }
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert any(c["speaker"] == "User" for c in conv)
        assert any(c["speaker"] == "Agent" for c in conv)
        assert any("Read" in c["speaker"] for c in conv)
        assert any(c["speaker"] == "Environment" for c in conv)

    # --- Metadata ---

    def test_metadata_extraction(self, converter):
        data = {
            "id": "s1",
            "model": "claude-opus",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
            "structured_turns": [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"tool": "Read", "input": {"file_path": "a.py"}, "output": "x"},
                    {"tool": "Edit", "input": {"file_path": "a.py", "old_string": "x", "new_string": "y"}, "output": "ok"},
                ]}
            ]
        }
        traces = converter.convert(data)
        meta = {m["Property"]: m["Value"] for m in traces[0].metadata_table}
        assert meta["Model"] == "claude-opus"
        assert meta["input_tokens"] == "1000"
        assert meta["Files touched"] == "1"
        assert meta["Tool calls"] == "2"

    # --- to_dict ---

    def test_to_dict_includes_structured_turns(self, converter):
        data = {"structured_turns": [
            {"role": "assistant", "content": "x", "tool_calls": []}
        ]}
        traces = converter.convert(data)
        d = traces[0].to_dict()
        assert "structured_turns" in d

    # --- Edge cases ---

    def test_empty_data(self, converter):
        traces = converter.convert([])
        assert traces == []

    def test_non_dict_items_skipped(self, converter):
        traces = converter.convert(["not a dict", 42])
        assert traces == []

    def test_missing_fields(self, converter):
        data = {"id": "x"}
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].task_description == ""

    def test_list_input(self, converter):
        data = [
            {"id": "a", "structured_turns": [{"role": "assistant", "content": "x", "tool_calls": []}]},
            {"id": "b", "structured_turns": [{"role": "assistant", "content": "y", "tool_calls": []}]},
        ]
        traces = converter.convert(data)
        assert len(traces) == 2
        assert traces[0].id == "a"
        assert traces[1].id == "b"


class TestConverterRegistration:
    """Test that ClaudeCodeConverter is properly registered."""

    def test_registered_in_registry(self):
        from potato.trace_converter.registry import converter_registry
        assert converter_registry.is_registered("claude_code")

    def test_format_info(self):
        converter = ClaudeCodeConverter()
        info = converter.get_format_info()
        assert info["format_name"] == "claude_code"
        assert ".json" in info["file_extensions"]
