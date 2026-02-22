"""
Tests for Pascal VOC XML exporter.
"""

import os
import pytest
import tempfile
import xml.etree.ElementTree as ET

from potato.export.base import ExportContext
from potato.export.pascal_voc_exporter import PascalVOCExporter


class TestPascalVOCExporter:
    def setup_method(self):
        self.exporter = PascalVOCExporter()

    def _make_context(self, annotations=None, items=None, schemas=None):
        return ExportContext(
            config={},
            annotations=annotations or [],
            items=items or {},
            schemas=schemas or [{"annotation_type": "image_annotation", "name": "img",
                                 "labels": [{"name": "cat"}, {"name": "dog"}]}],
            output_dir="",
        )

    def test_can_export_with_image_schema(self):
        ctx = self._make_context()
        can, reason = self.exporter.can_export(ctx)
        assert can

    def test_can_export_without_image_schema(self):
        ctx = self._make_context(schemas=[{"annotation_type": "span", "name": "ner"}])
        can, reason = self.exporter.can_export(ctx)
        assert not can

    def test_export_bbox(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [
                    {"type": "bbox", "label": "cat", "x": 10, "y": 20, "width": 100, "height": 50},
                ]
            }
        }]
        items = {"img1": {"image": "cat.jpg", "image_width": 640, "image_height": 480}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success

            xml_file = os.path.join(tmpdir, "cat.xml")
            assert os.path.exists(xml_file)

            tree = ET.parse(xml_file)
            root = tree.getroot()

            assert root.tag == "annotation"
            assert root.find("filename").text == "cat.jpg"
            assert root.find("size/width").text == "640"
            assert root.find("size/height").text == "480"

            objects = root.findall("object")
            assert len(objects) == 1
            assert objects[0].find("name").text == "cat"
            bndbox = objects[0].find("bndbox")
            assert bndbox.find("xmin").text == "10"
            assert bndbox.find("ymin").text == "20"
            assert bndbox.find("xmax").text == "110"
            assert bndbox.find("ymax").text == "70"

    def test_export_polygon_converted(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [
                    {"type": "polygon", "label": "dog",
                     "points": [[10, 10], [110, 10], [110, 60], [10, 60]]},
                ]
            }
        }]
        items = {"img1": {"image": "dog.png", "image_width": 200, "image_height": 200}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert any("converted to enclosing bbox" in w for w in result.warnings)

            tree = ET.parse(os.path.join(tmpdir, "dog.xml"))
            bndbox = tree.find(".//bndbox")
            assert bndbox.find("xmin").text == "10"
            assert bndbox.find("ymin").text == "10"
            assert bndbox.find("xmax").text == "110"
            assert bndbox.find("ymax").text == "60"

    def test_export_multiple_objects(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [
                    {"type": "bbox", "label": "cat", "x": 0, "y": 0, "width": 50, "height": 50},
                    {"type": "bbox", "label": "dog", "x": 100, "y": 100, "width": 60, "height": 60},
                ]
            }
        }]
        items = {"img1": {"image": "multi.jpg", "image_width": 640, "image_height": 480}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_objects"] == 2

            tree = ET.parse(os.path.join(tmpdir, "multi.xml"))
            objects = tree.findall(".//object")
            assert len(objects) == 2

    def test_export_landmark_skipped(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [{"type": "landmark", "label": "cat", "x": 50, "y": 60}]
            }
        }]
        items = {"img1": {"image": "test.jpg"}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert any("Landmark" in w for w in result.warnings)
