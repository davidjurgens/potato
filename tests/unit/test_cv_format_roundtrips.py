"""
Round trips for the autonomous-driving and video-segmentation formats.

Each of KITTI, MOT, Cityscapes, DAVIS and Darwin now has both halves, so the
whole loop is exercised: import -> Potato -> export -> import. A one-sided test
cannot catch the failure mode these formats are most prone to — the importer
and exporter agreeing on a *wrong* convention, which closes the loop cleanly
while producing a file the real tool misreads. So alongside each round trip
there is an assertion about the bytes on disk:

* KITTI writes CORNERS; MOT writes ORIGIN+SIZE. They sit next to each other in
  the same pipelines and the wrong one still looks like a box.
* DAVIS writes an INDEXED image whose pixel values are object ids. An RGB save
  renders identically and is unreadable as a mask.
* Cityscapes' object ORDER is its occlusion.
* Darwin emits exactly ONE shape key per annotation, because the key is the
  type.
"""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.cityscapes_exporter import CityscapesExporter
from potato.export.darwin_exporter import DarwinExporter
from potato.export.davis_exporter import DAVISExporter
from potato.export.kitti_exporter import KITTIExporter
from potato.export.mot_exporter import MOTExporter
from potato.export.registry import export_registry
from potato.importers.cityscapes_importer import CityscapesImporter
from potato.importers.darwin_importer import DarwinImporter
from potato.importers.kitti_importer import KITTIImporter
from potato.importers.mot_importer import MOTImporter
from potato.importers.registry import import_registry

W, H = 640, 480


def context(objects, tmp_path, items_extra=None):
    item = {"image_width": W, "image_height": H, "file_name": "img_1.jpg"}
    item.update(items_extra or {})
    return ExportContext(
        config={"annotation_task_name": "roundtrip"},
        schemas=[{
            "annotation_type": "image_annotation", "name": "objects",
            "labels": [{"name": "Car"}, {"name": "pedestrian"}],
        }],
        annotations=[{"instance_id": "img_1",
                      "image_annotations": {"objects": objects}}],
        items={"img_1": item},
        output_dir=str(tmp_path),
    )


def bbox(x=64.0, y=48.0, w=128.0, h=96.0, label="Car", **extra):
    obj = {"type": "bbox", "label": label,
           "coordinates": {"x": x / W, "y": y / H,
                           "width": w / W, "height": h / H}}
    obj.update(extra)
    return obj


def polygon(label="Car"):
    return {"type": "polygon", "label": label,
            "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1},
                            {"x": 0.5, "y": 0.5}]}


def close(a, b, tol=1.0):
    return abs(a - b) <= tol


class TestRegistration:
    @pytest.mark.parametrize(
        "fmt", ["kitti", "mot", "cityscapes", "davis", "darwin"])
    def test_both_halves_exist(self, fmt):
        assert import_registry.is_registered(fmt), f"{fmt} importer missing"
        assert export_registry.is_registered(fmt), f"{fmt} exporter missing"


class TestKITTI:
    def test_a_box_survives_the_loop(self, tmp_path):
        result = KITTIExporter().export(context([bbox()], tmp_path),
                                        str(tmp_path))
        assert result.success
        # The image has to be measurable for the importer to normalize.
        pytest.importorskip("PIL")
        from PIL import Image

        (tmp_path / "image_2").mkdir(exist_ok=True)
        Image.new("RGB", (W, H)).save(tmp_path / "image_2" / "img_1.png")

        back = KITTIImporter().parse_directory(str(tmp_path))
        obj = back.images[0].objects[0]
        c = obj["coordinates"]
        assert obj["label"] == "Car"
        assert close(c["x"] * W, 64.0)
        assert close(c["width"] * W, 128.0)

    def test_the_file_holds_corners_not_origin_plus_size(self, tmp_path):
        """
        The bug a round trip alone cannot catch: if both halves used
        origin+size the loop still closes, and every real KITTI tool reads the
        boxes as ending 64px from the left edge instead of 192.
        """
        KITTIExporter().export(context([bbox()], tmp_path), str(tmp_path))
        line = (tmp_path / "label_2" / "img_1.txt").read_text().split("\n")[0]
        fields = line.split()
        assert close(float(fields[4]), 64.0), "x1"
        assert close(float(fields[6]), 64.0 + 128.0), "x2 is not a corner"

    def test_absent_3d_is_written_as_the_devkit_sentinel(self, tmp_path):
        """Zeros would read as a real object sitting at the camera origin."""
        KITTIExporter().export(context([bbox()], tmp_path), str(tmp_path))
        fields = (tmp_path / "label_2" / "img_1.txt").read_text().split()
        assert float(fields[8]) == -1.0, "height should be the unset sentinel"
        assert float(fields[11]) == -1000.0, "location should be unset"

    def test_3d_attributes_survive_when_present(self, tmp_path):
        obj = bbox(attributes={"dimensions_hwl": [1.5, 1.6, 3.9],
                               "location_xyz": [1.8, 1.7, 8.4],
                               "rotation_y": -1.57, "truncated": 0.2})
        KITTIExporter().export(context([obj], tmp_path), str(tmp_path))
        fields = (tmp_path / "label_2" / "img_1.txt").read_text().split()
        assert close(float(fields[8]), 1.5, 0.01)
        assert close(float(fields[11]), 1.8, 0.01)
        assert close(float(fields[14]), -1.57, 0.01)

    def test_polygons_are_reported_not_dropped(self, tmp_path):
        result = KITTIExporter().export(context([polygon()], tmp_path),
                                        str(tmp_path))
        assert any("polygon" in w for w in result.warnings)


class TestMOT:
    def _export(self, tmp_path, objects, extra=None):
        ctx = context(objects, tmp_path,
                      items_extra=extra or {"sequence": "MOT17-02", "frame": 1})
        return MOTExporter().export(ctx, str(tmp_path))

    def test_a_track_survives_the_loop(self, tmp_path):
        obj = bbox(label="pedestrian", instance=7,
                   attributes={"track_id": 7, "visibility": 0.9})
        self._export(tmp_path, [obj])
        back = MOTImporter().parse_directory(str(tmp_path))
        restored = back.images[0].objects[0]
        assert restored["label"] == "pedestrian"
        assert restored["instance"] == 7
        assert close(restored["coordinates"]["x"] * W, 64.0)

    def test_the_file_holds_origin_plus_size_not_corners(self, tmp_path):
        """The opposite convention to the KITTI exporter beside it."""
        self._export(tmp_path, [bbox()])
        row = (tmp_path / "MOT17-02" / "gt" / "gt.txt").read_text().split(",")
        assert close(float(row[2]), 64.0), "bb_left"
        assert close(float(row[4]), 128.0), "bb_width is not a width"

    def test_frames_are_one_indexed(self, tmp_path):
        """Frame 0 is dropped by every MOT evaluator."""
        self._export(tmp_path, [bbox()], extra={"sequence": "s"})
        row = (tmp_path / "s" / "gt" / "gt.txt").read_text().split(",")
        assert int(row[0]) >= 1

    def test_ignore_becomes_conf_zero_and_confidence_does_not(self, tmp_path):
        """conf=0 means 'exclude from evaluation', not 'unconfident'."""
        objects = [bbox(attributes={"ignore": True, "track_id": 1}),
                   bbox(y=200.0, attributes={"confidence": 0.4, "track_id": 2})]
        self._export(tmp_path, objects)
        rows = [r for r in (tmp_path / "MOT17-02" / "gt" / "gt.txt")
                .read_text().splitlines() if r]
        by_id = {int(r.split(",")[1]): r.split(",")[6] for r in rows}
        assert by_id[1] == "0", "ignore should be conf 0"
        assert by_id[2] == "1", "a 0.4 confidence must not become an ignore region"

    def test_seqinfo_carries_the_image_size(self, tmp_path):
        self._export(tmp_path, [bbox()])
        parser = configparser.ConfigParser()
        parser.read(tmp_path / "MOT17-02" / "seqinfo.ini")
        assert int(parser["Sequence"]["imWidth"]) == W
        assert int(parser["Sequence"]["imHeight"]) == H

    def test_missing_track_ids_get_real_ones_not_minus_one(self, tmp_path):
        result = self._export(tmp_path, [bbox()])
        row = (tmp_path / "MOT17-02" / "gt" / "gt.txt").read_text().split(",")
        assert int(row[1]) > 0, "id -1 would make this a detection file"
        assert any("track id" in w for w in result.warnings)


class TestCityscapes:
    def test_a_polygon_survives_the_loop(self, tmp_path):
        result = CityscapesExporter().export(
            context([polygon(label="road")], tmp_path), str(tmp_path))
        assert result.success
        back = CityscapesImporter().parse_directory(str(tmp_path))
        obj = back.images[0].objects[0]
        assert obj["type"] == "polygon"
        assert obj["label"] == "road"

    def test_draw_order_is_preserved_because_it_is_the_occlusion(self, tmp_path):
        objects = [
            dict(polygon(label="car"), attributes={"draw_order": 2}),
            dict(polygon(label="road"), attributes={"draw_order": 0}),
            dict(polygon(label="sky"), attributes={"draw_order": 1}),
        ]
        CityscapesExporter().export(context(objects, tmp_path), str(tmp_path))
        written = json.loads(
            (tmp_path / "img_1_gtFine_polygons.json").read_text())
        assert [o["label"] for o in written["objects"]] == ["road", "sky", "car"]

    def test_a_box_becomes_four_corners(self, tmp_path):
        CityscapesExporter().export(context([bbox()], tmp_path), str(tmp_path))
        written = json.loads(
            (tmp_path / "img_1_gtFine_polygons.json").read_text())
        assert len(written["objects"][0]["polygon"]) == 4

    def test_the_suffix_does_not_accumulate_on_re_export(self, tmp_path):
        ctx = context([polygon()], tmp_path,
                      items_extra={"file_name": "aachen_000000_leftImg8bit.png"})
        CityscapesExporter().export(ctx, str(tmp_path))
        names = [p.name for p in tmp_path.glob("*.json")]
        assert names == ["aachen_000000_gtFine_polygons.json"]


class TestDAVIS:
    def test_a_mask_survives_as_indexed_pixels(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image

        obj = dict(polygon(label="bear"), instance=3)
        result = DAVISExporter().export(
            context([obj], tmp_path,
                    items_extra={"sequence": "bear", "frame": 0}),
            str(tmp_path))
        assert result.success, result.errors

        path = tmp_path / "Annotations" / "bear" / "00000.png"
        with Image.open(path) as img:
            assert img.mode == "P", (
                "an RGB save renders identically and is unreadable as a mask")
            values = set(img.getdata())
        assert 3 in values, "the pixel VALUE must be the object id"
        assert 0 in values, "background must be 0"

    def test_ids_are_stable_across_frames(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image

        ctx = ExportContext(
            config={}, schemas=[{"annotation_type": "image_annotation",
                                 "name": "objects", "labels": []}],
            annotations=[
                {"instance_id": "f0",
                 "image_annotations": {"objects": [dict(polygon(), instance=5)]}},
                {"instance_id": "f1",
                 "image_annotations": {"objects": [dict(polygon(), instance=5)]}},
            ],
            items={
                "f0": {"image_width": W, "image_height": H,
                       "sequence": "s", "frame": 0},
                "f1": {"image_width": W, "image_height": H,
                       "sequence": "s", "frame": 1},
            },
            output_dir=str(tmp_path))
        DAVISExporter().export(ctx, str(tmp_path))

        seen = []
        for frame in ("00000.png", "00001.png"):
            with Image.open(tmp_path / "Annotations" / "s" / frame) as img:
                seen.append({v for v in img.getdata() if v})
        assert seen[0] == seen[1] == {5}

    def test_objects_without_ids_are_reported(self, tmp_path):
        pytest.importorskip("PIL")
        result = DAVISExporter().export(
            context([polygon()], tmp_path,
                    items_extra={"sequence": "s", "frame": 0}),
            str(tmp_path))
        assert any("no instance or track id" in w for w in result.warnings)


class TestDarwin:
    def test_a_box_survives_the_loop(self, tmp_path):
        result = DarwinExporter().export(context([bbox()], tmp_path),
                                         str(tmp_path))
        assert result.success
        doc = json.loads((tmp_path / "img_1.json").read_text())
        back = DarwinImporter().parse(doc)
        obj = back.images[0].objects[0]
        assert obj["type"] == "bbox"
        assert close(obj["coordinates"]["x"] * W, 64.0)

    def test_exactly_one_shape_key_per_annotation(self, tmp_path):
        """Darwin has no `type` field: the key present IS the type."""
        DarwinExporter().export(context([bbox(), polygon()], tmp_path),
                                str(tmp_path))
        doc = json.loads((tmp_path / "img_1.json").read_text())
        shape_keys = {"bounding_box", "polygon", "complex_polygon", "ellipse",
                      "keypoint", "line", "tag", "raster_layer"}
        for entry in doc["annotations"]:
            present = shape_keys & set(entry)
            assert len(present) == 1, f"ambiguous annotation: {sorted(present)}"

    def test_dimensions_live_in_slots(self, tmp_path):
        DarwinExporter().export(context([bbox()], tmp_path), str(tmp_path))
        doc = json.loads((tmp_path / "img_1.json").read_text())
        assert doc["item"]["slots"][0]["width"] == W
        assert "width" not in doc["item"]

    def test_ids_are_stable_across_exports(self, tmp_path):
        """A re-export of unchanged work should diff as empty."""
        first = tmp_path / "a"
        second = tmp_path / "b"
        DarwinExporter().export(context([bbox()], first), str(first))
        DarwinExporter().export(context([bbox()], second), str(second))
        assert (first / "img_1.json").read_text() == \
               (second / "img_1.json").read_text()

    def test_masks_are_traced_and_reported(self, tmp_path):
        mask = {"type": "mask", "label": "Car",
                "rle": {"counts": [0, 100, W * H - 100], "size": [H, W]}}
        result = DarwinExporter().export(context([mask], tmp_path),
                                         str(tmp_path))
        assert any("raster_layer" in w for w in result.warnings)
        assert any("COCO" in w for w in result.warnings)


class TestPolygonRoundTripFidelity:
    """A polygon must come back where it started, not merely come back."""

    def test_cityscapes_preserves_vertices(self, tmp_path):
        CityscapesExporter().export(context([polygon()], tmp_path),
                                    str(tmp_path))
        back = CityscapesImporter().parse_directory(str(tmp_path))
        points = back.images[0].objects[0]["coordinates"]
        assert len(points) == 3
        assert close(points[0]["x"] * W, 0.1 * W, 0.5)
        assert close(points[1]["x"] * W, 0.5 * W, 0.5)
