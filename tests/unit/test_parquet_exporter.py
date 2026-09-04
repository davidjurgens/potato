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


# ---------------------------------------------------------------------------
# Audit 9: two ways parquet silently dropped data that csv and jsonl kept.
# ---------------------------------------------------------------------------

import pytest

from potato.export.base import ExportContext
from potato.export.parquet_exporter import ParquetExporter


def _exporter():
    return ParquetExporter.__new__(ParquetExporter)


class TestALabelledScaleIsNotNull:
    """A `likert` with an explicit `labels:` list stores a label, not a number.

    The generator renders it as a radio group and says so at boot ("Complex
    labels detected ... using radio layout"), so the stored value is
    `{"Moderate": "Moderate"}`. Routing on the declared type alone sent that to
    `_flatten_numeric`, which returned None for every row -- so the column was
    present and entirely null, indistinguishable from a scheme nobody answered.
    csv kept it, /admin/iaa scored it as ordinal, and the shape is the one the
    bundled full-study skeleton recommends.
    """

    @pytest.mark.parametrize("value,expected", [
        ({"Moderate": "Moderate"}, "Moderate"),
        ({"Severe": "Severe"}, "Severe"),
    ])
    def test_a_labelled_point_survives(self, value, expected):
        assert _exporter()._flatten_value(value, "likert") == expected

    @pytest.mark.parametrize("schema_type", ["likert", "slider", "number"])
    def test_a_numeric_answer_is_still_a_number(self, schema_type):
        assert _exporter()._flatten_value({"scale_3": "3"}, schema_type) == 3.0
        assert _exporter()._flatten_value("0.7", schema_type) == 0.7

    def test_no_answer_is_still_null(self):
        assert _exporter()._flatten_value(None, "likert") is None
        assert _exporter()._flatten_value({}, "likert") is None


class TestFreeTextIsTheTextNotTheContainer:
    """`str()` on a textbox's dict gave `{'text_box': 'alice r06'}` in the file."""

    def test_a_textbox_exports_what_was_typed(self):
        assert _exporter()._flatten_value(
            {"text_box": "alice r06"}, "text") == "alice r06"

    def test_a_plain_string_is_unchanged(self):
        assert _exporter()._flatten_value("already text", "text") == "already text"

    def test_an_empty_answer_is_null_not_an_empty_dict_repr(self):
        assert _exporter()._flatten_value({"text_box": ""}, "text") is None
        assert _exporter()._flatten_value(None, "text") is None


class TestAColumnKeepsOneType:
    """Parquet columns are typed, and `from_pylist` aborts the WHOLE export.

    A labelled scale can genuinely mix: `labels: [1, 2, 3, "Not applicable"]`
    flattens to three floats and a string. Deciding the shape per column rather
    than per value keeps the file writable and every answer in it.
    """

    def test_a_mixed_scale_becomes_text_rather_than_failing(self):
        rows = _exporter()._build_annotation_rows(
            [
                {"instance_id": "i1", "user_id": "a",
                 "labels": {"severity": {"3": "3"}}},
                {"instance_id": "i2", "user_id": "b",
                 "labels": {"severity": {"Not applicable": "Not applicable"}}},
            ],
            {"severity": {"annotation_type": "likert"}},
        )
        assert [r["severity"] for r in rows] == ["3", "Not applicable"]

        pa = pytest.importorskip("pyarrow")
        table = pa.Table.from_pylist(rows)
        assert table.num_rows == 2

    def test_a_scale_point_reads_as_written(self):
        """`3`, not `3.0` -- it came from a label, not a measurement."""
        rows = _exporter()._build_annotation_rows(
            [
                {"instance_id": "i1", "user_id": "a",
                 "labels": {"s": {"2.5": "2.5"}}},
                {"instance_id": "i2", "user_id": "b",
                 "labels": {"s": {"Skip": "Skip"}}},
            ],
            {"s": {"annotation_type": "likert"}},
        )
        assert [r["s"] for r in rows] == ["2.5", "Skip"]

    def test_a_uniform_numeric_column_stays_numeric(self):
        rows = _exporter()._build_annotation_rows(
            [
                {"instance_id": "i1", "user_id": "a", "labels": {"s": {"3": "3"}}},
                {"instance_id": "i2", "user_id": "b", "labels": {"s": {"4": "4"}}},
            ],
            {"s": {"annotation_type": "likert"}},
        )
        assert [r["s"] for r in rows] == [3.0, 4.0]


class TestPhaseResponsesReachTheFile:
    """`export_include_phase_data` was read by csv and jsonl and ignored here.

    parquet wrote annotations, items and spans and no phase file at all, and
    its stats did not mention phase responses either way -- so unlike csv there
    was not even a count to notice. A study collecting consent and a post-study
    survey handed over neither, and the key read as honoured.
    """

    PHASE_ROWS = [
        {"user_id": "alice", "phase": "consent", "page": "consent",
         "sequence": 0, "schema": "consent_agree", "label_name": "I agree",
         "value": "I agree"},
        {"user_id": "alice", "phase": "poststudy", "page": "poststudy",
         "sequence": 1, "schema": "comments", "label_name": "text_box",
         "value": "alice poststudy comment"},
    ]

    def _context(self, include: bool):
        return ExportContext(
            config={"export_include_phase_data": include,
                    "item_properties": {"text_key": "text"}},
            annotations=[{"instance_id": "i1", "user_id": "alice",
                          "labels": {"s": {"Yes": "Yes"}}, "spans": {}}],
            items={"i1": {"text": "hello"}},
            schemas=[{"annotation_type": "radio", "name": "s",
                      "description": "d", "labels": ["Yes", "No"]}],
            phase_responses=list(self.PHASE_ROWS),
            output_dir="",
        )

    def test_the_file_is_written_when_the_key_is_on(self, tmp_path):
        pytest.importorskip("pyarrow")
        result = ParquetExporter().export(self._context(True), str(tmp_path))

        assert result.success, result.errors
        written = {os.path.basename(f) for f in result.files_written}
        assert "phase_responses.parquet" in written
        assert result.stats["phase_response_rows"] == 2

    def test_the_rows_match_what_csv_writes(self, tmp_path):
        pq = pytest.importorskip("pyarrow.parquet")
        ParquetExporter().export(self._context(True), str(tmp_path))

        table = pq.read_table(str(tmp_path / "phase_responses.parquet"))
        rows = table.to_pylist()
        assert [r["value"] for r in rows] == [
            "I agree", "alice poststudy comment"]
        assert [r["schema"] for r in rows] == ["consent_agree", "comments"]
        for column in ("user_id", "phase", "page", "sequence", "label_name"):
            assert column in table.column_names

    def test_the_key_being_off_warns_rather_than_going_quiet(self, tmp_path):
        pytest.importorskip("pyarrow")
        result = ParquetExporter().export(self._context(False), str(tmp_path))

        written = {os.path.basename(f) for f in result.files_written}
        assert "phase_responses.parquet" not in written
        assert result.stats["phase_responses_excluded"] == 2
        assert any("export_include_phase_data" in w for w in result.warnings), (
            "silently dropping them is the bug; the count and the warning are "
            "what make it visible"
        )


class TestCompositeAnswersSurvive:
    """A dict whose keys are not its values is not a categorical answer.

    ``_flatten_categorical`` reads a stored dict as "the chosen label is one of
    the keys" and returns one. That holds for a radio and for a labelled scale,
    where the key *is* the answer, and it is false for every scheme storing
    several sub-answers keyed by row, option or step -- so a three-row multirate
    exported as the string "Reproducibility" (the first row's *name*) and an
    image annotation as "_data". Fifty-four of the sixty-one registered types
    took that branch. csv had all of it right in the same export.
    """

    SCHEMAS = [
        {"name": "handling", "annotation_type": "multirate"},
        {"name": "uibox", "annotation_type": "image_annotation"},
        {"name": "severity", "annotation_type": "likert"},
        {"name": "confidence", "annotation_type": "confidence"},
    ]

    ANNOTATIONS = [
        {"instance_id": "i1", "user_id": "alice", "labels": {
            "handling": {"Reproducibility": "Medium", "Customer tone": "High",
                         "Urgency": "Low"},
            "uibox": {"_data": "[]"},
            "severity": {"Serious": "Serious"},
            "confidence": {"5": "5"}}},
        {"instance_id": "i1", "user_id": "bob", "labels": {
            "handling": {"Reproducibility": "Low", "Customer tone": "Low",
                         "Urgency": "High"},
            "uibox": {"_data": '[{"x": 1}]'},
            "severity": {"Minor": "Minor"},
            "confidence": {"3": "3"}}},
    ]

    def _rows(self, tmp_path, annotations=None, schemas=None, items=None):
        context = ExportContext(
            config={}, annotations=annotations or self.ANNOTATIONS,
            items=items if items is not None else {},
            schemas=schemas or self.SCHEMAS, output_dir=str(tmp_path))
        result = ParquetExporter().export(context, str(tmp_path))
        assert result.success, result.errors
        return pq.read_table(str(tmp_path / "annotations.parquet")).to_pylist()

    def test_multirate_keeps_every_row(self, tmp_path):
        rows = self._rows(tmp_path)
        assert rows[0]["handling.Reproducibility"] == "Medium"
        assert rows[0]["handling.Customer tone"] == "High"
        assert rows[0]["handling.Urgency"] == "Low"
        assert rows[1]["handling.Urgency"] == "High"
        # Not the row name, which is what the column used to hold.
        assert "handling" not in rows[0]

    def test_geometry_keeps_its_blob(self, tmp_path):
        rows = self._rows(tmp_path)
        assert rows[0]["uibox._data"] == "[]"
        assert json.loads(rows[1]["uibox._data"]) == [{"x": 1}]

    def test_composite_columns_match_what_csv_writes(self, tmp_path):
        """The two formats must agree about the answers csv already got right.

        Only for the composite schemas. The formats differ on purpose for a
        single-select: csv writes one column per label (`severity.Serious`),
        parquet one typed column per schema (`severity` = "Serious"), which is
        the shape that is usable in a dataframe.
        """
        from potato.export.tabular_exporter import _flatten_annotation

        parquet_row = self._rows(tmp_path)[0]
        csv_row = _flatten_annotation(self.ANNOTATIONS[0])
        composite = {c: v for c, v in csv_row.items()
                     if c.startswith(("handling.", "uibox."))}
        assert composite, "the fixture must exercise composite answers"
        for column, value in composite.items():
            assert column in parquet_row, f"{column} missing from parquet"
            assert str(parquet_row[column]) == str(value)

    def test_a_genuine_categorical_is_left_alone(self, tmp_path):
        """`{"5": "5"}` and a labelled scale keep their single column."""
        rows = self._rows(tmp_path)
        assert rows[0]["confidence"] == "5"
        assert rows[0]["severity"] == "Serious"


class TestNoColumnIsDroppedByRowOne:
    """`pa.Table.from_pylist` infers the schema from the first row alone.

    Any key that row lacks was absent from the whole file -- not null, gone --
    however many later rows carried it. An optional textbox, a scheme behind
    `display_logic`, or an item field only some items have all hit it.
    """

    def test_a_schema_only_a_later_row_answered_survives(self, tmp_path):
        annotations = [
            {"instance_id": "i1", "user_id": "alice",
             "labels": {"category": {"Bug": "Bug"}}},
            {"instance_id": "i2", "user_id": "bob",
             "labels": {"category": {"Bug": "Bug"},
                        "notes": {"text_box": "only bob wrote this"}}},
        ]
        schemas = [{"name": "category", "annotation_type": "radio"},
                   {"name": "notes", "annotation_type": "text"}]
        context = ExportContext(config={}, annotations=annotations, items={},
                                schemas=schemas, output_dir=str(tmp_path))
        assert ParquetExporter().export(context, str(tmp_path)).success

        table = pq.read_table(str(tmp_path / "annotations.parquet"))
        assert "notes" in table.column_names
        rows = table.to_pylist()
        assert rows[0]["notes"] is None
        assert rows[1]["notes"] == "only bob wrote this"

    def test_an_item_field_only_some_items_carry_survives(self, tmp_path):
        annotations = [{"instance_id": "i1", "user_id": "alice",
                        "labels": {"category": {"Bug": "Bug"}}}]
        items = {"i1": {"text": "a"},
                 "i2": {"text": "b", "screenshot": "http://host/s.png"}}
        context = ExportContext(
            config={}, annotations=annotations, items=items,
            schemas=[{"name": "category", "annotation_type": "radio"}],
            output_dir=str(tmp_path))
        assert ParquetExporter().export(context, str(tmp_path)).success

        rows = pq.read_table(str(tmp_path / "items.parquet")).to_pylist()
        assert rows[0]["screenshot"] is None
        assert rows[1]["screenshot"] == "http://host/s.png"
