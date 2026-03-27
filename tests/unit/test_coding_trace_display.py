"""
Unit tests for CodingTraceDisplay.

Tests rendering of each tool type (Read, Edit, Bash, Grep, Glob, Write),
file tree generation, summary, and edge cases.
"""

import pytest
from potato.server_utils.displays.coding_trace_display import (
    CodingTraceDisplay,
    _classify_tool,
    _detect_language,
    _truncate_output,
)


class TestCodingTraceDisplay:
    """Tests for CodingTraceDisplay.render()."""

    @pytest.fixture
    def display(self):
        return CodingTraceDisplay()

    @pytest.fixture
    def field_config(self):
        return {"key": "structured_turns", "display_options": {}}

    def _make_turn(self, tool_calls, content="Reasoning text"):
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }

    def _make_user_turn(self, content="Fix the bug"):
        return {"role": "user", "content": content, "tool_calls": []}

    # --- Basic rendering ---

    def test_empty_data(self, display, field_config):
        html = display.render(field_config, None)
        assert "No trace data" in html

    def test_empty_list(self, display, field_config):
        html = display.render(field_config, [])
        assert "No trace" in html

    def test_user_message(self, display, field_config):
        data = [self._make_user_turn("Fix the authentication bug")]
        html = display.render(field_config, data)
        assert "ct-turn-user" in html
        assert "Fix the authentication bug" in html
        assert "User" in html

    def test_assistant_reasoning(self, display, field_config):
        data = [self._make_turn([], content="I will investigate the issue.")]
        html = display.render(field_config, data)
        assert "ct-reasoning" in html
        assert "I will investigate the issue." in html

    def test_step_numbers(self, display, field_config):
        data = [
            self._make_turn([], content="Step one"),
            self._make_turn([], content="Step two"),
        ]
        html = display.render(field_config, data)
        assert "Step 1" in html
        assert "Step 2" in html

    # --- Tool type rendering ---

    def test_read_tool(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Read",
            "input": {"file_path": "src/main.py"},
            "output": "def main():\n    pass",
            "output_type": "code",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-read" in html
        assert "Read" in html
        assert "src/main.py" in html
        assert "ct-code-block" in html
        assert "def main():" in html

    def test_edit_tool_diff(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Edit",
            "input": {
                "file_path": "src/main.py",
                "old_string": "    pass",
                "new_string": '    print("hello")',
            },
            "output": "Edit applied",
            "output_type": "diff",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-edit" in html
        assert "ct-diff" in html
        assert "ct-diff-removed" in html
        assert "ct-diff-added" in html
        assert "pass" in html
        assert "hello" in html
        assert "Edit applied" in html

    def test_bash_tool_terminal(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Bash",
            "input": {"command": "pytest tests/ -v"},
            "output": "PASSED test_main.py::test_hello\n3 passed",
            "output_type": "terminal",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-bash" in html
        assert "ct-terminal" in html
        assert "ct-terminal-cmd" in html
        assert "pytest tests/ -v" in html
        assert "PASSED" in html
        assert "ct-terminal-prompt" in html

    def test_grep_tool(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Grep",
            "input": {"pattern": "TODO", "path": "src/"},
            "output": "src/main.py:5: # TODO: fix this",
            "output_type": "code",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-search" in html
        assert "TODO" in html

    def test_write_tool(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Write",
            "input": {
                "file_path": "src/new_file.py",
                "content": "def new_func():\n    return 42",
            },
            "output": "File created",
            "output_type": "code",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-write" in html
        assert "ct-write-block" in html
        assert "New file" in html
        assert "new_func" in html

    def test_generic_tool(self, display, field_config):
        data = [self._make_turn([{
            "tool": "WebSearch",
            "input": {"query": "python async best practices"},
            "output": "Results found...",
        }])]
        html = display.render(field_config, data)
        assert "ct-tool-generic" in html
        assert "WebSearch" in html

    # --- File tree ---

    def test_file_tree(self, display, field_config):
        data = [self._make_turn([
            {"tool": "Read", "input": {"file_path": "src/main.py"}, "output": "code"},
            {"tool": "Edit", "input": {"file_path": "src/main.py", "old_string": "a", "new_string": "b"}, "output": "ok"},
            {"tool": "Read", "input": {"file_path": "src/utils.py"}, "output": "code"},
        ])]
        html = display.render(field_config, data)
        assert "ct-file-tree" in html
        assert "main.py" in html
        assert "utils.py" in html

    def test_no_file_tree_when_disabled(self, display):
        config = {"key": "test", "display_options": {"show_file_tree": False}}
        data = [self._make_turn([
            {"tool": "Read", "input": {"file_path": "x.py"}, "output": "code"},
        ])]
        html = display.render(config, data)
        assert "ct-file-tree" not in html

    # --- Summary ---

    def test_summary_counts(self, display, field_config):
        data = [
            self._make_turn([
                {"tool": "Read", "input": {}, "output": "x"},
                {"tool": "Bash", "input": {"command": "ls"}, "output": "files"},
            ]),
            self._make_turn([
                {"tool": "Edit", "input": {"old_string": "a", "new_string": "b"}, "output": "ok"},
            ]),
        ]
        html = display.render(field_config, data)
        assert "ct-summary" in html
        assert "3 tool calls" in html
        assert "2 turns" in html

    # --- Collapsible output ---

    def test_long_output_truncation(self, display):
        config = {"key": "test", "display_options": {
            "collapse_long_outputs": True,
            "max_output_lines": 5,
        }}
        long_output = "\n".join(f"line {i}" for i in range(20))
        data = [self._make_turn([{
            "tool": "Bash",
            "input": {"command": "cat big.txt"},
            "output": long_output,
            "output_type": "terminal",
        }])]
        html = display.render(config, data)
        assert "click to expand" in html

    # --- Multiple turns ---

    def test_multi_turn_trace(self, display, field_config):
        data = [
            self._make_user_turn("Fix the bug"),
            self._make_turn([
                {"tool": "Read", "input": {"file_path": "x.py"}, "output": "code"},
            ], content="Let me look at the code."),
            self._make_turn([
                {"tool": "Edit", "input": {"file_path": "x.py", "old_string": "a", "new_string": "b"}, "output": "ok"},
                {"tool": "Bash", "input": {"command": "pytest"}, "output": "passed"},
            ], content="Fixed and tested."),
        ]
        html = display.render(field_config, data)
        assert html.count("ct-turn-user") == 1
        assert html.count("ct-turn-assistant") == 2

    # --- Span target ---

    def test_span_target_support(self, display):
        config = {"key": "test", "span_target": True, "display_options": {}}
        data = [self._make_turn([], content="Reasoning text here")]
        html = display.render(config, data)
        assert "text-content" in html

    # --- Edge cases ---

    def test_empty_tool_output(self, display, field_config):
        data = [self._make_turn([{
            "tool": "Read",
            "input": {"file_path": "empty.py"},
            "output": "",
        }])]
        html = display.render(field_config, data)
        assert "No output" in html

    def test_string_data(self, display, field_config):
        """String data doesn't match structured turn format, so produces empty."""
        html = display.render(field_config, "just a string")
        assert "No trace" in html or "just a string" in html


class TestToolClassification:
    """Tests for tool classification helpers."""

    def test_read_tools(self):
        assert _classify_tool("Read") == "read"
        assert _classify_tool("Grep") == "search"
        assert _classify_tool("Glob") == "search"

    def test_edit_tools(self):
        assert _classify_tool("Edit") == "edit"

    def test_write_tools(self):
        assert _classify_tool("Write") == "write"

    def test_bash_tools(self):
        assert _classify_tool("Bash") == "bash"
        assert _classify_tool("Terminal") == "bash"

    def test_generic_tools(self):
        assert _classify_tool("WebSearch") == "generic"
        assert _classify_tool("Agent") == "generic"


class TestLanguageDetection:
    """Tests for language detection from file paths."""

    def test_python(self):
        assert _detect_language("src/main.py") == "python"

    def test_javascript(self):
        assert _detect_language("app/index.js") == "javascript"

    def test_typescript(self):
        assert _detect_language("src/App.tsx") == "tsx"

    def test_unknown(self):
        assert _detect_language("file.xyz") == ""

    def test_empty(self):
        assert _detect_language("") == ""


class TestTruncateOutput:
    """Tests for output truncation."""

    def test_no_truncation_needed(self):
        text, truncated = _truncate_output("line1\nline2\nline3", 5)
        assert text == "line1\nline2\nline3"
        assert truncated is False

    def test_truncation(self):
        text, truncated = _truncate_output("a\nb\nc\nd\ne", 3)
        assert text == "a\nb\nc"
        assert truncated is True

    def test_empty(self):
        text, truncated = _truncate_output("", 5)
        assert text == ""
        assert truncated is False
