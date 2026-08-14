"""
COCO's two remaining gaps: open paths and panoptic output.

Both are places where the obvious implementation is wrong in a way that still
produces a valid-looking file:

* Closing a polyline into a polygon yields a real `segmentation` that every
  downstream tool reads as a filled region. A lane marking becomes a road.
* Writing the panoptic PNG as an indexed image renders identically and caps
  segment ids at 255, silently merging segments in any busy scene.
"""

from __future__ import annotations

import json

import pytest

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter

W, H = 200, 100


def context(objects, tmp_path, labels=("lane", "car")):
    return ExportContext(
        config={"annotation_task_name": "coco"},
        schemas=[{
            "annotation_type": "image_annotation", "name": "objects",
            "labels": [{"name": n} for n in labels],
        }],
        annotations=[{"instance_id": "img_1",
                      "image_annotations": {"objects": objects}}],
        items={"img_1": {"image_width": W, "image_height": H,
                         "file_name": "img_1.jpg"}},
        output_dir=str(tmp_path),
    )


def polyline(label="lane"):
    return {"type": "polyline", "label": label, "closed": False,
            "coordinates": [{"x": 0.0, "y": 0.5}, {"x": 0.5, "y": 0.25},
                            {"x": 1.0, "y": 0.1}]}


def ellipse(label="car"):
    return {"type": "ellipse", "label": label,
            "coordinates": {"cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.1,
                            "angle": 0.0}}


def box(x=0.1, y=0.1, w=0.2, h=0.2, label="car"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def read(tmp_path, name="annotations.json"):
    with open(tmp_path / name) as fh:
        return json.load(fh)


class TestPolylines:
    def test_a_polyline_is_exported_at_all(self, tmp_path):
        """It used to fall through to 'unknown annotation type' and vanish."""
        result = COCOExporter().export(context([polyline()], tmp_path),
                                       str(tmp_path))
        assert result.success
        assert len(read(tmp_path)["annotations"]) == 1

    def test_it_is_not_closed_into_a_filled_region(self, tmp_path):
        COCOExporter().export(context([polyline()], tmp_path), str(tmp_path))
        ann = read(tmp_path)["annotations"][0]
        assert ann["segmentation"] == [], (
            "a closed segmentation makes every lane marking a filled region")
        assert ann["area"] == 0

    def test_the_points_survive_under_an_extension_key(self, tmp_path):
        COCOExporter().export(context([polyline()], tmp_path), str(tmp_path))
        ann = read(tmp_path)["annotations"][0]
        assert len(ann["polyline"]) == 6, "3 points as a flat x,y stream"
        assert ann["polyline"][0] == 0.0
        assert ann["polyline"][1] == pytest.approx(H * 0.5)

    def test_it_still_carries_a_bounding_box(self, tmp_path):
        """So detection tooling that ignores the extension key still works."""
        COCOExporter().export(context([polyline()], tmp_path), str(tmp_path))
        ann = read(tmp_path)["annotations"][0]
        assert ann["bbox"][2] > 0 and ann["bbox"][3] > 0

    def test_the_loss_is_reported(self, tmp_path):
        result = COCOExporter().export(context([polyline()], tmp_path),
                                       str(tmp_path))
        assert any("polyline" in w for w in result.warnings)


class TestEllipses:
    def test_an_ellipse_becomes_a_real_polygon(self, tmp_path):
        COCOExporter().export(context([ellipse()], tmp_path), str(tmp_path))
        ann = read(tmp_path)["annotations"][0]
        assert ann["segmentation"] and len(ann["segmentation"][0]) >= 6
        assert ann["area"] > 0

    def test_the_parametric_form_is_kept(self, tmp_path):
        COCOExporter().export(context([ellipse()], tmp_path), str(tmp_path))
        ann = read(tmp_path)["annotations"][0]
        assert ann["ellipse"]["rx"] == pytest.approx(0.2 * W)


class TestPanoptic:
    def test_it_is_off_by_default(self, tmp_path):
        result = COCOExporter().export(context([box()], tmp_path),
                                       str(tmp_path))
        assert not (tmp_path / "panoptic.json").exists()
        assert len(result.files_written) == 1

    def test_it_writes_a_png_and_a_segments_json(self, tmp_path):
        pytest.importorskip("PIL")
        result = COCOExporter().export(context([box()], tmp_path),
                                       str(tmp_path), {"panoptic": True})
        assert (tmp_path / "panoptic.json").exists()
        assert (tmp_path / "panoptic" / "img_1.png").exists()
        assert len(result.files_written) == 3

    def test_the_png_is_rgb_with_the_id_in_the_channels(self, tmp_path):
        """
        id = R + G*256 + B*256^2. An indexed save renders the same and caps
        ids at 255, which silently merges segments in any busy scene.
        """
        pytest.importorskip("PIL")
        from PIL import Image

        COCOExporter().export(context([box()], tmp_path), str(tmp_path),
                              {"panoptic": True})
        with Image.open(tmp_path / "panoptic" / "img_1.png") as img:
            assert img.mode == "RGB"
            colours = {c for _n, c in img.getcolors(maxcolors=1 << 20)}

        segments = read(tmp_path, "panoptic.json")["annotations"][0]["segments_info"]
        segment_id = segments[0]["id"]
        expected = (segment_id % 256, (segment_id // 256) % 256,
                    (segment_id // 65536) % 256)
        assert expected in colours
        assert (0, 0, 0) in colours, "unlabelled pixels must be segment 0"

    def test_segments_info_records_real_areas(self, tmp_path):
        pytest.importorskip("PIL")
        COCOExporter().export(context([box(0.0, 0.0, 0.5, 0.5)], tmp_path),
                              str(tmp_path), {"panoptic": True})
        segment = read(tmp_path, "panoptic.json")["annotations"][0]["segments_info"][0]
        # Half the width by half the height.
        assert segment["area"] == pytest.approx((W // 2) * (H // 2), rel=0.05)

    def test_overlap_is_reported_because_panoptic_cannot_express_it(self, tmp_path):
        pytest.importorskip("PIL")
        objects = [box(0.0, 0.0, 0.5, 0.5), box(0.2, 0.2, 0.5, 0.5)]
        result = COCOExporter().export(context(objects, tmp_path),
                                       str(tmp_path), {"panoptic": True})
        assert any("overlap" in w.lower() for w in result.warnings)

    def test_the_detection_json_keeps_overlapping_annotations(self, tmp_path):
        pytest.importorskip("PIL")
        objects = [box(0.0, 0.0, 0.5, 0.5), box(0.2, 0.2, 0.5, 0.5)]
        COCOExporter().export(context(objects, tmp_path), str(tmp_path),
                              {"panoptic": True})
        assert len(read(tmp_path)["annotations"]) == 2

    def test_a_polyline_claims_no_pixels(self, tmp_path):
        """An open path has no interior to paint."""
        pytest.importorskip("PIL")
        from PIL import Image

        COCOExporter().export(context([polyline()], tmp_path), str(tmp_path),
                              {"panoptic": True})
        with Image.open(tmp_path / "panoptic" / "img_1.png") as img:
            colours = {c for _n, c in img.getcolors(maxcolors=1 << 20)}
        assert colours == {(0, 0, 0)}
