"""
CVAT and LabelMe now round-trip: import -> Potato -> export -> import.

A converter is only trustworthy if what comes back out matches what went in, so
these tests run the *whole* loop rather than checking either half in isolation.
That also catches the class of bug both halves can share — if the importer and
exporter agree on a wrong convention (corners vs origin+size, say), a one-sided
test passes and the data is silently wrong in both directions.

Where a format genuinely cannot carry something, the loop is asserted to be
*honestly* lossy: the information is reported, not quietly mangled.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.cvat_exporter import CVATExporter
from potato.export.labelme_exporter import LabelMeExporter
from potato.export.registry import export_registry
from potato.importers.cvat_importer import CVATImporter
from potato.importers.labelme_importer import LabelMeImporter

W, H = 640, 480


def context(objects, tmp_path, labels=("car", "lane")):
    return ExportContext(
        config={"annotation_task_name": "roundtrip"},
        schemas=[{
            "annotation_type": "image_annotation", "name": "objects",
            "labels": [{"name": n, "color": "#e6194b"} for n in labels],
        }],
        annotations=[{"instance_id": "img_1",
                      "image_annotations": {"objects": objects}}],
        items={"img_1": {"image_width": W, "image_height": H,
                         "file_name": "img_1.jpg"}},
        output_dir=str(tmp_path),
    )


def bbox(x=0.1, y=0.1, w=0.4, h=0.4, label="car"):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def polyline(label="lane"):
    return {"type": "polyline", "label": label,
            "coordinates": [{"x": 0.0, "y": 0.5}, {"x": 0.5, "y": 0.25},
                            {"x": 1.0, "y": 0.1}]}


def polygon(label="car"):
    return {"type": "polygon", "label": label,
            "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1},
                            {"x": 0.5, "y": 0.5}]}


def ellipse(rx=0.1, ry=0.1, label="car"):
    return {"type": "ellipse", "label": label,
            "coordinates": {"cx": 0.5, "cy": 0.5, "rx": rx, "ry": ry,
                            "angle": 0.0}}


def roundtrip_cvat(objects, tmp_path):
    result = CVATExporter().export(context(objects, tmp_path), str(tmp_path))
    assert result.success, result.errors
    doc = ET.parse(result.files_written[0]).getroot()
    return CVATImporter().parse(doc), result


def roundtrip_labelme(objects, tmp_path):
    result = LabelMeExporter().export(context(objects, tmp_path), str(tmp_path))
    assert result.success, result.errors
    with open(result.files_written[0]) as fh:
        doc = json.load(fh)
    return LabelMeImporter().parse(doc), result


def close(a, b, tol=0.005):
    return abs(a - b) <= tol


class TestRegistration:
    @pytest.mark.parametrize("fmt", ["cvat", "labelme"])
    def test_exporter_is_registered(self, fmt):
        assert export_registry.is_registered(fmt)

    def test_both_directions_now_exist(self):
        """The matrix should no longer call these one-way."""
        from potato.importers.registry import import_registry

        for fmt in ("cvat", "labelme"):
            assert import_registry.is_registered(fmt)
            assert export_registry.is_registered(fmt)


class TestCVATRoundTrip:
    def test_a_box_survives(self, tmp_path):
        back, _ = roundtrip_cvat([bbox()], tmp_path)
        obj = back.images[0].objects[0]
        c = obj["coordinates"]
        assert obj["type"] == "bbox"
        assert close(c["x"], 0.1) and close(c["y"], 0.1)
        assert close(c["width"], 0.4) and close(c["height"], 0.4)

    def test_corners_are_written_not_origin_plus_size(self, tmp_path):
        """
        The bug a one-sided test cannot catch: if BOTH halves used origin+size
        the loop would still close, but the file would be wrong for CVAT.
        """
        result = CVATExporter().export(context([bbox()], tmp_path), str(tmp_path))
        box = ET.parse(result.files_written[0]).getroot().find(".//box")
        assert close(float(box.get("xtl")), 0.1 * W, 1)
        assert close(float(box.get("xbr")), 0.5 * W, 1), "xbr is not a corner"

    def test_a_polyline_stays_open(self, tmp_path):
        back, _ = roundtrip_cvat([polyline()], tmp_path)
        obj = back.images[0].objects[0]
        assert obj["type"] == "polyline"
        assert len(obj["coordinates"]) == 3

    def test_a_polygon_survives(self, tmp_path):
        back, _ = roundtrip_cvat([polygon()], tmp_path)
        assert back.images[0].objects[0]["type"] == "polygon"

    def test_an_ellipse_keeps_its_radii(self, tmp_path):
        back, _ = roundtrip_cvat([ellipse(rx=0.1, ry=0.05)], tmp_path)
        obj = back.images[0].objects[0]
        assert obj["type"] == "ellipse"
        assert close(obj["coordinates"]["rx"], 0.1)
        assert close(obj["coordinates"]["ry"], 0.05)

    def test_several_shapes_at_once(self, tmp_path):
        back, _ = roundtrip_cvat([bbox(), polyline(), polygon()], tmp_path)
        types = sorted(o["type"] for o in back.images[0].objects)
        assert types == ["bbox", "polygon", "polyline"]

    def test_label_colours_survive(self, tmp_path):
        back, _ = roundtrip_cvat([bbox()], tmp_path)
        assert back.labels[0]["color"] == "#e6194b"

    def test_attributes_survive(self, tmp_path):
        obj = bbox()
        obj["attributes"] = {"model": "sedan"}
        back, _ = roundtrip_cvat([obj], tmp_path)
        assert back.images[0].objects[0]["attributes"] == {"model": "sedan"}

    def test_masks_are_reported_not_silently_dropped(self, tmp_path):
        mask = {"type": "mask", "label": "car",
                "rle": {"counts": [0, 5, 95], "size": [H, W]}}
        _back, result = roundtrip_cvat([mask], tmp_path)
        assert any("mask" in w.lower() for w in result.warnings)
        # And it says what to do instead.
        assert any("COCO" in w for w in result.warnings)


class TestLabelMeRoundTrip:
    def test_a_box_survives(self, tmp_path):
        back, _ = roundtrip_labelme([bbox()], tmp_path)
        obj = back.images[0].objects[0]
        c = obj["coordinates"]
        assert obj["type"] == "bbox"
        assert close(c["x"], 0.1) and close(c["width"], 0.4)

    def test_a_rectangle_is_written_as_two_corners(self, tmp_path):
        result = LabelMeExporter().export(context([bbox()], tmp_path), str(tmp_path))
        with open(result.files_written[0]) as fh:
            shape = json.load(fh)["shapes"][0]
        assert shape["shape_type"] == "rectangle"
        assert len(shape["points"]) == 2, "a rectangle is TWO opposite corners"

    def test_a_circle_survives_as_an_ellipse(self, tmp_path):
        back, _ = roundtrip_labelme([ellipse(rx=0.1, ry=0.1 * W / H)], tmp_path)
        obj = back.images[0].objects[0]
        assert obj["type"] == "ellipse"

    def test_a_non_circular_ellipse_is_reported_not_squashed(self, tmp_path):
        """LabelMe's circle has ONE radius; writing it as a circle would
        silently change the shape."""
        _back, result = roundtrip_labelme([ellipse(rx=0.2, ry=0.02)], tmp_path)
        assert any("Non-circular" in w for w in result.warnings)

    def test_a_polyline_survives(self, tmp_path):
        back, _ = roundtrip_labelme([polyline()], tmp_path)
        assert back.images[0].objects[0]["type"] == "polyline"

    def test_group_id_carries_the_instance(self, tmp_path):
        obj = bbox()
        obj["instance"] = 3
        back, _ = roundtrip_labelme([obj], tmp_path)
        assert back.images[0].objects[0]["instance"] == 3

    def test_image_data_is_null_not_inlined(self, tmp_path):
        """Inlining base64 would multiply the export by the size of the corpus."""
        result = LabelMeExporter().export(context([bbox()], tmp_path), str(tmp_path))
        with open(result.files_written[0]) as fh:
            doc = json.load(fh)
        assert "imageData" in doc and doc["imageData"] is None

    def test_the_file_declares_a_labelme_version(self, tmp_path):
        result = LabelMeExporter().export(context([bbox()], tmp_path), str(tmp_path))
        with open(result.files_written[0]) as fh:
            assert json.load(fh)["version"]

    def test_masks_are_reported(self, tmp_path):
        mask = {"type": "mask", "label": "car",
                "rle": {"counts": [0, 5, 95], "size": [H, W]}}
        _back, result = roundtrip_labelme([mask], tmp_path)
        assert any("outlines, not pixels" in w for w in result.warnings)


class TestHonestLossiness:
    """Where a format cannot carry something, the loop must SAY so."""

    def test_cvat_reports_dropped_keypoint_visibility(self, tmp_path):
        kp = {"type": "keypoint_set", "label": "car", "skeleton": "s",
              "coordinates": [{"x": 0.1, "y": 0.1, "v": 2},
                              {"x": 0.2, "y": 0.2, "v": 0}]}
        _back, result = roundtrip_cvat([kp], tmp_path)
        assert any("visibility" in w for w in result.warnings)

    def test_cvat_does_not_write_unlabelled_points_at_the_origin(self, tmp_path):
        """
        An unlabelled joint is stored (0, 0, 0). Writing it out would read back
        as a real point in the image's top-left corner.
        """
        kp = {"type": "keypoint_set", "label": "car", "skeleton": "s",
              "coordinates": [{"x": 0.5, "y": 0.5, "v": 2},
                              {"x": 0.0, "y": 0.0, "v": 0}]}
        result = CVATExporter().export(context([kp], tmp_path), str(tmp_path))
        points = ET.parse(result.files_written[0]).getroot().find(".//points")
        assert len(points.get("points").split(";")) == 1

    def test_labelme_reports_lost_joint_identity(self, tmp_path):
        kp = {"type": "keypoint_set", "label": "car", "skeleton": "s",
              "coordinates": [{"x": 0.1, "y": 0.1, "v": 2},
                              {"x": 0.2, "y": 0.2, "v": 2}]}
        _back, result = roundtrip_labelme([kp], tmp_path)
        assert any("which point is which" in w for w in result.warnings)


class TestOutputIsWellFormed:
    def test_cvat_output_is_detected_as_cvat(self, tmp_path):
        result = CVATExporter().export(context([bbox()], tmp_path), str(tmp_path))
        doc = ET.parse(result.files_written[0]).getroot()
        assert CVATImporter().detect(doc)

    def test_labelme_output_is_detected_as_labelme(self, tmp_path):
        result = LabelMeExporter().export(context([bbox()], tmp_path), str(tmp_path))
        with open(result.files_written[0]) as fh:
            assert LabelMeImporter().detect(json.load(fh))

    def test_labelme_writes_one_file_per_image(self, tmp_path):
        result = LabelMeExporter().export(context([bbox()], tmp_path), str(tmp_path))
        assert len(result.files_written) == 1
        assert Path(result.files_written[0]).name == "img_1.json"

    def test_cvat_writes_a_single_annotations_xml(self, tmp_path):
        result = CVATExporter().export(context([bbox()], tmp_path), str(tmp_path))
        assert Path(result.files_written[0]).name == "annotations.xml"
