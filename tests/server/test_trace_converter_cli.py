"""
End-to-end tests for the trace converter CLI.

Tests the full CLI pipeline: creating temp input files in various formats,
running `python -m potato.trace_converter`, and verifying the output JSONL.
"""

import json
import os
import tempfile
import pytest

from potato.trace_converter.cli import main as cli_main, load_input, parse_args
from potato.trace_converter.registry import converter_registry


# =========================================================================
# CLI argument parsing
# =========================================================================

class TestCLIArgParsing:
    """Test that CLI arguments parse correctly."""

    def test_parse_input_and_format(self):
        args = parse_args(["--input", "traces.json", "--input-format", "react"])
        assert args.input == "traces.json"
        assert args.input_format == "react"

    def test_parse_output(self):
        args = parse_args(["-i", "in.json", "-f", "react", "-o", "out.jsonl"])
        assert args.output == "out.jsonl"

    def test_parse_auto_detect(self):
        args = parse_args(["--input", "in.json", "--auto-detect"])
        assert args.auto_detect is True

    def test_parse_list_formats(self):
        args = parse_args(["--list-formats"])
        assert args.list_formats is True

    def test_parse_pretty(self):
        args = parse_args(["-i", "in.json", "-f", "react", "--pretty"])
        assert args.pretty is True

    def test_parse_verbose(self):
        args = parse_args(["-i", "in.json", "-f", "react", "-v"])
        assert args.verbose is True


# =========================================================================
# Input loading
# =========================================================================

class TestInputLoading:
    """Test load_input with JSON and JSONL files."""

    def test_load_json_array(self, tmp_path):
        data = [{"id": "1", "steps": []}, {"id": "2", "steps": []}]
        f = tmp_path / "input.json"
        f.write_text(json.dumps(data))
        result = load_input(str(f))
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_load_jsonl(self, tmp_path):
        lines = [
            json.dumps({"id": "1", "steps": []}),
            json.dumps({"id": "2", "steps": []}),
        ]
        f = tmp_path / "input.jsonl"
        f.write_text("\n".join(lines))
        result = load_input(str(f))
        assert isinstance(result, list)
        assert len(result) == 2

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_input("/nonexistent/path/traces.json")

    def test_load_empty_lines_skipped(self, tmp_path):
        content = json.dumps({"id": "1"}) + "\n\n" + json.dumps({"id": "2"}) + "\n"
        f = tmp_path / "input.jsonl"
        f.write_text(content)
        result = load_input(str(f))
        assert len(result) == 2

    def test_load_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all\nreally not")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_input(str(f))


# =========================================================================
# --list-formats
# =========================================================================

class TestListFormats:
    """Test the --list-formats flag."""

    def test_list_formats_returns_zero(self, capsys):
        ret = cli_main(["--list-formats"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "react" in captured.out.lower()
        assert "langchain" in captured.out.lower()

    def test_list_formats_includes_all_registered(self, capsys):
        cli_main(["--list-formats"])
        captured = capsys.readouterr()
        for fmt in converter_registry.get_supported_formats():
            assert fmt in captured.out.lower(), \
                f"--list-formats should list '{fmt}'"


# =========================================================================
# Error cases
# =========================================================================

class TestCLIErrors:
    """Test CLI error handling."""

    def test_missing_input_returns_error(self, capsys):
        ret = cli_main([])
        assert ret == 1
        captured = capsys.readouterr()
        assert "input" in captured.err.lower()

    def test_missing_format_returns_error(self, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"steps": []}]))
        ret = cli_main(["--input", str(f)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "format" in captured.err.lower()

    def test_nonexistent_input_file(self, capsys):
        ret = cli_main(["--input", "/no/such/file.json", "--input-format", "react"])
        assert ret == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "error" in captured.err.lower()

    def test_unknown_format(self, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"steps": []}]))
        ret = cli_main(["--input", str(f), "--input-format", "nonexistent_format"])
        assert ret == 1


# =========================================================================
# End-to-end conversion: ReAct format
# =========================================================================

class TestReActConversionE2E:
    """End-to-end test converting ReAct traces via CLI."""

    @pytest.fixture
    def react_input(self, tmp_path):
        traces = [
            {
                "id": "test_001",
                "task": "Find the capital of France",
                "steps": [
                    {"thought": "I need to search for this.",
                     "action": "search('capital of France')",
                     "observation": "Paris is the capital of France."},
                    {"thought": "Found it.",
                     "action": "finish('Paris')",
                     "observation": "Task complete."},
                ],
            },
            {
                "id": "test_002",
                "task": "What is 2+2?",
                "steps": [
                    {"thought": "Simple math.",
                     "action": "calculate(2+2)",
                     "observation": "4"},
                ],
            },
        ]
        f = tmp_path / "react_traces.json"
        f.write_text(json.dumps(traces))
        return str(f)

    def test_react_conversion_to_stdout(self, react_input, capsys):
        ret = cli_main(["--input", react_input, "--input-format", "react"])
        assert ret == 0
        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        assert len(lines) == 2, f"Should output 2 JSONL lines, got {len(lines)}"

        trace1 = json.loads(lines[0])
        assert "conversation" in trace1
        assert isinstance(trace1["conversation"], list)
        assert len(trace1["conversation"]) > 0

    def test_react_conversion_to_file(self, react_input, tmp_path):
        output_path = str(tmp_path / "output.jsonl")
        ret = cli_main([
            "--input", react_input,
            "--input-format", "react",
            "--output", output_path,
        ])
        assert ret == 0
        assert os.path.exists(output_path)

        with open(output_path) as f:
            lines = [l for l in f.readlines() if l.strip()]
        assert len(lines) == 2

        trace = json.loads(lines[0])
        assert "id" in trace
        assert "conversation" in trace

    def test_react_conversion_pretty(self, react_input, capsys):
        ret = cli_main([
            "--input", react_input,
            "--input-format", "react",
            "--pretty",
        ])
        assert ret == 0
        captured = capsys.readouterr()
        # Pretty output has indentation
        assert "  " in captured.out

    def test_react_conversation_structure(self, react_input, capsys):
        """Converted traces should have proper speaker/text conversation format."""
        cli_main(["--input", react_input, "--input-format", "react"])
        captured = capsys.readouterr()
        trace = json.loads(captured.out.strip().split("\n")[0])

        conversation = trace["conversation"]
        speakers = [turn["speaker"] for turn in conversation]
        # ReAct traces produce Thought/Action/Observation turns
        assert any("Thought" in s for s in speakers), \
            "Should have Thought speaker"
        assert any("Action" in s for s in speakers), \
            "Should have Action speaker"


# =========================================================================
# Auto-detection
# =========================================================================

class TestAutoDetection:
    """Test --auto-detect flag."""

    def test_auto_detect_react(self, tmp_path, capsys):
        traces = [{
            "id": "ad_001",
            "task": "Test task",
            "steps": [
                {"thought": "thinking", "action": "act()", "observation": "result"}
            ],
        }]
        f = tmp_path / "traces.json"
        f.write_text(json.dumps(traces))

        ret = cli_main(["--input", str(f), "--auto-detect"])
        assert ret == 0
        captured = capsys.readouterr()
        # Should mention detected format on stderr
        assert "auto-detected" in captured.err.lower() or \
               "react" in captured.err.lower()

    def test_auto_detect_failure(self, tmp_path, capsys):
        """Unrecognizable format should fail auto-detection."""
        data = [{"random_key": "random_value", "no_steps": True}]
        f = tmp_path / "unknown.json"
        f.write_text(json.dumps(data))

        ret = cli_main(["--input", str(f), "--auto-detect"])
        assert ret == 1
        captured = capsys.readouterr()
        assert "could not auto-detect" in captured.err.lower() or \
               "error" in captured.err.lower()


# =========================================================================
# LangChain format E2E
# =========================================================================

class TestLangChainConversionE2E:
    """End-to-end test for LangChain format conversion."""

    def test_langchain_conversion(self, tmp_path, capsys):
        traces = [{
            "id": "lc_001",
            "runs": [
                {
                    "run_type": "llm",
                    "inputs": {"prompt": "What is AI?"},
                    "outputs": {"text": "AI is artificial intelligence."},
                },
                {
                    "run_type": "tool",
                    "inputs": {"tool": "search", "query": "AI definition"},
                    "outputs": {"result": "AI stands for..."},
                },
            ],
        }]
        f = tmp_path / "langchain.json"
        f.write_text(json.dumps(traces))

        ret = cli_main(["--input", str(f), "--input-format", "langchain"])
        assert ret == 0
        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l.strip()]
        assert len(lines) >= 1
        trace = json.loads(lines[0])
        assert "conversation" in trace


# =========================================================================
# Registry integration
# =========================================================================

class TestRegistryIntegration:
    """Test that the registry has all expected converters."""

    def test_all_five_formats_registered(self):
        formats = converter_registry.get_supported_formats()
        for expected in ["react", "langchain", "langfuse", "atif", "webarena"]:
            assert expected in formats, f"'{expected}' should be registered"

    def test_converter_info_has_description(self):
        for info in converter_registry.list_converters():
            assert "description" in info
            assert len(info["description"]) > 0
