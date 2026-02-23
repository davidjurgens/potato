"""
Tests for Batch 4 testing gaps (items 19-30).

Covers under-tested areas: trace converter CLI, dynamic multirate,
converter edge cases, exporter aggregation, and gallery display.
"""

import json
import os
import tempfile

import pytest

from potato.trace_converter.cli import parse_args, load_input, main
from potato.trace_converter.base import CanonicalTrace
from potato.trace_converter.converters.react_converter import ReActConverter
from potato.trace_converter.converters.langchain_converter import LangChainConverter
from potato.trace_converter.converters.langfuse_converter import LangfuseConverter
from potato.trace_converter.converters.atif_converter import ATIFConverter
from potato.trace_converter.converters.webarena_converter import WebArenaConverter
from potato.server_utils.schemas.multirate import (
    generate_multirate_layout,
    populate_dynamic_multirate,
)
from potato.export.agent_eval_exporter import AgentEvalExporter
from potato.export.base import ExportContext
from potato.server_utils.displays.gallery_display import GalleryDisplay
from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay


# ============================================================================
# CLI Tests
# ============================================================================


class TestTraceConverterCLI:
    """Tests for the trace converter CLI (cli.py)."""

    def test_parse_args_defaults(self):
        args = parse_args([])
        assert args.input is None
        assert args.input_format is None
        assert args.output is None
        assert args.auto_detect is False
        assert args.list_formats is False
        assert args.pretty is False
        assert args.verbose is False

    def test_parse_args_full(self):
        args = parse_args([
            "--input", "traces.json",
            "--input-format", "react",
            "--output", "output.jsonl",
            "--pretty", "--verbose"
        ])
        assert args.input == "traces.json"
        assert args.input_format == "react"
        assert args.output == "output.jsonl"
        assert args.pretty is True
        assert args.verbose is True

    def test_parse_args_short_flags(self):
        args = parse_args(["-i", "input.json", "-f", "langchain", "-o", "out.jsonl", "-v"])
        assert args.input == "input.json"
        assert args.input_format == "langchain"
        assert args.output == "out.jsonl"
        assert args.verbose is True

    def test_load_input_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"id": "1", "data": "test"}], f)
            f.flush()
            data = load_input(f.name)
        os.unlink(f.name)
        assert isinstance(data, list)
        assert data[0]["id"] == "1"

    def test_load_input_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"id": "1"}) + "\n")
            f.write(json.dumps({"id": "2"}) + "\n")
            f.flush()
            data = load_input(f.name)
        os.unlink(f.name)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_load_input_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_input("/nonexistent/path.json")

    def test_load_input_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("not json\nalso not json\n")
            f.flush()
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_input(f.name)
        os.unlink(f.name)

    def test_main_list_formats(self, capsys):
        exit_code = main(["--list-formats"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "react" in captured.out
        assert "langchain" in captured.out

    def test_main_no_input(self, capsys):
        exit_code = main([])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "input" in captured.err.lower()

    def test_main_no_format(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"steps": []}], f)
            f.flush()
        exit_code = main(["--input", f.name])
        os.unlink(f.name)
        assert exit_code == 1

    def test_main_convert_react(self, capsys):
        data = [{"id": "t1", "task": "test", "steps": [
            {"thought": "think", "action": "do()", "observation": "done"}
        ]}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

        exit_code = main(["--input", f.name, "--input-format", "react"])
        os.unlink(f.name)
        assert exit_code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["id"] == "t1"

    def test_main_convert_to_file(self):
        data = [{"id": "t1", "task": "test", "steps": [
            {"thought": "think", "action": "act", "observation": "obs"}
        ]}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as infile:
            json.dump(data, infile)
            infile.flush()

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = os.path.join(tmpdir, "output.jsonl")
            exit_code = main([
                "--input", infile.name,
                "--input-format", "react",
                "--output", outfile
            ])
            os.unlink(infile.name)
            assert exit_code == 0
            assert os.path.exists(outfile)
            with open(outfile) as f:
                output = json.loads(f.readline())
            assert output["id"] == "t1"

    def test_main_auto_detect(self, capsys):
        data = [{"id": "t1", "run_type": "chain", "child_runs": [],
                 "inputs": {"input": "test"}, "outputs": {"output": "done"}}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

        exit_code = main(["--input", f.name, "--auto-detect"])
        os.unlink(f.name)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "langchain" in captured.err.lower()

    def test_main_auto_detect_failure(self, capsys):
        data = [{"random": "data"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

        exit_code = main(["--input", f.name, "--auto-detect"])
        os.unlink(f.name)
        assert exit_code == 1


# ============================================================================
# Converter Edge Case Tests
# ============================================================================


class TestConverterEdgeCases:
    """Tests for edge cases in all trace converters."""

    def test_react_empty_steps(self):
        """ReAct converter should handle traces with empty steps."""
        converter = ReActConverter()
        data = [{"id": "t1", "task": "test", "steps": []}]
        traces = converter.convert(data)
        assert len(traces) == 1
        assert traces[0].conversation == []

    def test_react_partial_steps(self):
        """ReAct converter should handle steps with missing fields."""
        converter = ReActConverter()
        data = [{"id": "t1", "task": "test", "steps": [
            {"thought": "thinking"},  # No action or observation
            {"action": "doing"},  # No thought or observation
            {"observation": "result"},  # No thought or action
        ]}]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert len(conv) == 3

    def test_langchain_no_child_runs(self):
        """LangChain converter should handle traces without child runs."""
        converter = LangChainConverter()
        data = [{"id": "r1", "run_type": "chain", "name": "test",
                 "inputs": {"input": "hello"}, "outputs": {"output": "world"},
                 "child_runs": []}]
        traces = converter.convert(data)
        assert len(traces) == 1
        # Falls back to simple input/output trace
        conv = traces[0].conversation
        assert len(conv) >= 1

    def test_langchain_nested_chains(self):
        """LangChain converter should handle deeply nested chains."""
        converter = LangChainConverter()
        data = [{
            "id": "r1", "run_type": "chain", "name": "outer",
            "inputs": {"input": "test"}, "outputs": {"output": "done"},
            "child_runs": [{
                "name": "inner_chain", "run_type": "chain",
                "inputs": {}, "outputs": {},
                "child_runs": [{
                    "name": "deep_llm", "run_type": "llm",
                    "inputs": {},
                    "outputs": {"generations": [[{"text": "deep thought"}]]}
                }]
            }]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert any("deep thought" in t["text"] for t in conv)

    def test_langfuse_event_observations(self):
        """Langfuse converter should handle EVENT type observations."""
        converter = LangfuseConverter()
        data = [{
            "id": "t1", "name": "test",
            "input": {"query": "test"},
            "observations": [
                {"type": "EVENT", "name": "system_log",
                 "input": "Log entry", "output": "Event result"}
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        assert any("System" in t["speaker"] for t in conv)

    def test_langfuse_string_input(self):
        """Langfuse should handle string input (not dict)."""
        converter = LangfuseConverter()
        data = [{
            "id": "t1", "name": "test",
            "input": "raw string query",
            "observations": []
        }]
        traces = converter.convert(data)
        assert traces[0].task_description == "raw string query"

    def test_webarena_all_action_types(self):
        """WebArena converter should handle all action types."""
        converter = WebArenaConverter()
        data = [{
            "task_id": "w1", "intent": "test",
            "actions": [
                {"action_type": "click", "element": {"text": "btn"}},
                {"action_type": "type", "element": {"text": "input"}, "value": "hello"},
                {"action_type": "scroll", "direction": "up"},
                {"action_type": "navigate", "url": "https://example.com"},
                {"action_type": "select", "element": {"text": "dropdown"}, "value": "opt1"},
                {"action_type": "hover", "element": {"text": "menu"}},
                {"action_type": "stop", "value": "done"},
            ]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert len(action_turns) == 7
        assert "click" in action_turns[0]["text"]
        assert "type_text" in action_turns[1]["text"]
        assert "scroll" in action_turns[2]["text"]
        assert "navigate" in action_turns[3]["text"]
        assert "select_option" in action_turns[4]["text"]
        assert "hover" in action_turns[5]["text"]
        assert "stop" in action_turns[6]["text"]

    def test_atif_structured_action(self):
        """ATIF converter should handle action as dict with tool/params."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": {"name": "A"},
            "steps": [{
                "thought": "think",
                "action": {"tool": "calculator", "params": {"expr": "2+2"}},
                "observation": "4"
            }]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert "calculator" in action_turns[0]["text"]
        assert "expr" in action_turns[0]["text"]

    def test_atif_string_action(self):
        """ATIF converter should handle action as plain string."""
        converter = ATIFConverter()
        data = [{
            "trace_id": "t1",
            "task": {"description": "test"},
            "agent": {"name": "A"},
            "steps": [{"thought": "think", "action": "do_something()", "observation": "ok"}]
        }]
        traces = converter.convert(data)
        conv = traces[0].conversation
        action_turns = [t for t in conv if t["speaker"] == "Agent (Action)"]
        assert action_turns[0]["text"] == "do_something()"

    def test_multiple_traces_in_batch(self):
        """All converters should handle multiple traces in a batch."""
        converter = ReActConverter()
        data = [
            {"id": f"t{i}", "task": f"task {i}", "steps": [
                {"thought": "t", "action": "a", "observation": "o"}
            ]}
            for i in range(5)
        ]
        traces = converter.convert(data)
        assert len(traces) == 5
        assert traces[4].id == "t4"


# ============================================================================
# Dynamic Multirate Tests
# ============================================================================


class TestDynamicMultirate:
    """Tests for dynamic multirate schema and populate_dynamic_multirate."""

    def test_populate_replaces_placeholder(self):
        """populate_dynamic_multirate should inject options into HTML."""
        html = '''<div data-options-from-data="items" data-options-values='[]'>body</div>'''
        instance_data = {"items": ["item_a", "item_b", "item_c"]}
        result = populate_dynamic_multirate(html, instance_data)
        assert "item_a" in result
        assert "item_b" in result
        assert "item_c" in result
        # Placeholder should be gone
        assert "data-options-values='[]'" not in result

    def test_populate_no_matching_key(self):
        """Should leave HTML unchanged if data key not found."""
        html = '''<div data-options-from-data="missing_key" data-options-values='[]'>body</div>'''
        instance_data = {"other_key": ["a", "b"]}
        result = populate_dynamic_multirate(html, instance_data)
        assert "data-options-values='[]'" in result

    def test_populate_empty_options(self):
        """Should leave placeholder if options list is empty."""
        html = '''<div data-options-from-data="items" data-options-values='[]'>body</div>'''
        instance_data = {"items": []}
        result = populate_dynamic_multirate(html, instance_data)
        assert "data-options-values='[]'" in result

    def test_populate_html_escapes_options(self):
        """Options with special chars should be HTML-escaped in attribute."""
        html = '''<div data-options-from-data="items" data-options-values='[]'>body</div>'''
        instance_data = {"items": ['item with "quotes"', "item with <html>"]}
        result = populate_dynamic_multirate(html, instance_data)
        # Should not have raw quotes or HTML tags
        assert 'item with "quotes"' not in result  # Should be escaped
        assert "<html>" not in result  # Should be escaped

    def test_populate_multiple_containers(self):
        """Should handle multiple dynamic multirate containers in one page."""
        html = (
            '''<div data-options-from-data="items_a" data-options-values='[]'>a</div>'''
            '''<div data-options-from-data="items_b" data-options-values='[]'>b</div>'''
        )
        instance_data = {"items_a": ["x", "y"], "items_b": ["p", "q"]}
        result = populate_dynamic_multirate(html, instance_data)
        # Both should be populated
        assert "data-options-values='[]'" not in result

    def test_generate_static_multirate_layout(self):
        """Static multirate with options should generate valid HTML."""
        scheme = {
            "annotation_type": "multirate",
            "name": "test_rate",
            "description": "Test rating",
            "options": ["opt1", "opt2"],
            "labels": ["Bad", "Good"],
        }
        html, keybindings = generate_multirate_layout(scheme)
        assert "test_rate" in html
        assert "opt1" in html
        assert "opt2" in html
        assert "Bad" in html
        assert "Good" in html

    def test_generate_dynamic_multirate_layout(self):
        """Dynamic multirate with options_from_data should generate JS-powered HTML."""
        scheme = {
            "annotation_type": "multirate",
            "name": "dynamic_rate",
            "description": "Dynamic rating",
            "options_from_data": "step_labels",
            "labels": ["Wrong", "Right"],
        }
        html, keybindings = generate_multirate_layout(scheme)
        assert "dynamic-multirate-dynamic_rate" in html
        assert "step_labels" in html
        assert "Wrong" in html
        assert "Right" in html
        assert "<script>" in html


# ============================================================================
# Exporter Aggregation Tests
# ============================================================================


class TestExporterAggregation:
    """Tests for AgentEvalExporter aggregation methods."""

    def setup_method(self):
        self.exporter = AgentEvalExporter()

    def test_aggregate_categorical_simple_strings(self):
        """Categorical aggregation with simple string values."""
        result = self.exporter._aggregate_categorical(["success", "success", "failure"])
        assert result["distribution"]["success"] == 2
        assert result["distribution"]["failure"] == 1
        assert result["majority"] == "success"
        assert result["agreement"] == pytest.approx(2/3, abs=0.01)

    def test_aggregate_categorical_all_same(self):
        """Perfect agreement should give agreement=1.0."""
        result = self.exporter._aggregate_categorical(["yes", "yes", "yes"])
        assert result["agreement"] == 1.0

    def test_aggregate_categorical_empty(self):
        """Empty values should not crash."""
        result = self.exporter._aggregate_categorical([])
        assert result["distribution"] == {}
        assert result["majority"] == ""
        assert result["agreement"] == 0

    def test_aggregate_numeric_single_value(self):
        result = self.exporter._aggregate_numeric([5])
        assert result["mean"] == 5.0
        assert result["std"] == 0.0

    def test_aggregate_numeric_string_values(self):
        """Should handle numeric strings."""
        result = self.exporter._aggregate_numeric(["3", "4", "5"])
        assert result["mean"] == 4.0

    def test_aggregate_numeric_mixed_invalid(self):
        """Should skip non-numeric values."""
        result = self.exporter._aggregate_numeric(["3", "bad", "5"])
        assert result["mean"] == 4.0
        assert len(result["values"]) == 2

    def test_aggregate_numeric_all_invalid(self):
        """All non-numeric should return None mean."""
        result = self.exporter._aggregate_numeric(["bad", "worse"])
        assert result["mean"] is None

    def test_aggregate_multiselect_dict_format(self):
        """Multiselect with dict format {label: bool}."""
        values = [
            {"err_a": True, "err_b": False, "no_errors": True},
            {"err_a": True, "err_b": True},
        ]
        result = self.exporter._aggregate_multiselect(values)
        assert result["counts"]["err_a"] == 2
        assert result["counts"]["err_b"] == 1
        assert result["counts"]["no_errors"] == 1

    def test_aggregate_multiselect_list_format(self):
        """Multiselect with list format [label1, label2]."""
        values = [
            ["err_a", "err_b"],
            ["err_a"],
        ]
        result = self.exporter._aggregate_multiselect(values)
        assert result["counts"]["err_a"] == 2
        assert result["counts"]["err_b"] == 1

    def test_aggregate_multirate(self):
        """Multirate aggregation across annotators."""
        values = [
            {"step_1": "3", "step_2": "5"},
            {"step_1": "4", "step_2": "4"},
        ]
        result = self.exporter._aggregate_multirate(values)
        assert "per_item" in result
        assert result["per_item"]["step_1"]["mean"] == 3.5
        assert result["per_item"]["step_2"]["mean"] == 4.5

    def test_full_export_with_multiple_schema_types(self):
        """Full export with radio, likert, and multiselect schemas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"success": "yes", "quality": 4,
                                "errors": {"loop": True}}},
                    {"instance_id": "t1", "user_id": "u2",
                     "labels": {"success": "yes", "quality": 5,
                                "errors": {"loop": True, "hallucination": True}}},
                    {"instance_id": "t2", "user_id": "u1",
                     "labels": {"success": "no", "quality": 2,
                                "errors": {"premature_stop": True}}},
                ],
                items={"t1": {}, "t2": {}},
                schemas=[
                    {"name": "success", "annotation_type": "radio"},
                    {"name": "quality", "annotation_type": "likert"},
                    {"name": "errors", "annotation_type": "multiselect"},
                ],
                output_dir=tmpdir
            )
            result = self.exporter.export(context, tmpdir)
            assert result.success

            with open(os.path.join(tmpdir, "agent_evaluation.json")) as f:
                output = json.load(f)

            assert output["summary"]["total_traces"] == 2
            assert output["summary"]["total_annotators"] == 2
            assert "success" in output["aggregate"]
            assert "quality" in output["aggregate"]
            assert "errors" in output["aggregate"]


# ============================================================================
# Display Edge Case Tests
# ============================================================================


class TestAgentTraceDisplayEdgeCases:
    """Edge case tests for AgentTraceDisplay."""

    def setup_method(self):
        self.display = AgentTraceDisplay()

    def test_mixed_format_data(self):
        """Should handle mixed Format 1 and Format 2 data."""
        data = [
            {"speaker": "Agent (Thought)", "text": "format 1"},
            {"thought": "format 2", "action": "act", "observation": "obs"},
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "format 1" in html
        assert "format 2" in html

    def test_format3_step_type_content(self):
        """Should handle Format 3 (step_type/content) data."""
        data = [
            {"step_type": "thought", "content": "thinking..."},
            {"step_type": "action", "content": "search('query')"},
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "thinking..." in html
        assert "search(&#x27;query&#x27;)" in html or "search(" in html

    def test_empty_step_text(self):
        """Should handle steps with empty text."""
        data = [{"speaker": "Agent", "text": ""}]
        html = self.display.render({"key": "trace"}, data)
        assert "agent-trace-step" in html

    def test_screenshot_rendering(self):
        """Should render screenshot thumbnails when present."""
        data = [
            {"speaker": "Agent (Action)", "text": "click(btn)",
             "screenshot": "screenshots/step_0.png"}
        ]
        html = self.display.render({"key": "trace"}, data)
        assert "step_0.png" in html
        assert "step-screenshot-img" in html


class TestGalleryDisplayEdgeCases:
    """Edge case tests for GalleryDisplay."""

    def setup_method(self):
        self.display = GalleryDisplay()

    def test_xss_in_url(self):
        """Image URLs with special chars should be escaped."""
        data = ['"><script>alert(1)</script>']
        html = self.display.render({"key": "test"}, data)
        assert "<script>" not in html

    def test_xss_in_caption(self):
        """Captions with special chars should be escaped."""
        data = [{"url": "img.png", "caption": '<script>alert(1)</script>'}]
        html = self.display.render({"key": "test"}, data)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_dict_items_skipped(self):
        """Dict items without a url should be skipped."""
        data = [{"caption": "no url"}, {"url": "valid.png"}]
        html = self.display.render({"key": "test"}, data)
        assert html.count('class="gallery-item"') == 1

    def test_alternate_url_keys(self):
        """Should fall back to 'src' and 'path' keys."""
        data = [{"src": "img_src.png"}, {"path": "img_path.png"}]
        html = self.display.render({"key": "test"}, data)
        assert "img_src.png" in html
        assert "img_path.png" in html
