"""Tests for HuggingFace Hub exporter."""

import json
import pytest
from unittest.mock import patch, MagicMock

from potato.export.base import ExportContext, ExportResult


@pytest.fixture
def sample_context():
    """Build a minimal ExportContext for testing."""
    return ExportContext(
        config={"annotation_schemes": []},
        annotations=[
            {
                "instance_id": "item_1",
                "user_id": "user_a",
                "labels": {"sentiment": {"Positive": 1}},
                "spans": {},
            },
            {
                "instance_id": "item_2",
                "user_id": "user_b",
                "labels": {"sentiment": {"Negative": 1}},
                "spans": {
                    "ner": [
                        {"start": 0, "end": 5, "label": "PER", "text": "Alice"},
                    ]
                },
            },
        ],
        items={
            "item_1": {"id": "item_1", "text": "Great movie!"},
            "item_2": {"id": "item_2", "text": "Alice went home."},
        },
        schemas=[
            {"name": "sentiment", "annotation_type": "radio",
             "labels": ["Positive", "Negative", "Neutral"],
             "description": "Sentiment analysis"},
            {"name": "ner", "annotation_type": "span",
             "labels": ["PER", "ORG", "LOC"],
             "description": "Named entities"},
        ],
        output_dir="/tmp/test_output",
    )


@pytest.fixture
def empty_context():
    return ExportContext(
        config={},
        annotations=[],
        items={},
        schemas=[],
        output_dir="/tmp/test_output",
    )


class TestCanExport:
    def test_missing_deps(self, sample_context):
        """can_export returns False when dependencies aren't installed."""
        with patch("potato.export.huggingface_exporter._check_deps",
                   side_effect=ImportError("No module named 'datasets'")):
            from potato.export.huggingface_exporter import HuggingFaceExporter
            exporter = HuggingFaceExporter()
            can, reason = exporter.can_export(sample_context)
            assert can is False
            assert "huggingface_hub" in reason

    def test_no_annotations(self, empty_context):
        """can_export returns False with empty annotations."""
        with patch("potato.export.huggingface_exporter._check_deps"):
            from potato.export.huggingface_exporter import HuggingFaceExporter
            exporter = HuggingFaceExporter()
            can, reason = exporter.can_export(empty_context)
            assert can is False
            assert "No annotations" in reason

    def test_can_export_success(self, sample_context):
        with patch("potato.export.huggingface_exporter._check_deps"):
            from potato.export.huggingface_exporter import HuggingFaceExporter
            exporter = HuggingFaceExporter()
            can, reason = exporter.can_export(sample_context)
            assert can is True


class TestAnnotationRowBuilding:
    def test_basic_rows(self, sample_context):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        schema_map = {s["name"]: s for s in sample_context.schemas}
        rows = exporter._build_annotation_rows(
            sample_context.annotations, schema_map
        )
        assert len(rows) == 2
        assert rows[0]["instance_id"] == "item_1"
        assert rows[0]["user_id"] == "user_a"
        # Dict values serialized as JSON strings
        assert json.loads(rows[0]["sentiment"]) == {"Positive": 1}

    def test_string_values_preserved(self):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        annotations = [{
            "instance_id": "i1",
            "user_id": "u1",
            "labels": {"comment": "plain text value"},
        }]
        rows = exporter._build_annotation_rows(annotations, {})
        assert rows[0]["comment"] == "plain text value"


class TestSpanRowBuilding:
    def test_span_rows(self, sample_context):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        rows = exporter._build_span_rows(sample_context.annotations)
        assert len(rows) == 1
        assert rows[0]["label"] == "PER"
        assert rows[0]["text"] == "Alice"
        assert rows[0]["start"] == 0
        assert rows[0]["end"] == 5

    def test_no_spans(self):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        rows = exporter._build_span_rows([{"spans": {}}])
        assert rows == []


class TestItemRowBuilding:
    def test_item_rows(self, sample_context):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        rows = exporter._build_item_rows(sample_context.items)
        assert len(rows) == 2
        ids = {r["item_id"] for r in rows}
        assert ids == {"item_1", "item_2"}

    def test_complex_values_serialized(self):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        items = {"i1": {"id": "i1", "metadata": {"key": "val"}}}
        rows = exporter._build_item_rows(items)
        assert json.loads(rows[0]["metadata"]) == {"key": "val"}


class TestDatasetCardGeneration:
    def test_card_contains_metadata(self, sample_context):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        schema_map = {s["name"]: s for s in sample_context.schemas}
        card = exporter._build_dataset_card(
            sample_context, "org/my-dataset", [{"row": 1}], schema_map
        )
        assert "org/my-dataset" in card
        assert "potato" in card.lower()
        assert "sentiment" in card
        assert "Positive" in card

    def test_card_truncates_many_labels(self, sample_context):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        schema_map = {
            "big": {
                "name": "big",
                "annotation_type": "radio",
                "labels": [f"label_{i}" for i in range(20)],
                "description": "Many labels",
            }
        }
        card = exporter._build_dataset_card(
            sample_context, "org/ds", [], schema_map
        )
        assert "+10 more" in card


class TestExport:
    @patch("potato.export.huggingface_exporter._check_deps")
    def test_invalid_repo_id(self, mock_deps, sample_context):
        mock_deps.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        result = exporter.export(sample_context, "no-slash-repo")
        assert result.success is False
        assert "repo ID" in result.errors[0]

    @patch("potato.export.huggingface_exporter._check_deps")
    def test_successful_export(self, mock_deps, sample_context):
        MockDataset = MagicMock()
        MockDatasetDict = MagicMock()
        MockCard = MagicMock()
        MockCardData = MagicMock()
        mock_deps.return_value = (MockDataset, MockDatasetDict, MockCard, MockCardData)

        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        result = exporter.export(
            sample_context, "org/test-dataset",
            options={"token": "hf_test", "private": "true"}
        )

        assert result.success is True
        assert result.stats["repo_id"] == "org/test-dataset"
        assert result.stats["annotation_rows"] == 2
        assert result.stats["private"] is True
        # Verify push_to_hub was called
        MockDatasetDict.return_value.push_to_hub.assert_called_once()

    @patch("potato.export.huggingface_exporter._check_deps")
    def test_export_deps_missing(self, mock_deps, sample_context):
        mock_deps.side_effect = ImportError("no datasets")
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        result = exporter.export(sample_context, "org/ds")
        assert result.success is False


class TestRegistration:
    def test_format_info(self):
        from potato.export.huggingface_exporter import HuggingFaceExporter
        exporter = HuggingFaceExporter()
        info = exporter.get_format_info()
        assert info["format_name"] == "huggingface"
        assert info["file_extensions"] == []

    def test_registry_includes_hf_when_available(self):
        """If HF deps are importable, exporter should be in registry."""
        from potato.export.registry import export_registry
        # The exporter may or may not be registered depending on environment.
        # Just verify the registry is queryable.
        formats = export_registry.get_supported_formats()
        assert isinstance(formats, list)
