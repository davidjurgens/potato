"""
Tests for COCO JSON exporter.
"""

import json
import os
import pytest
import tempfile

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter


class TestCOCOExporter:
    def setup_method(self):
        self.exporter = COCOExporter()

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
        ctx = self._make_context(schemas=[{"annotation_type": "radio", "name": "q1"}])
        can, reason = self.exporter.can_export(ctx)
        assert not can
        assert "image_annotation" in reason

    def test_export_bbox(self):
        annotations = [{
            "instance_id": "img1",
            "user_id": "user1",
            "image_annotations": {
                "img": [
                    {"type": "bbox", "label": "cat", "x": 10, "y": 20, "width": 100, "height": 50},
                    {"type": "bbox", "label": "dog", "x": 50, "y": 60, "width": 80, "height": 40},
                ]
            }
        }]
        items = {"img1": {"image": "cat.jpg", "image_width": 640, "image_height": 480}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_images"] == 1
            assert result.stats["num_annotations"] == 2
            assert result.stats["num_categories"] == 2

            out_file = os.path.join(tmpdir, "annotations.json")
            assert os.path.exists(out_file)

            with open(out_file) as f:
                coco = json.load(f)

            assert len(coco["images"]) == 1
            assert coco["images"][0]["file_name"] == "cat.jpg"
            assert coco["images"][0]["width"] == 640

            assert len(coco["annotations"]) == 2
            assert coco["annotations"][0]["bbox"] == [10, 20, 100, 50]
            assert coco["annotations"][0]["area"] == 100 * 50
            assert coco["annotations"][0]["category_id"] == 1  # cat = 1 (1-indexed)

            assert len(coco["categories"]) == 2
            assert coco["categories"][0]["name"] == "cat"

    def test_export_polygon(self):
        annotations = [{
            "instance_id": "img1",
            "user_id": "user1",
            "image_annotations": {
                "img": [
                    {"type": "polygon", "label": "cat",
                     "points": [[10, 10], [100, 10], [100, 80], [10, 80]]},
                ]
            }
        }]
        items = {"img1": {"image": "test.jpg", "image_width": 640, "image_height": 480}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success

            with open(os.path.join(tmpdir, "annotations.json")) as f:
                coco = json.load(f)

            ann = coco["annotations"][0]
            assert ann["segmentation"] == [[10, 10, 100, 10, 100, 80, 10, 80]]
            assert ann["bbox"] == [10, 10, 90, 70]

    def test_export_landmark_skipped(self):
        annotations = [{
            "instance_id": "img1",
            "user_id": "user1",
            "image_annotations": {
                "img": [
                    {"type": "landmark", "label": "cat", "x": 50, "y": 60},
                ]
            }
        }]
        items = {"img1": {"image": "test.jpg"}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_annotations"] == 0
            assert any("Landmark" in w for w in result.warnings)

    def test_export_deduplicates_images(self):
        """Multiple annotations for same instance should share one image entry."""
        annotations = [
            {
                "instance_id": "img1", "user_id": "user1",
                "image_annotations": {"img": [{"type": "bbox", "label": "cat", "x": 0, "y": 0, "width": 10, "height": 10}]}
            },
            {
                "instance_id": "img1", "user_id": "user2",
                "image_annotations": {"img": [{"type": "bbox", "label": "dog", "x": 20, "y": 20, "width": 30, "height": 30}]}
            },
        ]
        items = {"img1": {"image": "test.jpg", "image_width": 100, "image_height": 100}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_images"] == 1
            assert result.stats["num_annotations"] == 2

    def test_export_empty_annotations(self):
        ctx = self._make_context()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_images"] == 0
