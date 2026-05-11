"""Unit tests for codebook and quotation-report exporters."""

import csv
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.codebook_exporter import CodebookExporter
from potato.export.quotation_report_exporter import QuotationReportExporter
from potato.export.registry import export_registry


def _context(schemas, annotations=None, items=None):
    return ExportContext(
        config={"item_properties": {"text_key": "text"}},
        annotations=annotations or [],
        items=items or {},
        schemas=schemas,
        output_dir="",
    )


class TestCodebookExporter:
    def test_registered(self):
        assert export_registry.is_registered("codebook")

    def test_exports_flat_radio_schema(self):
        schemas = [{
            "name": "sentiment",
            "annotation_type": "radio",
            "labels": [
                {"name": "positive", "description": "Positive sentiment", "color": "#0f0"},
                {"name": "negative", "tooltip": "Negative sentiment"},
                "neutral",
            ],
        }]
        annotations = [
            {"instance_id": "i1", "labels": {"sentiment": {"positive": 1}}},
            {"instance_id": "i2", "labels": {"sentiment": {"positive": 1}}},
            {"instance_id": "i3", "labels": {"sentiment": {"negative": 1}}},
        ]
        with tempfile.TemporaryDirectory() as out:
            result = CodebookExporter().export(_context(schemas, annotations), out)
            assert result.success
            with open(result.files_written[0]) as f:
                rows = list(csv.DictReader(f))

        names = [r["code"] for r in rows]
        assert names == ["positive", "negative", "neutral"]
        assert rows[0]["description"] == "Positive sentiment"
        assert rows[0]["color"] == "#0f0"
        assert rows[0]["n_uses"] == "2"
        assert rows[1]["n_uses"] == "1"
        assert rows[2]["n_uses"] == "0"

    def test_exports_hierarchical_schema_with_parents(self):
        schemas = [{
            "name": "topics",
            "annotation_type": "hierarchical_multiselect",
            "labels": [
                {"name": "Assessment", "children": [
                    {"name": "Multiple Choice"},
                    {"name": "Essay"},
                ]},
                {"name": "Pedagogy"},
            ],
        }]
        with tempfile.TemporaryDirectory() as out:
            result = CodebookExporter().export(_context(schemas), out)
            with open(result.files_written[0]) as f:
                rows = list(csv.DictReader(f))

        parents = {r["code"]: r["parent"] for r in rows}
        assert parents["Assessment"] == ""
        assert parents["Multiple Choice"] == "Assessment"
        assert parents["Essay"] == "Assessment"
        assert parents["Pedagogy"] == ""

    def test_can_export_rejects_when_no_codeable_schema(self):
        schemas = [{"name": "txt", "annotation_type": "textbox"}]
        ok, reason = CodebookExporter().can_export(_context(schemas))
        assert not ok
        assert "No codeable schema" in reason

    def test_span_label_uses_counted(self):
        schemas = [{
            "name": "themes",
            "annotation_type": "span",
            "labels": ["frustration", "delight"],
        }]
        annotations = [
            {"instance_id": "i1", "spans": {"themes": [
                {"label": "frustration", "text": "ugh", "start": 0, "end": 3},
                {"label": "frustration", "text": "no", "start": 5, "end": 7},
                {"label": "delight", "text": "yay", "start": 10, "end": 13},
            ]}},
        ]
        with tempfile.TemporaryDirectory() as out:
            result = CodebookExporter().export(_context(schemas, annotations), out)
            with open(result.files_written[0]) as f:
                rows = list(csv.DictReader(f))
        uses = {r["code"]: int(r["n_uses"]) for r in rows}
        assert uses == {"frustration": 2, "delight": 1}


class TestQuotationReportExporter:
    def test_registered(self):
        assert export_registry.is_registered("quotation_report")

    def test_exports_one_row_per_span(self):
        schemas = [{"name": "themes", "annotation_type": "span", "labels": ["a", "b"]}]
        items = {"i1": {"text": "Hello there, world."}}
        annotations = [
            {"instance_id": "i1", "user_id": "u1", "spans": {"themes": [
                {"label": "a", "text": "Hello", "start": 0, "end": 5},
                {"label": "b", "text": "world", "start": 13, "end": 18},
            ]}},
            {"instance_id": "i1", "user_id": "u2", "spans": {"themes": [
                {"label": "a", "text": "there", "start": 6, "end": 11},
            ]}},
        ]
        with tempfile.TemporaryDirectory() as out:
            result = QuotationReportExporter().export(_context(schemas, annotations, items), out)
            with open(result.files_written[0]) as f:
                rows = list(csv.DictReader(f))

        assert len(rows) == 3
        assert {r["coder"] for r in rows} == {"u1", "u2"}
        assert {r["code"] for r in rows} == {"a", "b"}
        u1_a = next(r for r in rows if r["coder"] == "u1" and r["code"] == "a")
        assert u1_a["text"] == "Hello"
        assert u1_a["start"] == "0"
        assert u1_a["end"] == "5"
        assert u1_a["source_doc"] == "Hello there, world."

    def test_handles_alternate_offset_keys(self):
        schemas = [{"name": "s", "annotation_type": "span", "labels": ["x"]}]
        annotations = [
            {"instance_id": "i1", "user_id": "u1", "spans": {"s": [
                {"annotation": "x", "text": "foo", "start_offset": 2, "end_offset": 5},
            ]}},
        ]
        with tempfile.TemporaryDirectory() as out:
            result = QuotationReportExporter().export(_context(schemas, annotations), out)
            with open(result.files_written[0]) as f:
                rows = list(csv.DictReader(f))
        assert rows[0]["code"] == "x"
        assert rows[0]["start"] == "2"
        assert rows[0]["end"] == "5"

    def test_can_export_rejects_without_span_schema(self):
        schemas = [{"name": "rb", "annotation_type": "radio"}]
        ok, reason = QuotationReportExporter().can_export(_context(schemas))
        assert not ok
        assert "span" in reason.lower()
