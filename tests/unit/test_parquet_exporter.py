"""
Tests for the Parquet exporter.
"""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from potato.export.base import ExportContext, ExportResult
from potato.export.parquet_exporter import ParquetExporter
from potato.export.registry import export_registry


# Skip all tests if pyarrow is not installed
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


class TestParquetExporter:
    """Tests for the ParquetExporter."""

    def setup_method(self):
        self.exporter = ParquetExporter()

    def test_registered_in_registry(self):
        """parquet should be registered in the export registry."""
        assert export_registry.is_registered("parquet")

    def test_format_info(self):
        info = self.exporter.get_format_info()
        assert info["format_name"] == "parquet"
        assert ".parquet" in info["file_extensions"]
        assert "Parquet" in info["description"]

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
        assert "No annotations" in reason

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
        """Test basic export with radio annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"task_success": {"success": "1"}}},
                    {"instance_id": "t1", "user_id": "u2",
                     "labels": {"task_success": {"partial": "1"}}},
                    {"instance_id": "t2", "user_id": "u1",
                     "labels": {"task_success": {"failure": "1"}}},
                ],
                items={"t1": {"text": "trace 1"}, "t2": {"text": "trace 2"}},
                schemas=[{"name": "task_success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            # Check annotations.parquet was created
            ann_path = os.path.join(tmpdir, "annotations.parquet")
            assert os.path.exists(ann_path)
            assert ann_path in result.files_written

            # Read and verify
            table = pq.read_table(ann_path)
            assert len(table) == 3
            assert "instance_id" in table.column_names
            assert "user_id" in table.column_names
            assert "task_success" in table.column_names

            # Check values
            df = table.to_pydict()
            assert set(df["instance_id"]) == {"t1", "t2"}
            assert "success" in df["task_success"]
            assert "failure" in df["task_success"]

    def test_export_numeric(self):
        """Test export with likert/slider values as floats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"efficiency": 4}},
                    {"instance_id": "t1", "user_id": "u2", "labels": {"efficiency": 5}},
                    {"instance_id": "t2", "user_id": "u1", "labels": {"efficiency": 3.5}},
                ],
                items={},
                schemas=[{"name": "efficiency", "annotation_type": "likert"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "annotations.parquet"))
            values = table.column("efficiency").to_pylist()
            assert values == [4.0, 5.0, 3.5]

    def test_export_multiselect(self):
        """Test export with multiselect producing list columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"errors": {"loop": True, "no_errors": False}}},
                    {"instance_id": "t1", "user_id": "u2",
                     "labels": {"errors": {"no_errors": True, "loop": False}}},
                ],
                items={},
                schemas=[{"name": "errors", "annotation_type": "multiselect"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "annotations.parquet"))
            col = table.column("errors").to_pylist()
            assert col[0] == ["loop"]
            assert col[1] == ["no_errors"]

    def test_export_text(self):
        """Test export with text annotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"notes": "Looks good"}},
                ],
                items={},
                schemas=[{"name": "notes", "annotation_type": "text"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "annotations.parquet"))
            assert table.column("notes").to_pylist() == ["Looks good"]

    def test_export_spans(self):
        """Test spans.parquet generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {
                        "instance_id": "t1",
                        "user_id": "u1",
                        "labels": {"success": "yes"},
                        "spans": {
                            "hallucination": [
                                {"start": 10, "end": 25, "label": "hallucination", "text": "incorrect claim"},
                                {"start": 50, "end": 60, "label": "incorrect_fact", "text": "wrong date"},
                            ]
                        },
                    },
                    {
                        "instance_id": "t2",
                        "user_id": "u1",
                        "labels": {"success": "no"},
                        "spans": {
                            "hallucination": [
                                {"start": 5, "end": 15, "label": "hallucination", "text": "made up"},
                            ]
                        },
                    },
                ],
                items={},
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            span_path = os.path.join(tmpdir, "spans.parquet")
            assert os.path.exists(span_path)
            assert span_path in result.files_written

            table = pq.read_table(span_path)
            assert len(table) == 3
            assert "instance_id" in table.column_names
            assert "schema_name" in table.column_names
            assert "start" in table.column_names
            assert "end" in table.column_names
            assert "label" in table.column_names
            assert "text" in table.column_names

    def test_export_no_spans_when_absent(self):
        """spans.parquet should not be created if no spans exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"success": "yes"}},
                ],
                items={},
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            span_path = os.path.join(tmpdir, "spans.parquet")
            assert not os.path.exists(span_path)

    def test_export_items(self):
        """Test items.parquet from original data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"success": "yes"}},
                ],
                items={
                    "t1": {"text": "Hello world", "source": "test", "score": 0.95},
                    "t2": {"text": "Another item", "source": "test", "score": 0.8},
                },
                schemas=[{"name": "success", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            items_path = os.path.join(tmpdir, "items.parquet")
            assert os.path.exists(items_path)
            assert items_path in result.files_written

            table = pq.read_table(items_path)
            assert len(table) == 2
            assert "item_id" in table.column_names
            assert "text" in table.column_names

    def test_export_items_with_nested_data(self):
        """Test that nested dicts/lists in items are JSON-serialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}},
                ],
                items={
                    "t1": {"text": "hi", "metadata": {"key": "val"}, "tags": ["a", "b"]},
                },
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "items.parquet"))
            row = table.to_pydict()
            # Nested values should be JSON strings
            assert json.loads(row["metadata"][0]) == {"key": "val"}
            assert json.loads(row["tags"][0]) == ["a", "b"]

    def test_compression_option(self):
        """Test that compression parameter is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}},
                ],
                items={},
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir, options={"compression": "gzip"})
            assert result.success is True
            assert result.stats["compression"] == "gzip"

            # Verify file is readable and was compressed with gzip
            ann_path = os.path.join(tmpdir, "annotations.parquet")
            metadata = pq.read_metadata(ann_path)
            assert metadata.row_group(0).column(0).compression == "GZIP"

    def test_skip_items_option(self):
        """include_items=false should skip items.parquet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}},
                ],
                items={"t1": {"text": "hello"}},
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir, options={"include_items": False})
            assert result.success is True

            items_path = os.path.join(tmpdir, "items.parquet")
            assert not os.path.exists(items_path)

    def test_skip_spans_option(self):
        """include_spans=false should skip spans.parquet even if spans exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {
                        "instance_id": "t1", "user_id": "u1",
                        "labels": {"x": "y"},
                        "spans": {"s": [{"start": 0, "end": 5, "label": "l", "text": "t"}]},
                    },
                ],
                items={},
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir, options={"include_spans": False})
            assert result.success is True
            assert not os.path.exists(os.path.join(tmpdir, "spans.parquet"))

    def test_string_boolean_options(self):
        """CLI passes options as strings; verify 'false' is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}},
                ],
                items={"t1": {"text": "hello"}},
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir, options={
                "include_items": "false",
                "include_spans": "false",
            })
            assert result.success is True
            assert not os.path.exists(os.path.join(tmpdir, "items.parquet"))
            assert not os.path.exists(os.path.join(tmpdir, "spans.parquet"))

    def test_null_handling(self):
        """Missing schema values should produce null columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1",
                     "labels": {"success": {"yes": "1"}, "notes": "good"}},
                    {"instance_id": "t2", "user_id": "u1",
                     "labels": {"success": {"no": "1"}}},
                    # t2 has no "notes" label
                ],
                items={},
                schemas=[
                    {"name": "success", "annotation_type": "radio"},
                    {"name": "notes", "annotation_type": "text"},
                ],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "annotations.parquet"))
            notes_col = table.column("notes").to_pylist()
            assert notes_col[0] == "good"
            assert notes_col[1] is None

    def test_export_stats(self):
        """Verify stats in the ExportResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"},
                     "spans": {"s": [{"start": 0, "end": 1, "label": "l", "text": "t"}]}},
                ],
                items={"t1": {"text": "hi"}},
                schemas=[{"name": "x", "annotation_type": "radio"}],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.stats["annotation_rows"] == 1
            assert result.stats["span_rows"] == 1
            assert result.stats["item_rows"] == 1
            assert result.stats["compression"] == "snappy"

    def test_multiple_schemas(self):
        """Test export with multiple annotation schemas of different types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = ExportContext(
                config={},
                annotations=[
                    {
                        "instance_id": "t1", "user_id": "u1",
                        "labels": {
                            "task_success": {"success": "1"},
                            "efficiency": 4,
                            "errors": {"loop": True, "no_errors": False},
                            "notes": "Good trace",
                        },
                    },
                ],
                items={},
                schemas=[
                    {"name": "task_success", "annotation_type": "radio"},
                    {"name": "efficiency", "annotation_type": "likert"},
                    {"name": "errors", "annotation_type": "multiselect"},
                    {"name": "notes", "annotation_type": "text"},
                ],
                output_dir=tmpdir
            )

            result = self.exporter.export(context, tmpdir)
            assert result.success is True

            table = pq.read_table(os.path.join(tmpdir, "annotations.parquet"))
            row = table.to_pydict()
            assert row["task_success"] == ["success"]
            assert row["efficiency"] == [4.0]
            assert row["errors"] == [["loop"]]
            assert row["notes"] == ["Good trace"]


class TestParquetExporterPyarrowMissing:
    """Test graceful behavior when pyarrow is not installed."""

    def test_pyarrow_not_installed(self):
        """can_export should return False with helpful message when pyarrow is missing."""
        exporter = ParquetExporter()
        context = ExportContext(
            config={},
            annotations=[{"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}}],
            items={},
            schemas=[{"name": "x", "annotation_type": "radio"}],
            output_dir=""
        )

        with patch("potato.export.parquet_exporter._check_pyarrow",
                    side_effect=ImportError("No module named 'pyarrow'")):
            can, reason = exporter.can_export(context)
            assert can is False
            assert "pyarrow" in reason

    def test_export_fails_gracefully_without_pyarrow(self):
        """export should return a failed ExportResult when pyarrow is missing."""
        exporter = ParquetExporter()
        context = ExportContext(
            config={},
            annotations=[{"instance_id": "t1", "user_id": "u1", "labels": {"x": "y"}}],
            items={},
            schemas=[{"name": "x", "annotation_type": "radio"}],
            output_dir=""
        )

        with patch("potato.export.parquet_exporter._check_pyarrow",
                    side_effect=ImportError("No module named 'pyarrow'")):
            result = exporter.export(context, "/tmp/test_out")
            assert result.success is False
            assert len(result.errors) > 0
