"""
Tests for the mask PNG exporter.
"""

import os
import pytest
import tempfile

from potato.export.base import ExportContext
from potato.export.mask_exporter import MaskExporter
from potato.export.cv_utils import decode_rle as _decode_rle


class TestDecodeRLE:
    def test_basic_rle(self):
        rle = {"counts": [2, 3, 5], "size": [2, 5]}
        mask = _decode_rle(rle, 5, 2)
        # First 2 zeros, then 3 ones, then 5 zeros
        assert mask[:2] == [0, 0]
        assert mask[2:5] == [1, 1, 1]
        assert mask[5:10] == [0, 0, 0, 0, 0]

    def test_empty_rle(self):
        rle = {"counts": [], "size": [1, 1]}
        mask = _decode_rle(rle, 1, 1)
        assert mask == [0]

    def test_all_ones(self):
        rle = {"counts": [0, 4], "size": [2, 2]}
        mask = _decode_rle(rle, 2, 2)
        assert mask == [1, 1, 1, 1]

    def test_all_zeros(self):
        rle = {"counts": [4], "size": [2, 2]}
        mask = _decode_rle(rle, 2, 2)
        assert mask == [0, 0, 0, 0]


class TestMaskExporter:
    def setup_method(self):
        self.exporter = MaskExporter()

    def _make_context(self, annotations=None, items=None, schemas=None):
        return ExportContext(
            config={},
            annotations=annotations or [],
            items=items or {},
            schemas=schemas or [{"annotation_type": "image_annotation", "name": "img",
                                 "labels": [{"name": "road"}, {"name": "sky"}]}],
            output_dir="",
        )

    def test_can_export_requires_pillow(self):
        ctx = self._make_context()
        can, reason = self.exporter.can_export(ctx)
        # This will pass if Pillow is installed, fail if not
        try:
            from PIL import Image
            assert can
        except ImportError:
            assert not can
            assert "Pillow" in reason

    def test_can_export_requires_image_schema(self):
        ctx = self._make_context(schemas=[{"annotation_type": "span", "name": "ner"}])
        can, reason = self.exporter.can_export(ctx)
        assert not can

    def test_export_mask(self):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        annotations = [{
            "instance_id": "img1",
            "user_id": "u1",
            "image_annotations": {
                "img": [{
                    "type": "mask",
                    "label": "road",
                    "rle": {"counts": [5, 10, 5], "size": [4, 5]}
                }]
            }
        }]
        items = {"img1": {"image": "scene.jpg", "image_width": 5, "image_height": 4}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_masks"] == 1
            assert len(result.files_written) == 1

            # Verify the PNG was created
            mask_file = result.files_written[0]
            assert os.path.exists(mask_file)
            assert mask_file.endswith("_road_mask.png")

            # Verify it's a valid image
            img = Image.open(mask_file)
            assert img.size == (5, 4)
            assert img.mode == "RGBA"

    def test_export_skips_non_mask_annotations(self):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        annotations = [{
            "instance_id": "img1",
            "user_id": "u1",
            "image_annotations": {
                "img": [
                    {"type": "bbox", "label": "car", "x": 0, "y": 0, "width": 10, "height": 10},
                    {"type": "mask", "label": "road", "rle": {"counts": [0, 4], "size": [2, 2]}},
                ]
            }
        }]
        items = {"img1": {"image": "test.jpg", "image_width": 2, "image_height": 2}}
        ctx = self._make_context(annotations=annotations, items=items)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.exporter.export(ctx, tmpdir)
            assert result.success
            assert result.stats["num_masks"] == 1  # Only the mask, not the bbox
