"""
Tests for CoNLL-2003 and CoNLL-U exporters.
"""

import os
import pytest
import tempfile

from potato.export.base import ExportContext
from potato.export.conll_2003_exporter import CoNLL2003Exporter
from potato.export.conll_u_exporter import CoNLLUExporter


def _make_span_context(text="John lives in New York", spans=None, schemas=None):
    """Helper to build a span annotation context."""
    if spans is None:
        spans = [
            {"start": 0, "end": 4, "name": "PER"},
            {"start": 14, "end": 22, "name": "LOC"},
        ]
    return ExportContext(
        config={"item_properties": {"text_key": "text"}},
        annotations=[{
            "instance_id": "doc1",
            "user_id": "user1",
            "spans": {"ner": spans},
            "labels": {},
        }],
        items={"doc1": {"text": text}},
        schemas=schemas or [{"annotation_type": "span", "name": "ner",
                             "labels": ["PER", "LOC", "ORG"]}],
        output_dir="",
    )


class TestCoNLL2003Exporter:
    def setup_method(self):
        self.exporter = CoNLL2003Exporter()

    def test_can_export_with_span_schema(self):
        ctx = _make_span_context()
        can, reason = self.exporter.can_export(ctx)
        assert can

    def test_can_export_without_span_schema(self):
        ctx = _make_span_context(schemas=[{"annotation_type": "radio", "name": "q1"}])
        can, reason = self.exporter.can_export(ctx)
        assert not can

    def test_export_basic(self):
        ctx = _make_span_context()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_entities"] == 2

            out_file = os.path.join(tmpdir, "annotations.conll")
            assert os.path.exists(out_file)

            with open(out_file) as f:
                content = f.read()

            # Should contain -DOCSTART- marker
            assert "-DOCSTART-" in content
            # Should contain BIO tags
            assert "B-PER" in content
            assert "B-LOC" in content
            assert "I-LOC" in content

    def test_export_no_text_warns(self):
        ctx = ExportContext(
            config={"item_properties": {"text_key": "text"}},
            annotations=[{
                "instance_id": "doc1", "user_id": "u1",
                "spans": {"ner": []}, "labels": {},
            }],
            items={"doc1": {}},
            schemas=[{"annotation_type": "span", "name": "ner"}],
            output_dir="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert any("No text" in w for w in result.warnings)

    def test_export_tab_separated(self):
        ctx = _make_span_context(text="Hello world", spans=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            out_file = os.path.join(tmpdir, "annotations.conll")
            with open(out_file) as f:
                lines = f.read().strip().split("\n")

            # Find first non-docstart, non-empty line
            data_lines = [l for l in lines if l and not l.startswith("-DOCSTART-")]
            if data_lines:
                parts = data_lines[0].split("\t")
                assert len(parts) == 4  # WORD POS CHUNK NER


class TestCoNLLUExporter:
    def setup_method(self):
        self.exporter = CoNLLUExporter()

    def test_can_export_with_span_schema(self):
        ctx = _make_span_context()
        can, reason = self.exporter.can_export(ctx)
        assert can

    def test_export_basic(self):
        ctx = _make_span_context()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_entities"] == 2

            out_file = os.path.join(tmpdir, "annotations.conllu")
            assert os.path.exists(out_file)

            with open(out_file) as f:
                content = f.read()

            # Should have comment lines
            assert "# sent_id" in content
            assert "# text" in content

    def test_export_10_columns(self):
        ctx = _make_span_context(text="Hello world", spans=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            out_file = os.path.join(tmpdir, "annotations.conllu")
            with open(out_file) as f:
                lines = f.read().strip().split("\n")

            data_lines = [l for l in lines if l and not l.startswith("#")]
            if data_lines:
                parts = data_lines[0].split("\t")
                assert len(parts) == 10  # CoNLL-U has 10 columns

    def test_export_ner_in_misc(self):
        ctx = _make_span_context(
            text="John works",
            spans=[{"start": 0, "end": 4, "name": "PER"}],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            out_file = os.path.join(tmpdir, "annotations.conllu")
            with open(out_file) as f:
                content = f.read()

            assert "NER=B-PER" in content

    def test_export_list_text(self):
        """Text stored as list should be joined."""
        ctx = ExportContext(
            config={"item_properties": {"text_key": "text"}},
            annotations=[{
                "instance_id": "doc1", "user_id": "u1",
                "spans": {"ner": []}, "labels": {},
            }],
            items={"doc1": {"text": ["Hello", "world"]}},
            schemas=[{"annotation_type": "span", "name": "ner"}],
            output_dir="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_tokens"] == 2
