"""
Tests for YOLO exporter.
"""

import os
import pytest
import tempfile

from potato.export.base import ExportContext
from potato.export.yolo_exporter import YOLOExporter


class TestYOLOExporter:
    def setup_method(self):
        self.exporter = YOLOExporter()

    def _make_context(self, annotations=None, items=None, schemas=None):
        return ExportContext(
            config={},
            annotations=annotations or [],
            items=items or {},
            schemas=schemas or [{"annotation_type": "image_annotation", "name": "img",
                                 "labels": [{"name": "cat"}, {"name": "dog"}]}],
            output_dir="",
        )

    def test_can_export_with_dims(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {"img": [{"type": "bbox", "label": "cat",
                                           "x": 10, "y": 20, "width": 100, "height": 50}]}
        }]
        items = {"img1": {"image_width": 640, "image_height": 480}}
        ctx = self._make_context(annotations=annotations, items=items)
        can, reason = self.exporter.can_export(ctx)
        assert can

    def test_can_export_without_dims(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {"img": [{"type": "bbox", "label": "cat",
                                           "x": 10, "y": 20, "width": 100, "height": 50}]}
        }]
        items = {"img1": {"image": "test.jpg"}}
        ctx = self._make_context(annotations=annotations, items=items)
        can, reason = self.exporter.can_export(ctx)
        assert not can
        assert "dimensions" in reason

    def test_export_bbox_normalized(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [{"type": "bbox", "label": "cat", "x": 100, "y": 100, "width": 200, "height": 100}]
            }
        }]
        items = {"img1": {"image": "cat.jpg", "image_width": 1000, "image_height": 500}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success

            # Check label file
            label_file = os.path.join(tmpdir, "labels", "cat.txt")
            assert os.path.exists(label_file)
            with open(label_file) as f:
                lines = f.read().strip().split("\n")
            assert len(lines) == 1
            parts = lines[0].split()
            assert parts[0] == "0"  # class_id for "cat"
            # cx = (100 + 100) / 1000 = 0.2, cy = (100 + 50) / 500 = 0.3
            # w = 200/1000 = 0.2, h = 100/500 = 0.2
            assert float(parts[1]) == pytest.approx(0.2, abs=0.001)
            assert float(parts[2]) == pytest.approx(0.3, abs=0.001)
            assert float(parts[3]) == pytest.approx(0.2, abs=0.001)
            assert float(parts[4]) == pytest.approx(0.2, abs=0.001)

            # Check classes.txt
            classes_file = os.path.join(tmpdir, "classes.txt")
            assert os.path.exists(classes_file)
            with open(classes_file) as f:
                classes = f.read().strip().split("\n")
            assert classes == ["cat", "dog"]

            # Check data.yaml
            data_yaml = os.path.join(tmpdir, "data.yaml")
            assert os.path.exists(data_yaml)

    def test_export_polygon_converted_to_bbox(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [{"type": "polygon", "label": "cat",
                         "points": [[100, 100], [300, 100], [300, 200], [100, 200]]}]
            }
        }]
        items = {"img1": {"image": "test.jpg", "image_width": 1000, "image_height": 500}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert any("converted to enclosing bbox" in w for w in result.warnings)

    def test_export_landmark_skipped(self):
        annotations = [{
            "instance_id": "img1", "user_id": "u1",
            "image_annotations": {
                "img": [{"type": "landmark", "label": "cat", "x": 50, "y": 60}]
            }
        }]
        items = {"img1": {"image": "test.jpg", "image_width": 100, "image_height": 100}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_annotations"] == 0
