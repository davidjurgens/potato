"""
YOLO, Pascal VOC and LabelMe importers.

Each of these formats has a coordinate convention that produces a *plausible*
wrong answer when misread, which is the dangerous kind:

* YOLO boxes are **centre**-based (``cx cy w h``). Read as ``x y w h`` every box
  shifts by half its own size — still on the object, just off.
* VOC boxes are **corners** (``xmin ymin xmax ymax``). Read ``xmax`` as a width
  and the box starts correctly and runs far too far.
* LabelMe rectangles are **two opposite corners**, and circles are a centre plus
  a rim point. Read either as a generic polygon and you get a shape with no area.

So every geometry test here asserts an exact expected position, not merely that
something was imported.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from potato.export.cv_utils import normalize_annotation_object
from potato.importers.registry import import_registry
from potato.importers.labelme_importer import LabelMeImporter
from potato.importers.voc_importer import VOCImporter
from potato.importers.yolo_importer import YOLOImporter

W, H = 1000, 1000


def only_object(result):
    assert len(result.images) == 1, result.images
    assert len(result.images[0].objects) == 1, result.images[0].objects
    return result.images[0].objects[0]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    @pytest.mark.parametrize("fmt", ["coco", "pascal_voc", "yolo", "labelme"])
    def test_format_is_registered(self, fmt):
        assert import_registry.get(fmt) is not None

    def test_each_declares_metadata(self):
        for fmt in ("pascal_voc", "yolo", "labelme"):
            info = import_registry.get(fmt).get_format_info()
            assert info["description"].strip()
            assert info["file_extensions"]


# ---------------------------------------------------------------------------
# YOLO
# ---------------------------------------------------------------------------

def yolo_dataset(tmp_path, lines, names=("cat", "dog")):
    root = tmp_path / "ds"
    (root / "labels").mkdir(parents=True)
    (root / "images").mkdir(parents=True)
    (root / "labels" / "img1.txt").write_text("\n".join(lines))
    (root / "data.yaml").write_text(
        "names:\n" + "".join(f"  - {n}\n" for n in names))
    return root


class TestYOLO:
    def test_boxes_are_centre_based(self, tmp_path):
        """cx=0.5 cy=0.5 w=0.2 h=0.4 -> top-left at (0.4, 0.3)."""
        root = yolo_dataset(tmp_path, ["0 0.5 0.5 0.2 0.4"])
        obj = only_object(YOLOImporter().parse_directory(str(root)))

        assert obj["type"] == "bbox"
        c = obj["coordinates"]
        assert c["x"] == pytest.approx(0.4)
        assert c["y"] == pytest.approx(0.3)
        assert c["width"] == pytest.approx(0.2)
        assert c["height"] == pytest.approx(0.4)

    def test_a_centred_box_is_not_placed_at_the_centre(self, tmp_path):
        """The specific misreading this convention invites."""
        root = yolo_dataset(tmp_path, ["0 0.5 0.5 0.2 0.2"])
        c = only_object(YOLOImporter().parse_directory(str(root)))["coordinates"]
        assert c["x"] != pytest.approx(0.5), "read cx as the left edge"

    def test_class_indices_resolve_through_data_yaml(self, tmp_path):
        root = yolo_dataset(tmp_path, ["1 0.5 0.5 0.2 0.2"], names=("cat", "dog"))
        obj = only_object(YOLOImporter().parse_directory(str(root)))
        assert obj["label"] == "dog"

    def test_a_missing_data_yaml_warns_rather_than_silently_degrading(self, tmp_path):
        root = tmp_path / "ds"
        (root / "labels").mkdir(parents=True)
        (root / "labels" / "img1.txt").write_text("0 0.5 0.5 0.2 0.2")

        result = YOLOImporter().parse_directory(str(root))
        obj = only_object(result)
        assert obj["label"] == "class_0"
        assert any("data.yaml" in w for w in result.warnings)

    def test_segmentation_lines_become_polygons(self, tmp_path):
        root = yolo_dataset(tmp_path, ["0 0.1 0.1 0.5 0.1 0.5 0.5 0.1 0.5"])
        obj = only_object(YOLOImporter().parse_directory(str(root)))
        assert obj["type"] == "polygon"
        assert len(obj["coordinates"]) == 4

    def test_only_used_classes_reach_the_config(self, tmp_path):
        """Not 80 unused COCO names because data.yaml happened to list them."""
        root = yolo_dataset(tmp_path, ["1 0.5 0.5 0.2 0.2"],
                            names=("cat", "dog", "bird", "fish"))
        result = YOLOImporter().parse_directory(str(root))
        assert [l["name"] for l in result.labels] == ["dog"]

    def test_malformed_lines_are_reported_not_dropped_silently(self, tmp_path):
        root = yolo_dataset(tmp_path, ["0 0.5 0.5", "0 0.5 0.5 0.2 0.2"])
        result = YOLOImporter().parse_directory(str(root))
        assert len(result.images[0].objects) == 1
        assert any("5 fields" in w for w in result.warnings)

    def test_a_directory_with_no_labels_is_an_actionable_error(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(ValueError, match="labels"):
            YOLOImporter().parse_directory(str(tmp_path / "empty"))

    def test_tools_are_derived_from_the_content(self, tmp_path):
        root = yolo_dataset(tmp_path, ["0 0.5 0.5 0.2 0.2"])
        assert YOLOImporter().parse_directory(str(root)).tools == ["bbox"]


# ---------------------------------------------------------------------------
# Pascal VOC
# ---------------------------------------------------------------------------

def voc_xml(objects="", width=1000, height=1000, filename="000001.jpg"):
    return f"""<annotation>
      <filename>{filename}</filename>
      <size><width>{width}</width><height>{height}</height></size>
      {objects}
    </annotation>"""


def voc_object(name="dog", xmin=100, ymin=200, xmax=300, ymax=600, extra=""):
    return f"""<object><name>{name}</name>{extra}
      <bndbox><xmin>{xmin}</xmin><ymin>{ymin}</ymin>
      <xmax>{xmax}</xmax><ymax>{ymax}</ymax></bndbox></object>"""


class TestVOC:
    def test_corners_become_origin_plus_size(self):
        """xmin=100 xmax=300 is a width of 200, not a width of 300."""
        obj = only_object(VOCImporter().parse(ET.fromstring(voc_xml(voc_object()))))
        c = obj["coordinates"]
        assert c["x"] == pytest.approx(0.1)
        assert c["y"] == pytest.approx(0.2)
        assert c["width"] == pytest.approx(0.2)
        assert c["height"] == pytest.approx(0.4)

    def test_difficult_flags_survive(self):
        """A benchmark that excludes `difficult` is not reproducible without it."""
        xml = voc_xml(voc_object(extra="<difficult>1</difficult>"))
        obj = only_object(VOCImporter().parse(ET.fromstring(xml)))
        assert obj["difficult"] == 1

    def test_truncated_and_occluded_survive_too(self):
        xml = voc_xml(voc_object(
            extra="<truncated>1</truncated><occluded>0</occluded>"))
        obj = only_object(VOCImporter().parse(ET.fromstring(xml)))
        assert obj["truncated"] == 1
        assert obj["occluded"] == 0

    def test_missing_size_skips_the_image_with_a_warning(self):
        """Guessing dimensions would misplace every box on the image."""
        xml = "<annotation><filename>x.jpg</filename>" + voc_object() + "</annotation>"
        result = VOCImporter().parse(ET.fromstring(xml))
        assert result.images == []
        assert any("size" in w for w in result.warnings)

    def test_a_degenerate_box_is_rejected_with_a_reason(self):
        xml = voc_xml(voc_object(xmin=300, xmax=100))
        result = VOCImporter().parse(ET.fromstring(xml))
        assert result.images[0].objects == []
        assert any("degenerate" in w for w in result.warnings)

    def test_an_object_without_a_bndbox_explains_why(self):
        xml = voc_xml("<object><name>dog</name></object>")
        result = VOCImporter().parse(ET.fromstring(xml))
        assert any("segmentation masks live in a separate directory" in w
                   for w in result.warnings)

    def test_detect_rejects_other_xml(self):
        assert not VOCImporter().detect("<foo><bar/></foo>")
        assert VOCImporter().detect(voc_xml(voc_object()))

    def test_directory_import_merges_labels(self, tmp_path):
        (tmp_path / "a.xml").write_text(voc_xml(voc_object("dog"), filename="a.jpg"))
        (tmp_path / "b.xml").write_text(voc_xml(voc_object("cat"), filename="b.jpg"))
        result = VOCImporter().parse_directory(str(tmp_path))
        assert len(result.images) == 2
        assert [l["name"] for l in result.labels] == ["cat", "dog"]

    def test_malformed_xml_does_not_abort_the_whole_import(self, tmp_path):
        (tmp_path / "good.xml").write_text(voc_xml(voc_object(), filename="g.jpg"))
        (tmp_path / "bad.xml").write_text("<annotation><unclosed>")
        result = VOCImporter().parse_directory(str(tmp_path))
        assert len(result.images) == 1
        assert any("malformed" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# LabelMe
# ---------------------------------------------------------------------------

def labelme_doc(shapes, width=1000, height=1000):
    return {"version": "5.2.1", "imagePath": "img.jpg",
            "imageWidth": width, "imageHeight": height, "shapes": shapes}


class TestLabelMe:
    def test_rectangle_is_two_opposite_corners(self):
        doc = labelme_doc([{"label": "cat", "shape_type": "rectangle",
                            "points": [[100, 200], [300, 600]]}])
        obj = only_object(LabelMeImporter().parse(doc))
        assert obj["type"] == "bbox"
        c = obj["coordinates"]
        assert c["x"] == pytest.approx(0.1)
        assert c["width"] == pytest.approx(0.2)
        assert c["height"] == pytest.approx(0.4)

    def test_rectangle_corners_may_be_dragged_in_any_order(self):
        """Bottom-right to top-left must give the same box."""
        forward = labelme_doc([{"label": "c", "shape_type": "rectangle",
                                "points": [[100, 200], [300, 600]]}])
        reverse = labelme_doc([{"label": "c", "shape_type": "rectangle",
                                "points": [[300, 600], [100, 200]]}])
        assert (only_object(LabelMeImporter().parse(forward))["coordinates"]
                == only_object(LabelMeImporter().parse(reverse))["coordinates"])

    def test_circle_radius_is_a_distance_not_a_stored_value(self):
        doc = labelme_doc([{"label": "cell", "shape_type": "circle",
                            "points": [[500, 500], [500, 600]]}])
        obj = only_object(LabelMeImporter().parse(doc))
        assert obj["type"] == "ellipse"
        assert obj["coordinates"]["rx"] == pytest.approx(0.1)
        assert obj["coordinates"]["ry"] == pytest.approx(0.1)

    def test_line_becomes_a_polyline_not_a_polygon(self):
        doc = labelme_doc([{"label": "lane", "shape_type": "linestrip",
                            "points": [[0, 0], [500, 500], [900, 100]]}])
        obj = only_object(LabelMeImporter().parse(doc))
        assert obj["type"] == "polyline"
        # An open path claims no area.
        canonical = normalize_annotation_object(obj, W, H)
        assert canonical["area"] == 0.0

    def test_point_becomes_a_landmark(self):
        doc = labelme_doc([{"label": "tip", "shape_type": "point",
                            "points": [[250, 750]]}])
        obj = only_object(LabelMeImporter().parse(doc))
        assert obj["type"] == "landmark"
        assert obj["coordinates"]["x"] == pytest.approx(0.25)

    def test_group_id_becomes_an_instance(self):
        doc = labelme_doc([{"label": "cat", "shape_type": "polygon",
                            "points": [[0, 0], [100, 0], [100, 100]],
                            "group_id": 3}])
        obj = only_object(LabelMeImporter().parse(doc))
        assert obj["instance"] == 3

    def test_a_two_point_polygon_is_rejected_with_a_reason(self):
        doc = labelme_doc([{"label": "cat", "shape_type": "polygon",
                            "points": [[0, 0], [100, 100]]}])
        result = LabelMeImporter().parse(doc)
        assert result.images[0].objects == []
        assert any("at least 3" in w for w in result.warnings)

    def test_image_data_is_not_carried_into_the_project(self):
        """Inlining the corpus would multiply the project size for no gain."""
        doc = labelme_doc([{"label": "cat", "shape_type": "rectangle",
                            "points": [[0, 0], [10, 10]]}])
        doc["imageData"] = "A" * 10000
        result = LabelMeImporter().parse(doc)
        assert "imageData" not in json.dumps(result.images[0].extra)

    def test_detect_is_not_fooled_by_any_dict_with_shapes(self):
        assert not LabelMeImporter().detect({"shapes": []})
        assert LabelMeImporter().detect(labelme_doc([]))


# ---------------------------------------------------------------------------
# Everything lands in the client contract
# ---------------------------------------------------------------------------

class TestContractCompliance:
    """Whatever the source format, the output must be readable by the exporters."""

    def _all_objects(self):
        objs = []
        objs.append(only_object(VOCImporter().parse(
            ET.fromstring(voc_xml(voc_object())))))
        for shape in (
            {"label": "c", "shape_type": "rectangle", "points": [[10, 10], [90, 90]]},
            {"label": "c", "shape_type": "polygon",
             "points": [[10, 10], [90, 10], [90, 90]]},
            {"label": "c", "shape_type": "circle", "points": [[50, 50], [50, 70]]},
            {"label": "c", "shape_type": "point", "points": [[20, 20]]},
            {"label": "c", "shape_type": "linestrip", "points": [[0, 0], [50, 50]]},
        ):
            objs.append(only_object(LabelMeImporter().parse(labelme_doc([shape]))))
        return objs

    def test_every_imported_object_normalizes(self):
        for obj in self._all_objects():
            canonical = normalize_annotation_object(obj, W, H)
            assert canonical is not None, f"exporters cannot read {obj['type']}"
            assert canonical["bbox"] is not None

    def test_every_imported_object_is_normalized_to_the_unit_square(self):
        for obj in self._all_objects():
            coords = obj["coordinates"]
            values = []
            if isinstance(coords, list):
                values = [v for p in coords for v in (p["x"], p["y"])]
            elif isinstance(coords, dict):
                values = [v for k, v in coords.items() if k != "angle"]
            for v in values:
                assert -0.001 <= v <= 1.001, f"{obj['type']} coordinate {v}"


# ---------------------------------------------------------------------------
# The generated project has to actually load its images
# ---------------------------------------------------------------------------

class TestImageUrlPrefix:
    """
    A bare filename is not a URL any route serves.

    All three importers originally ignored --image-url-prefix, so the generated
    project stored `street.jpg`, the canvas 404'd, and nothing in the UI said
    why. Caught only by starting the imported project in a browser.
    """

    def test_yolo_applies_the_prefix(self, tmp_path):
        root = yolo_dataset(tmp_path, ["0 0.5 0.5 0.2 0.2"])
        result = YOLOImporter().parse_directory(
            str(root), {"image_url_prefix": "/media"})
        assert result.images[0].extra["image_url"].startswith("/media/")

    def test_voc_applies_the_prefix(self):
        result = VOCImporter().parse(ET.fromstring(voc_xml(voc_object())),
                                     {"image_url_prefix": "/media"})
        assert result.images[0].extra["image_url"] == "/media/000001.jpg"

    def test_labelme_applies_the_prefix(self):
        doc = labelme_doc([{"label": "c", "shape_type": "rectangle",
                            "points": [[0, 0], [10, 10]]}])
        result = LabelMeImporter().parse(doc, {"image_url_prefix": "/media"})
        assert result.images[0].extra["image_url"] == "/media/img.jpg"

    def test_no_prefix_leaves_the_bare_filename(self):
        result = VOCImporter().parse(ET.fromstring(voc_xml(voc_object())))
        assert result.images[0].extra["image_url"] == "000001.jpg"

    def test_slashes_are_not_doubled(self):
        result = VOCImporter().parse(ET.fromstring(voc_xml(voc_object())),
                                     {"image_url_prefix": "/media/"})
        assert result.images[0].extra["image_url"] == "/media/000001.jpg"

    def test_voc_directory_import_passes_options_through(self, tmp_path):
        """parse_directory must forward options, or the prefix is lost again."""
        (tmp_path / "a.xml").write_text(voc_xml(voc_object(), filename="a.jpg"))
        result = VOCImporter().parse_directory(
            str(tmp_path), {"image_url_prefix": "/media"})
        assert result.images[0].extra["image_url"] == "/media/a.jpg"


class TestStatsContract:
    """The CLI reads these keys unconditionally; a mismatch is a crash."""

    @pytest.mark.parametrize("keys", [
        ("num_images", "num_annotations", "num_categories", "num_warnings")])
    def test_voc_reports_the_keys_the_cli_reads(self, keys):
        result = VOCImporter().parse(ET.fromstring(voc_xml(voc_object())))
        for key in keys:
            assert key in result.stats, key

    def test_yolo_reports_the_keys_the_cli_reads(self, tmp_path):
        root = yolo_dataset(tmp_path, ["0 0.5 0.5 0.2 0.2"])
        stats = YOLOImporter().parse_directory(str(root)).stats
        assert stats["num_images"] == 1
        assert stats["num_annotations"] == 1

    def test_labelme_reports_the_keys_the_cli_reads(self):
        doc = labelme_doc([{"label": "c", "shape_type": "rectangle",
                            "points": [[0, 0], [10, 10]]}])
        stats = LabelMeImporter().parse(doc).stats
        assert stats["num_images"] == 1
        assert stats["num_annotations"] == 1
