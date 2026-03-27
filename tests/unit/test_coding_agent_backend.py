"""
Unit tests for coding agent backend abstraction, tool execution,
and backend registry.
"""

import os
import pytest
import tempfile

from potato.coding_agent_backend import (
    BACKEND_REGISTRY,
    CodingAgentEvent,
    CodingAgentEventType,
    CODING_TOOLS,
    CODING_TOOLS_OLLAMA,
    create_backend,
    execute_tool,
    register_backend,
)


class TestToolExecution:
    """Tests for execute_tool()."""

    @pytest.fixture
    def workspace(self):
        with tempfile.TemporaryDirectory() as td:
            # Create some files
            with open(os.path.join(td, "main.py"), "w") as f:
                f.write("def hello():\n    return 42\n")
            with open(os.path.join(td, "README.md"), "w") as f:
                f.write("# Project\n")
            os.makedirs(os.path.join(td, "src"), exist_ok=True)
            with open(os.path.join(td, "src", "utils.py"), "w") as f:
                f.write("def add(a, b):\n    return a + b\n")
            yield td

    def test_read_file(self, workspace):
        result = execute_tool("Read", {"file_path": "main.py"}, workspace)
        assert "def hello():" in result
        assert "return 42" in result

    def test_read_missing_file(self, workspace):
        result = execute_tool("Read", {"file_path": "nonexistent.py"}, workspace)
        assert "Error" in result

    def test_edit_file(self, workspace):
        result = execute_tool("Edit", {
            "file_path": "main.py",
            "old_string": "return 42",
            "new_string": "return 99",
        }, workspace)
        assert "successfully" in result.lower() or "applied" in result.lower()

        # Verify the edit
        with open(os.path.join(workspace, "main.py")) as f:
            assert "return 99" in f.read()

    def test_edit_missing_string(self, workspace):
        result = execute_tool("Edit", {
            "file_path": "main.py",
            "old_string": "not_in_file",
            "new_string": "replacement",
        }, workspace)
        assert "not found" in result.lower() or "error" in result.lower()

    def test_write_file(self, workspace):
        result = execute_tool("Write", {
            "file_path": "new_file.py",
            "content": "print('hello')\n",
        }, workspace)
        assert "new_file.py" in result

        with open(os.path.join(workspace, "new_file.py")) as f:
            assert f.read() == "print('hello')\n"

    def test_write_creates_directories(self, workspace):
        result = execute_tool("Write", {
            "file_path": "deep/nested/file.py",
            "content": "x = 1",
        }, workspace)
        assert os.path.exists(os.path.join(workspace, "deep", "nested", "file.py"))

    def test_bash_command(self, workspace):
        result = execute_tool("Bash", {"command": "echo hello"}, workspace)
        assert "hello" in result

    def test_bash_exit_code(self, workspace):
        result = execute_tool("Bash", {"command": "exit 1"}, workspace)
        assert "exit code: 1" in result

    def test_bash_cwd(self, workspace):
        result = execute_tool("Bash", {"command": "pwd"}, workspace)
        assert workspace in result or os.path.basename(workspace) in result

    def test_grep(self, workspace):
        result = execute_tool("Grep", {"pattern": "def", "path": "."}, workspace)
        assert "main.py" in result
        assert "utils.py" in result

    def test_grep_no_matches(self, workspace):
        result = execute_tool("Grep", {"pattern": "zzzzz"}, workspace)
        assert "no matches" in result.lower()

    def test_glob(self, workspace):
        result = execute_tool("Glob", {"pattern": "**/*.py"}, workspace)
        assert "main.py" in result
        lines = result.strip().split("\n")
        assert len(lines) >= 2  # main.py and src/utils.py

    def test_unknown_tool(self, workspace):
        result = execute_tool("UnknownTool", {}, workspace)
        assert "Unknown tool" in result


class TestCodingAgentEvent:
    def test_to_dict(self):
        event = CodingAgentEvent(
            event_type=CodingAgentEventType.THINKING,
            timestamp=1234.5,
            data={"text": "hello"},
        )
        d = event.to_dict()
        assert d["event_type"] == "thinking"
        assert d["timestamp"] == 1234.5
        assert d["data"]["text"] == "hello"


class TestToolDefinitions:
    def test_coding_tools_have_required_fields(self):
        for tool in CODING_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_ollama_tools_format(self):
        for tool in CODING_TOOLS_OLLAMA:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

    def test_tool_names_match(self):
        names = {t["name"] for t in CODING_TOOLS}
        ollama_names = {t["function"]["name"] for t in CODING_TOOLS_OLLAMA}
        assert names == ollama_names


class TestBackendRegistry:
    def test_builtin_backends_registered(self):
        # At least anthropic and ollama should be registered
        assert "anthropic_tool_use" in BACKEND_REGISTRY or "ollama_tool_use" in BACKEND_REGISTRY

    def test_create_backend_invalid(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            create_backend("nonexistent_backend", {})

    def test_ollama_backend_registered(self):
        assert "ollama_tool_use" in BACKEND_REGISTRY

    def test_anthropic_backend_registered(self):
        assert "anthropic_tool_use" in BACKEND_REGISTRY

    def test_claude_sdk_backend_registered(self):
        assert "claude_sdk" in BACKEND_REGISTRY
