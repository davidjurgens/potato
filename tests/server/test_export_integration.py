"""
Server integration tests for the export system.

Tests the export infrastructure with real annotation data:
- Export registry integration
- COCO, YOLO, Pascal VOC exports from image annotation data
- CoNLL-2003, CoNLL-U exports from span annotation data
- ExportContext construction
"""

import pytest
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.export import export_registry, ExportContext, ExportResult, BaseExporter
from potato.export.cv_utils import (
    build_category_mapping, polygon_to_bbox, normalize_bbox, flatten_polygon,
    polygon_area, get_image_filename,
)
from potato.export.nlp_utils import tokenize_text, char_spans_to_bio_tags, group_sentences


class TestExportRegistryIntegration:
    """Test export registry is fully integrated and functional."""

    def test_all_exporters_registered(self):
        formats = export_registry.get_supported_formats()
        assert "coco" in formats
        assert "yolo" in formats
        assert "pascal_voc" in formats
        assert "conll_2003" in formats
        assert "conll_u" in formats
        assert "mask_png" in formats

    def test_get_exporter_returns_instance(self):
        exporter = export_registry.get("coco")
        assert exporter is not None
        assert isinstance(exporter, BaseExporter)

    def test_get_nonexistent_exporter(self):
        exporter = export_registry.get("nonexistent_format")
        assert exporter is None

    def test_exporters_have_required_attributes(self):
        for fmt in export_registry.get_supported_formats():
            exporter = export_registry.get(fmt)
            assert hasattr(exporter, 'format_name')
            assert hasattr(exporter, 'description')
            assert hasattr(exporter, 'file_extensions')
            assert len(exporter.format_name) > 0
            assert len(exporter.description) > 0


class TestCOCOExportIntegration:
    """Test COCO export with realistic annotation data.

    The COCO exporter expects annotations with 'image_annotations' key
    (a dict of schema_name -> list of annotation objects), which is the
    format produced by the CLI's load_annotations_from_output_dir().
    """

    def _make_context(self, annotations, items=None, schemas=None):
        return ExportContext(
            config={},
            annotations=annotations,
            items=items or {},
            schemas=schemas or [
                {"annotation_type": "image_annotation", "name": "detection",
                 "labels": [{"name": "cat"}, {"name": "dog"}, {"name": "person"}, {"name": "object"}, {"name": "car"}]}
            ],
            output_dir="/tmp/test_export",
        )

    def test_can_export_with_image_schema(self):
        ctx = self._make_context([])
        exporter = export_registry.get("coco")
        can, msg = exporter.can_export(ctx)
        assert can is True

    def test_cannot_export_without_image_schema(self):
        ctx = ExportContext(
            config={}, annotations=[], items={},
            schemas=[{"annotation_type": "radio", "name": "sentiment"}],
            output_dir="/tmp",
        )
        exporter = export_registry.get("coco")
        can, msg = exporter.can_export(ctx)
        assert can is False

    def test_export_produces_valid_coco_json(self, tmp_path):
        annotations = [
            {
                "instance_id": "img_001",
                "user_id": "user1",
                "image_annotations": {
                    "detection": [
                        {"type": "bbox", "label": "cat", "x": 50, "y": 60, "width": 120, "height": 80},
                        {"type": "polygon", "label": "dog", "points": [[10, 10], [100, 10], [100, 100], [10, 100]]},
                    ]
                },
            }
        ]
        ctx = self._make_context(annotations)
        exporter = export_registry.get("coco")
        output_path = str(tmp_path / "coco_output")
        result = exporter.export(ctx, output_path)

        assert result.success
        out_file = os.path.join(output_path, "annotations.json")
        assert os.path.exists(out_file)

        with open(out_file) as f:
            coco = json.load(f)

        assert "images" in coco
        assert "annotations" in coco
        assert "categories" in coco
        assert len(coco["images"]) == 1
        assert len(coco["annotations"]) == 2

        # Verify bbox annotation
        bbox_ann = [a for a in coco["annotations"] if a.get("bbox") == [50, 60, 120, 80]]
        assert len(bbox_ann) == 1

    def test_export_multiple_images(self, tmp_path):
        annotations = [
            {
                "instance_id": f"img_{i:03d}",
                "user_id": "user1",
                "image_annotations": {
                    "detection": [
                        {"type": "bbox", "label": "object", "x": i * 10, "y": i * 10, "width": 50, "height": 50}
                    ]
                },
            }
            for i in range(5)
        ]
        ctx = self._make_context(annotations)
        exporter = export_registry.get("coco")
        output_path = str(tmp_path / "coco_multi")
        result = exporter.export(ctx, output_path)

        assert result.success
        out_file = os.path.join(output_path, "annotations.json")
        with open(out_file) as f:
            coco = json.load(f)
        assert len(coco["images"]) == 5
        assert len(coco["annotations"]) == 5


class TestYOLOExportIntegration:
    """Test YOLO export with realistic annotation data."""

    def test_export_creates_required_files(self, tmp_path):
        annotations = [
            {
                "instance_id": "img_001",
                "user_id": "user1",
                "image_annotations": {
                    "detection": [
                        {"type": "bbox", "label": "person", "x": 100, "y": 150, "width": 200, "height": 300}
                    ]
                },
            }
        ]
        ctx = ExportContext(
            config={"image_dimensions": {"width": 800, "height": 600}},
            annotations=annotations,
            items={},
            schemas=[{"annotation_type": "image_annotation", "name": "detection",
                      "labels": [{"name": "person"}]}],
            output_dir=str(tmp_path),
        )
        exporter = export_registry.get("yolo")
        output_dir = str(tmp_path / "yolo_out")
        os.makedirs(output_dir, exist_ok=True)
        result = exporter.export(ctx, output_dir, options={"image_width": 800, "image_height": 600})

        assert result.success
        classes_file = os.path.join(output_dir, "classes.txt")
        assert os.path.exists(classes_file)
        with open(classes_file) as f:
            classes = f.read().strip().split("\n")
        assert "person" in classes


class TestPascalVOCExportIntegration:
    """Test Pascal VOC export with realistic annotation data."""

    def test_export_creates_xml_files(self, tmp_path):
        annotations = [
            {
                "instance_id": "img_001",
                "user_id": "user1",
                "image_annotations": {
                    "detection": [
                        {"type": "bbox", "label": "car", "x": 50, "y": 75, "width": 200, "height": 150}
                    ]
                },
            }
        ]
        ctx = ExportContext(
            config={},
            annotations=annotations,
            items={},
            schemas=[{"annotation_type": "image_annotation", "name": "detection",
                      "labels": [{"name": "car"}]}],
            output_dir=str(tmp_path),
        )
        exporter = export_registry.get("pascal_voc")
        output_dir = str(tmp_path / "voc_out")
        os.makedirs(output_dir, exist_ok=True)
        result = exporter.export(ctx, output_dir)

        assert result.success
        xml_files = [f for f in os.listdir(output_dir) if f.endswith(".xml")]
        assert len(xml_files) >= 1

        import xml.etree.ElementTree as ET
        tree = ET.parse(os.path.join(output_dir, xml_files[0]))
        root = tree.getroot()
        assert root.tag == "annotation"
        objects = root.findall("object")
        assert len(objects) == 1
        assert objects[0].find("name").text == "car"


class TestCoNLLExportIntegration:
    """Test CoNLL exports with realistic span annotation data.

    The CoNLL exporters expect 'spans' as a dict: {schema_name: [span_list]},
    which is the format produced by the CLI's load_annotations_from_output_dir().
    """

    def _make_span_context(self, text_items, span_annotations):
        annotations = []
        items = {}
        for item_id, text in text_items.items():
            items[item_id] = {"id": item_id, "text": text}
            raw_spans = span_annotations.get(item_id, [])
            # Format spans as dict keyed by schema name (as the exporter expects)
            spans_dict = {}
            if raw_spans:
                spans_dict["ner"] = raw_spans
            annotations.append({
                "instance_id": item_id,
                "user_id": "user1",
                "spans": spans_dict,
                "labels": {},
            })
        return ExportContext(
            config={},
            annotations=annotations,
            items=items,
            schemas=[{"annotation_type": "span", "name": "ner"}],
            output_dir="/tmp/test_conll",
        )

    def test_conll_2003_export(self, tmp_path):
        ctx = self._make_span_context(
            {"doc1": "John works at Google in New York."},
            {
                "doc1": [
                    {"schema": "ner", "name": "PER", "start": 0, "end": 4},
                    {"schema": "ner", "name": "ORG", "start": 14, "end": 20},
                    {"schema": "ner", "name": "LOC", "start": 24, "end": 32},
                ]
            },
        )
        exporter = export_registry.get("conll_2003")
        output_dir = str(tmp_path / "conll_out")
        result = exporter.export(ctx, output_dir)

        assert result.success
        out_file = os.path.join(output_dir, "annotations.conll")
        assert os.path.exists(out_file)

        with open(out_file) as f:
            content = f.read()
        assert "B-PER" in content
        assert "B-ORG" in content

    def test_conll_u_export(self, tmp_path):
        ctx = self._make_span_context(
            {"doc1": "Marie lives in Paris."},
            {
                "doc1": [
                    {"schema": "ner", "name": "PER", "start": 0, "end": 5},
                    {"schema": "ner", "name": "LOC", "start": 15, "end": 20},
                ]
            },
        )
        exporter = export_registry.get("conll_u")
        output_dir = str(tmp_path / "conllu_out")
        result = exporter.export(ctx, output_dir)

        assert result.success
        out_file = os.path.join(output_dir, "annotations.conllu")
        assert os.path.exists(out_file)

        with open(out_file) as f:
            content = f.read()
        assert "# sent_id" in content
        assert "NER=B-PER" in content

    def test_conll_export_empty_spans(self, tmp_path):
        """Text with no spans should produce all O tags."""
        ctx = self._make_span_context(
            {"doc1": "No entities here."},
            {"doc1": []},
        )
        exporter = export_registry.get("conll_2003")
        output_dir = str(tmp_path / "conll_empty")
        result = exporter.export(ctx, output_dir)

        assert result.success
        out_file = os.path.join(output_dir, "annotations.conll")
        with open(out_file) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("-DOCSTART-")]
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 4:
                assert parts[-1] == "O"


class TestCVUtilsIntegration:
    """Test CV utility functions with edge cases."""

    def test_polygon_to_bbox_triangle(self):
        points = [[0, 0], [100, 0], [50, 80]]
        bbox = polygon_to_bbox(points)
        # Returns tuple (x_min, y_min, width, height)
        assert bbox == (0, 0, 100, 80)

    def test_normalize_bbox(self):
        result = normalize_bbox(100, 200, 50, 60, 1000, 800)
        assert result == pytest.approx((0.125, 0.2875, 0.05, 0.075))

    def test_polygon_area(self):
        area = polygon_area([[0, 0], [1, 0], [1, 1], [0, 1]])
        assert area == pytest.approx(1.0)

    def test_flatten_polygon(self):
        result = flatten_polygon([[10, 20], [30, 40]])
        assert result == [10, 20, 30, 40]

    def test_build_category_mapping(self):
        annotations = [
            {"image_annotations": {"det": [{"type": "bbox", "label": "cat"}, {"type": "bbox", "label": "dog"}]}}
        ]
        schemas = [{"annotation_type": "image_annotation", "name": "det",
                     "labels": [{"name": "cat"}, {"name": "dog"}]}]
        mapping = build_category_mapping(annotations, schemas)
        assert len(mapping) == 2
        assert "cat" in mapping
        assert "dog" in mapping


class TestNLPUtilsIntegration:
    """Test NLP utilities with edge cases."""

    def test_tokenize_whitespace_preserves_punctuation(self):
        """Default whitespace tokenizer keeps punctuation attached."""
        tokens = tokenize_text("Hello, world!")
        token_texts = [t["token"] for t in tokens]
        assert "Hello," in token_texts  # whitespace mode keeps comma attached
        assert "world!" in token_texts

    def test_tokenize_word_punct_splits_punctuation(self):
        """Word_punct tokenizer splits punctuation."""
        tokens = tokenize_text("Hello, world!", method="word_punct")
        token_texts = [t["token"] for t in tokens]
        assert "Hello" in token_texts
        assert "," in token_texts

    def test_bio_tags_overlapping_spans(self):
        tokens = tokenize_text("New York City is beautiful")
        spans = [
            {"start": 0, "end": 13, "label": "LOC"},
            {"start": 0, "end": 8, "label": "CITY"},
        ]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags[0] == "B-LOC"

    def test_bio_tags_multi_token_entity(self):
        tokens = tokenize_text("San Francisco is nice")
        spans = [{"start": 0, "end": 13, "label": "LOC"}]
        tags = char_spans_to_bio_tags(tokens, spans)
        assert tags[0] == "B-LOC"
        assert tags[1] == "I-LOC"

    def test_group_sentences_basic(self):
        text = "Hello world. How are you?"
        tokens = tokenize_text(text)
        groups = group_sentences(tokens, text)
        assert len(groups) == 2
