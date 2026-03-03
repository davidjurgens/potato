"""
Regression tests for Batch 2 bug fixes (items 8-14).

Each test class targets a specific bug that was identified during code review.
Tests are written to demonstrate the bug (would fail before the fix) and
verify the fix prevents regression.
"""

import csv
import io
import json
import os
import tempfile

import pytest

from potato.trace_converter.base import CanonicalTrace
from potato.trace_converter.converters.langfuse_converter import LangfuseConverter
from potato.server_utils.displays.gallery_display import GalleryDisplay
from potato.server_utils.displays.agent_trace_display import AgentTraceDisplay
from potato.export.agent_eval_exporter import AgentEvalExporter
from potato.export.base import ExportContext


class TestItem8ExtraFieldsOverwriteCoreFields:
    """
    Bug: CanonicalTrace.to_dict() uses result.update(self.extra_fields), which
    allows extra_fields to silently overwrite core fields like 'id', 'conversation',
    'task_description', etc.

    Fix: Filter out core field keys from extra_fields before merging.
    """

    def test_extra_fields_cannot_overwrite_id(self):
        trace = CanonicalTrace(
            id="real_id",
            task_description="Real task",
            conversation=[{"speaker": "A", "text": "hello"}],
            extra_fields={"id": "OVERWRITTEN"}
        )
        d = trace.to_dict()
        assert d["id"] == "real_id", "extra_fields must not overwrite 'id'"

    def test_extra_fields_cannot_overwrite_conversation(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[{"speaker": "A", "text": "hello"}],
            extra_fields={"conversation": "OVERWRITTEN"}
        )
        d = trace.to_dict()
        assert isinstance(d["conversation"], list), "extra_fields must not overwrite 'conversation'"
        assert d["conversation"][0]["text"] == "hello"

    def test_extra_fields_cannot_overwrite_task_description(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Real task",
            conversation=[],
            extra_fields={"task_description": "FAKE"}
        )
        d = trace.to_dict()
        assert d["task_description"] == "Real task"

    def test_extra_fields_cannot_overwrite_agent_name(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[],
            agent_name="RealAgent",
            extra_fields={"agent_name": "FakeAgent"}
        )
        d = trace.to_dict()
        assert d["agent_name"] == "RealAgent"

    def test_extra_fields_cannot_overwrite_metadata_table(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[],
            metadata_table=[{"Property": "Steps", "Value": "3"}],
            extra_fields={"metadata_table": "OVERWRITTEN"}
        )
        d = trace.to_dict()
        assert isinstance(d["metadata_table"], list)

    def test_extra_fields_cannot_overwrite_screenshots(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[],
            screenshots=["real.png"],
            extra_fields={"screenshots": "OVERWRITTEN"}
        )
        d = trace.to_dict()
        assert d["screenshots"] == ["real.png"]

    def test_non_core_extra_fields_still_work(self):
        trace = CanonicalTrace(
            id="test",
            task_description="Test",
            conversation=[],
            extra_fields={"custom_field": "value", "another": 42}
        )
        d = trace.to_dict()
        assert d["custom_field"] == "value"
        assert d["another"] == 42


class TestItem9LangfuseNoneTokens:
    """
    Bug: Langfuse converter crashes with TypeError when usage dict has
    None values for token counts (e.g., {"totalTokens": None}).

    Fix: Use `or 0` to convert None to 0 before addition.
    """

    def test_none_total_tokens(self):
        """usage.totalTokens = None should not crash."""
        converter = LangfuseConverter()
        data = [{
            "id": "trace-1",
            "name": "test",
            "input": {"query": "test"},
            "observations": [
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "hello"},
                    "model": "gpt-4",
                    "usage": {"totalTokens": None}
                }
            ]
        }]
        traces = converter.convert(data)
        assert len(traces) == 1
        # Should not have a Tokens entry since total is 0
        meta = traces[0].metadata_table
        token_entries = [m for m in meta if m["Property"] == "Tokens"]
        assert len(token_entries) == 0  # 0 tokens means no entry

    def test_none_total_tokens_key(self):
        """usage.total_tokens = None (underscore variant) should not crash."""
        converter = LangfuseConverter()
        data = [{
            "id": "trace-1",
            "name": "test",
            "input": {"query": "test"},
            "observations": [
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "hello"},
                    "model": "gpt-4",
                    "usage": {"total_tokens": None}
                }
            ]
        }]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_null_usage_dict(self):
        """usage = None should not crash."""
        converter = LangfuseConverter()
        data = [{
            "id": "trace-1",
            "name": "test",
            "input": {"query": "test"},
            "observations": [
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "hello"},
                    "model": "gpt-4",
                    "usage": None
                }
            ]
        }]
        traces = converter.convert(data)
        assert len(traces) == 1

    def test_mixed_none_and_valid_tokens(self):
        """Mix of None and valid tokens should sum correctly."""
        converter = LangfuseConverter()
        data = [{
            "id": "trace-1",
            "name": "test",
            "input": {"query": "test"},
            "observations": [
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "hello"},
                    "usage": {"totalTokens": None}
                },
                {
                    "type": "GENERATION",
                    "name": "gpt-4",
                    "input": {},
                    "output": {"content": "world"},
                    "usage": {"totalTokens": 100}
                }
            ]
        }]
        traces = converter.convert(data)
        meta = traces[0].metadata_table
        token_entries = [m for m in meta if m["Property"] == "Tokens"]
        assert len(token_entries) == 1
        assert token_entries[0]["Value"] == "100"


class TestItem10GalleryCSSStringTypes:
    """
    Bug: GalleryDisplay._build_css() does arithmetic on max_height, thumbnail_size,
    and columns (e.g., `max_height - 40`), but these values come from config and
    may be strings (e.g., "400"), causing TypeError.

    Fix: Cast to int with fallback defaults at the top of _build_css.
    """

    def test_string_max_height(self):
        """String max_height should not crash CSS generation."""
        display = GalleryDisplay()
        data = ["img1.png"]
        field_config = {
            "key": "test",
            "display_options": {"max_height": "500", "layout": "horizontal"}
        }
        html = display.render(field_config, data)
        assert "gallery-horizontal" in html
        # Should contain the numeric value in CSS
        assert "500px" in html or "460px" in html  # max_height or max_height - 40

    def test_string_thumbnail_size(self):
        """String thumbnail_size should not crash CSS generation."""
        display = GalleryDisplay()
        data = ["img1.png"]
        field_config = {
            "key": "test",
            "display_options": {"thumbnail_size": "250", "layout": "horizontal"}
        }
        html = display.render(field_config, data)
        assert "250px" in html

    def test_string_columns(self):
        """String columns should not crash CSS generation."""
        display = GalleryDisplay()
        data = ["img1.png"]
        field_config = {
            "key": "test",
            "display_options": {"columns": "4", "layout": "grid"}
        }
        html = display.render(field_config, data)
        assert "repeat(4," in html

    def test_invalid_string_falls_back(self):
        """Invalid string values should fall back to defaults."""
        display = GalleryDisplay()
        data = ["img1.png"]
        field_config = {
            "key": "test",
            "display_options": {
                "max_height": "not_a_number",
                "thumbnail_size": "also_bad",
                "columns": "nope",
                "layout": "grid"
            }
        }
        html = display.render(field_config, data)
        # Should not crash and should use defaults (400, 300, 3)
        assert "400px" in html
        assert "300px" in html
        assert "repeat(3," in html


class TestItem11CSVEscaping:
    """
    Bug: _write_summary_csv() uses raw ",".join(row) instead of the csv module,
    so values containing commas, quotes, or newlines corrupt the CSV output.

    Fix: Use csv.writer for proper RFC 4180 escaping.
    """

    def test_csv_with_commas_in_values(self):
        """Values containing commas should be properly escaped in CSV."""
        exporter = AgentEvalExporter()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "trace,with,commas", "user_id": "u1",
                     "labels": {"success": {"yes, definitely": "1"}}},
                ],
                items={"trace,with,commas": {}},
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )
            result = exporter.export(context, tmpdir)
            assert result.success

            csv_file = os.path.join(tmpdir, "agent_evaluation_summary.csv")
            # Parse with csv.reader to verify it's valid CSV
            with open(csv_file, newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert len(rows) == 2  # header + 1 data row
            # The trace_id with commas should be in one field, not split
            assert rows[1][0] == "trace,with,commas"

    def test_csv_with_quotes_in_values(self):
        """Values containing quotes should be properly escaped in CSV."""
        exporter = AgentEvalExporter()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": 'trace_"quoted"', "user_id": "u1",
                     "labels": {"success": {"yes": "1"}}},
                ],
                items={'trace_"quoted"': {}},
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )
            result = exporter.export(context, tmpdir)
            assert result.success

            csv_file = os.path.join(tmpdir, "agent_evaluation_summary.csv")
            with open(csv_file, newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert rows[1][0] == 'trace_"quoted"'


class TestItem12CategoricalMaxStringComparison:
    """
    Bug: _aggregate_categorical() uses max(v.keys(), key=lambda k: v[k]) where
    v[k] might be a string like "1". Python's max() on strings does lexicographic
    comparison, so "9" > "10" (incorrect for label counts).

    Fix: Convert to float in the comparison key function.
    """

    def test_string_values_in_dict(self):
        """Radio annotations with string values should be compared numerically."""
        exporter = AgentEvalExporter()
        # Simulate annotation values as dicts with string counts
        values = [
            {"option_a": "10", "option_b": "9"},  # option_a has higher count
        ]
        result = exporter._aggregate_categorical(values)
        # With string comparison, "9" > "10" would pick option_b incorrectly
        assert result["majority"] == "option_a", \
            "Should pick option_a (10 > 9, not lexicographic '9' > '10')"

    def test_numeric_values_in_dict(self):
        """Radio annotations with numeric values should work correctly."""
        exporter = AgentEvalExporter()
        values = [
            {"option_a": 2, "option_b": 1},
        ]
        result = exporter._aggregate_categorical(values)
        assert result["majority"] == "option_a"

    def test_mixed_string_numeric_values(self):
        """Should handle a mix of string and numeric values."""
        exporter = AgentEvalExporter()
        values = [
            {"opt_x": "5"},
            {"opt_y": "3"},
        ]
        result = exporter._aggregate_categorical(values)
        assert result["distribution"]["opt_x"] == 1
        assert result["distribution"]["opt_y"] == 1

    def test_non_numeric_string_values(self):
        """Non-numeric string values should not crash (fallback to 0)."""
        exporter = AgentEvalExporter()
        values = [
            {"checked": "true", "unchecked": "false"},
        ]
        # Should not raise - falls back to 0 for comparison
        result = exporter._aggregate_categorical(values)
        assert "majority" in result


class TestItem13SampleStdDev:
    """
    Bug: _aggregate_numeric() computes population standard deviation (divides by N)
    instead of sample standard deviation (divides by N-1). For annotation
    data (samples from annotators), Bessel's correction is appropriate.

    Fix: Divide by max(N-1, 1) instead of N.
    """

    def test_two_value_sample_std(self):
        """Sample std of [4, 6] should use N-1 denominator."""
        exporter = AgentEvalExporter()
        values = [4, 6]
        result = exporter._aggregate_numeric(values)

        # mean = 5.0
        # population variance = ((4-5)^2 + (6-5)^2) / 2 = 1.0 -> std = 1.0
        # sample variance = ((4-5)^2 + (6-5)^2) / 1 = 2.0 -> std = 1.414
        expected_sample_std = (2.0) ** 0.5  # ~1.414
        assert abs(result["std"] - round(expected_sample_std, 3)) < 0.001, \
            f"Expected sample std ~{expected_sample_std:.3f}, got {result['std']}"

    def test_single_value_std_is_zero(self):
        """Sample std of a single value should be 0 (max(N-1, 1) = max(0, 1) = 1)."""
        exporter = AgentEvalExporter()
        values = [5]
        result = exporter._aggregate_numeric(values)
        assert result["std"] == 0.0

    def test_three_value_sample_std(self):
        """Sample std of [2, 4, 6] should use N-1=2 denominator."""
        exporter = AgentEvalExporter()
        values = [2, 4, 6]
        result = exporter._aggregate_numeric(values)

        # mean = 4.0
        # sample variance = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 2 = 8/2 = 4.0
        # sample std = 2.0
        assert result["std"] == 2.0

    def test_global_numeric_std_also_uses_sample(self):
        """_aggregate_numeric_global should also use sample std."""
        exporter = AgentEvalExporter()
        # Create per-trace results with known means
        per_trace_results = [
            {"annotations": {"score": {"mean": 2.0}}},
            {"annotations": {"score": {"mean": 4.0}}},
        ]
        result = exporter._aggregate_numeric_global(per_trace_results, "score")

        # mean of means = 3.0
        # sample variance = ((2-3)^2 + (4-3)^2) / 1 = 2.0
        # sample std = sqrt(2) ~ 1.414
        expected_std = round((2.0) ** 0.5, 3)
        assert result["overall_std"] == expected_std


class TestItem14UnescapedStepType:
    """
    Bug: In AgentTraceDisplay.render(), step_type values from Format 3
    data (user-provided 'step_type' field) are inserted directly into
    HTML class names and data attributes without escaping, allowing XSS.

    Fix: Apply html.escape() to step_type before use in HTML attributes.
    """

    def test_malicious_step_type_in_class(self):
        """XSS in step_type should be escaped in class attributes."""
        display = AgentTraceDisplay()
        data = [
            {"step_type": '"><script>alert(1)</script>', "content": "test"}
        ]
        html_output = display.render({"key": "trace"}, data)
        # The script tag should be escaped
        assert "<script>" not in html_output
        assert "&lt;script&gt;" in html_output or "&#" in html_output

    def test_malicious_step_type_in_data_attr(self):
        """XSS in step_type should be escaped in data-step-type attribute."""
        display = AgentTraceDisplay()
        data = [
            {"step_type": '" onmouseover="alert(1)"', "content": "test"}
        ]
        html_output = display.render({"key": "trace"}, data)
        # The attribute injection should be escaped
        assert 'onmouseover' not in html_output or '&quot;' in html_output

    def test_normal_step_type_still_works(self):
        """Normal step types should render correctly."""
        display = AgentTraceDisplay()
        data = [
            {"step_type": "thought", "content": "I need to plan"},
            {"step_type": "action", "content": "search('test')"},
            {"step_type": "observation", "content": "Found results"},
        ]
        html_output = display.render({"key": "trace"}, data)
        assert "step-type-thought" in html_output
        assert "step-type-action" in html_output
        assert "step-type-observation" in html_output

    def test_step_type_with_special_chars(self):
        """Step types with special chars like & < > should be escaped."""
        display = AgentTraceDisplay()
        data = [
            {"step_type": "action&thought", "content": "test"}
        ]
        html_output = display.render({"key": "trace"}, data)
        assert "action&amp;thought" in html_output
        # Should NOT have unescaped & in class/attribute
        assert 'step-type-action&thought' not in html_output
