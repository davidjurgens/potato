"""
Tests for the agent evaluation exporter.
"""

import json
import os
import pytest
import tempfile

from potato.export.agent_eval_exporter import AgentEvalExporter
from potato.export.base import ExportContext, ExportResult
from potato.export.registry import export_registry


class TestAgentEvalExporter:
    """Tests for the AgentEvalExporter."""

    def setup_method(self):
        self.exporter = AgentEvalExporter()

    def test_registered_in_registry(self):
        """agent_eval should be registered in the export registry."""
        assert export_registry.is_registered("agent_eval")

    def test_format_info(self):
        info = self.exporter.get_format_info()
        assert info["format_name"] == "agent_eval"
        assert ".json" in info["file_extensions"]

    def test_can_export_empty(self):
        context = ExportContext(
            config={},
            annotations=[],
            items={},
            schemas=[],
            output_dir=""
        )
        can, reason = self.exporter.can_export(context)
        assert can is False

    def test_can_export_valid(self):
        context = ExportContext(
            config={},
            annotations=[{"instance_id": "t1", "user_id": "u1", "labels": {"success": "yes"}}],
            items={"t1": {}},
            schemas=[{"name": "success", "annotation_type": "radio"}],
            output_dir=""
        )
        can, reason = self.exporter.can_export(context)
        assert can is True

    def test_export_basic(self):
        """Test basic export with categorical annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "trace_001", "user_id": "ann1",
                     "labels": {"task_success": {"success": "1"}}},
                    {"instance_id": "trace_001", "user_id": "ann2",
                     "labels": {"task_success": {"success": "1"}}},
                    {"instance_id": "trace_002", "user_id": "ann1",
                     "labels": {"task_success": {"failure": "1"}}},
                ],
                items={"trace_001": {}, "trace_002": {}},
                schemas=[{"name": "task_success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True
            assert len(result.files_written) == 2

            # Check JSON output
            json_file = os.path.join(tmpdir, "agent_evaluation.json")
            assert os.path.exists(json_file)

            with open(json_file) as f:
                output = json.load(f)

            assert output["summary"]["total_traces"] == 2
            assert output["summary"]["total_annotators"] == 2
            assert len(output["per_trace"]) == 2

    def test_export_numeric(self):
        """Test export with numeric (likert) annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"efficiency": 4}},
                    {"instance_id": "t1", "user_id": "u2", "labels": {"efficiency": 5}},
                ],
                items={"t1": {}},
                schemas=[{"name": "efficiency", "annotation_type": "likert"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            with open(os.path.join(tmpdir, "agent_evaluation.json")) as f:
                output = json.load(f)

            trace = output["per_trace"][0]
            eff = trace["annotations"]["efficiency"]
            assert eff["mean"] == 4.5
            assert len(eff["values"]) == 2

    def test_export_multiselect(self):
        """Test export with multiselect annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"errors": {"loop": True, "no_errors": False}}},
                    {"instance_id": "t1", "user_id": "u2",
                     "labels": {"errors": {"no_errors": True}}},
                ],
                items={"t1": {}},
                schemas=[{"name": "errors", "annotation_type": "multiselect"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            with open(os.path.join(tmpdir, "agent_evaluation.json")) as f:
                output = json.load(f)

            errors = output["per_trace"][0]["annotations"]["errors"]
            assert errors["counts"]["loop"] == 1
            assert errors["counts"]["no_errors"] == 1

    def test_csv_output(self):
        """Test that CSV summary is generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"success": {"yes": "1"}}},
                ],
                items={"t1": {}},
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            csv_file = os.path.join(tmpdir, "agent_evaluation_summary.csv")
            assert os.path.exists(csv_file)

            with open(csv_file) as f:
                lines = f.readlines()
            assert len(lines) == 2  # header + 1 trace
            assert "trace_id" in lines[0]
