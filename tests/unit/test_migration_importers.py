"""
CVAT and V7 Darwin importers — the two direct migration paths.

These matter differently from the others: someone importing CVAT or Darwin data
is *leaving a platform*, so a silently lossy import is the worst possible
outcome. They will not notice until the annotations are gone from the source.

So the tests here concentrate on what each format carries that Potato cannot
represent — CVAT video tracks, Darwin polygon holes, Darwin image-level tags —
and assert that each is **reported**, not quietly dropped or, worse, quietly
mangled into something plausible.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from potato.export.cv_utils import normalize_annotation_object
from potato.importers.cvat_importer import CVATImporter
from potato.importers.darwin_importer import DarwinImporter
from potato.importers.registry import import_registry

W, H = 640, 480


def objects_of(result):
    assert result.images, result.warnings
    return result.images[0].objects


def only(result):
    objs = objects_of(result)
    assert len(objs) == 1, objs
    return objs[0]


# ---------------------------------------------------------------------------
# CVAT
# ---------------------------------------------------------------------------

def cvat_xml(shapes="", labels="", tracks=""):
    return f"""<annotations>
      <version>1.1</version>
      <meta><task><labels>{labels}</labels></task></meta>
      <image id="0" name="img.jpg" width="{W}" height="{H}">{shapes}</image>
      {tracks}
    </annotations>"""


class TestCVATShapes:
    def test_box_corners_become_origin_plus_size(self):
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<box label="car" xtl="64" ytl="48" xbr="320" ybr="240"/>'))))
        c = obj["coordinates"]
        assert obj["type"] == "bbox"
        assert c["x"] == pytest.approx(0.1)
        assert c["y"] == pytest.approx(0.1)
        assert c["width"] == pytest.approx(0.4)
        assert c["height"] == pytest.approx(0.4)

    def test_polyline_stays_an_open_path(self):
        """The payoff for adding the polyline primitive: nothing is flattened."""
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<polyline label="lane" points="0,0;320,240;640,0"/>'))))
        assert obj["type"] == "polyline"
        assert normalize_annotation_object(obj, W, H)["area"] == 0.0

    def test_ellipse_keeps_its_rotation(self):
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<ellipse label="cell" cx="320" cy="240" rx="64" ry="24" rotation="30"/>'))))
        assert obj["type"] == "ellipse"
        assert obj["coordinates"]["angle"] == pytest.approx(30)
        assert obj["coordinates"]["rx"] == pytest.approx(0.1)

    def test_polygon_needs_three_points(self):
        result = CVATImporter().parse(ET.fromstring(cvat_xml(
            '<polygon label="road" points="0,0;10,10"/>')))
        assert objects_of(result) == []
        assert any("2 points" in w for w in result.warnings)

    def test_a_single_point_is_a_landmark(self):
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<points label="tip" points="64,48"/>'))))
        assert obj["type"] == "landmark"

    def test_several_points_become_a_keypoint_set(self):
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<points label="pose" points="64,48;128,96;192,144"/>'))))
        assert obj["type"] == "keypoint_set"
        assert len(obj["coordinates"]) == 3

    def test_degenerate_box_is_reported(self):
        result = CVATImporter().parse(ET.fromstring(cvat_xml(
            '<box label="car" xtl="320" ytl="48" xbr="64" ybr="240"/>')))
        assert objects_of(result) == []
        assert any("degenerate" in w for w in result.warnings)


class TestCVATMetadata:
    def test_label_colours_survive_the_move(self):
        result = CVATImporter().parse(ET.fromstring(cvat_xml(
            shapes='<box label="car" xtl="0" ytl="0" xbr="10" ybr="10"/>',
            labels='<label><name>car</name><color>#ff0000</color></label>')))
        assert result.labels == [{"name": "car", "color": "#ff0000"}]

    def test_shape_attributes_are_carried_across(self):
        """A project whose variables live in attributes would import empty."""
        obj = only(CVATImporter().parse(ET.fromstring(cvat_xml(
            '<box label="car" xtl="0" ytl="0" xbr="10" ybr="10" occluded="1">'
            '<attribute name="model">sedan</attribute></box>'))))
        assert obj["occluded"] == 1
        assert obj["attributes"] == {"model": "sedan"}


class TestCVATTracks:
    def test_video_tracks_are_reported_not_flattened(self):
        """
        A track is one object across frames. Importing only frame 0 would look
        like a successful import of a dataset that had quietly lost its video
        annotations.
        """
        result = CVATImporter().parse(ET.fromstring(cvat_xml(tracks=(
            '<track id="0" label="car">'
            '<box frame="0" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            '<box frame="1" xtl="5" ytl="5" xbr="15" ybr="15"/>'
            '</track>'))))
        assert objects_of(result) == []
        assert any("track" in w.lower() for w in result.warnings)
        assert any("discard" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Darwin / V7
# ---------------------------------------------------------------------------

def darwin_doc(annotations, width=W, height=H, slots=None):
    return {
        "version": "2.0",
        "item": {"name": "img.jpg",
                 "slots": slots if slots is not None
                 else [{"width": width, "height": height}]},
        "annotations": annotations,
    }


class TestDarwinShapes:
    def test_bounding_box_is_origin_plus_size(self):
        """Unlike CVAT and VOC, Darwin boxes are x/y/w/h."""
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "car", "bounding_box": {"x": 64, "y": 48, "w": 256, "h": 192}}])))
        c = obj["coordinates"]
        assert c["x"] == pytest.approx(0.1)
        assert c["width"] == pytest.approx(0.4)

    def test_line_becomes_a_polyline(self):
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "lane", "line": {"path": [{"x": 0, "y": 0},
                                               {"x": 320, "y": 240}]}}])))
        assert obj["type"] == "polyline"

    def test_skeleton_becomes_an_ordered_keypoint_set(self):
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "person", "skeleton": {"nodes": [
                {"x": 10, "y": 10},
                {"x": 20, "y": 20, "occluded": True},
                {"x": 30, "y": 30}]}}])))
        assert obj["type"] == "keypoint_set"
        # occluded -> COCO visibility 1, visible -> 2
        assert [p["v"] for p in obj["coordinates"]] == [2, 1, 2]

    def test_ellipse_radius_may_be_isotropic(self):
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "cell", "ellipse": {"center": {"x": 320, "y": 240},
                                         "radius": {"x": 64}}}])))
        assert obj["coordinates"]["rx"] == pytest.approx(0.1)
        assert obj["coordinates"]["ry"] == pytest.approx(64 / H)

    def test_sub_annotations_are_preserved(self):
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "car", "bounding_box": {"x": 0, "y": 0, "w": 10, "h": 10},
             "text": {"text": "licence ABC"}, "instance_id": {"value": 7}}])))
        assert obj["text"] == {"text": "licence ABC"}
        assert obj["instance_id"] == {"value": 7}


class TestDarwinLossyCases:
    def test_polygon_holes_are_reported_not_filled(self):
        """
        Unioning the rings would FILL the holes — a plausible-looking result
        that is wrong. An honest warning beats a silent wrong answer.
        """
        result = DarwinImporter().parse(darwin_doc([
            {"name": "road", "polygon": {"paths": [
                [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}],
                [{"x": 20, "y": 20}, {"x": 40, "y": 20}, {"x": 40, "y": 40}],
            ]}}]))
        assert len(objects_of(result)) == 1
        assert any("hole" in w for w in result.warnings)

    def test_the_exterior_ring_is_the_one_imported(self):
        obj = only(DarwinImporter().parse(darwin_doc([
            {"name": "road", "polygon": {"paths": [
                [{"x": 0, "y": 0}, {"x": 640, "y": 0}, {"x": 640, "y": 480}],
                [{"x": 20, "y": 20}, {"x": 40, "y": 20}, {"x": 40, "y": 40}],
            ]}}])))
        assert obj["coordinates"][1]["x"] == pytest.approx(1.0)

    def test_image_level_tags_are_reported_with_a_remedy(self):
        result = DarwinImporter().parse(darwin_doc([
            {"name": "daytime", "tag": {}}]))
        assert objects_of(result) == []
        warning = " ".join(result.warnings)
        assert "tag" in warning
        # Says what to do instead, rather than only what failed.
        assert "radio" in warning or "multiselect" in warning

    def test_multi_slot_items_say_only_the_first_was_read(self):
        result = DarwinImporter().parse(darwin_doc(
            [{"name": "car", "bounding_box": {"x": 0, "y": 0, "w": 10, "h": 10}}],
            slots=[{"width": W, "height": H}, {"width": 100, "height": 100}]))
        assert any("slots" in w for w in result.warnings)

    def test_an_unknown_shape_key_names_what_was_expected(self):
        result = DarwinImporter().parse(darwin_doc([
            {"name": "x", "cuboid": {"front": {}}}]))
        assert objects_of(result) == []
        assert any("bounding_box" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class TestRegistrationAndContract:
    @pytest.mark.parametrize("fmt", ["cvat", "darwin"])
    def test_registered(self, fmt):
        assert import_registry.get(fmt) is not None

    def test_detect_does_not_claim_other_documents(self):
        assert not CVATImporter().detect("<foo/>")
        assert not DarwinImporter().detect({"annotations": []})
        assert not DarwinImporter().detect({"shapes": [], "imagePath": "x"})

    def test_cvat_detect_accepts_a_real_export(self):
        assert CVATImporter().detect(cvat_xml())

    def test_every_shape_lands_in_the_client_contract(self):
        cvat = CVATImporter().parse(ET.fromstring(cvat_xml(
            '<box label="a" xtl="0" ytl="0" xbr="10" ybr="10"/>'
            '<polygon label="b" points="0,0;10,0;10,10"/>'
            '<polyline label="c" points="0,0;10,10"/>'
            '<ellipse label="d" cx="10" cy="10" rx="5" ry="5"/>'
            '<points label="e" points="1,1"/>')))
        darwin = DarwinImporter().parse(darwin_doc([
            {"name": "a", "bounding_box": {"x": 0, "y": 0, "w": 10, "h": 10}},
            {"name": "c", "line": {"path": [{"x": 0, "y": 0}, {"x": 5, "y": 5}]}},
            {"name": "f", "keypoint": {"x": 3, "y": 4}},
        ]))
        for result in (cvat, darwin):
            for obj in objects_of(result):
                assert normalize_annotation_object(obj, W, H) is not None, obj

    @pytest.mark.parametrize("importer,doc", [
        (CVATImporter(), None), (DarwinImporter(), None)])
    def test_url_prefix_is_applied(self, importer, doc):
        if isinstance(importer, CVATImporter):
            result = importer.parse(ET.fromstring(cvat_xml()),
                                    {"image_url_prefix": "/media"})
        else:
            result = importer.parse(darwin_doc([]), {"image_url_prefix": "/media"})
        assert result.images[0].extra["image_url"] == "/media/img.jpg"

    @pytest.mark.parametrize("key", ["num_images", "num_annotations",
                                     "num_categories", "num_warnings"])
    def test_stats_match_the_cli_contract(self, key):
        assert key in CVATImporter().parse(ET.fromstring(cvat_xml())).stats
        assert key in DarwinImporter().parse(darwin_doc([])).stats


# ---------------------------------------------------------------------------
# Directory detection
# ---------------------------------------------------------------------------

class TestDirectoryDetection:
    """
    The file EXTENSION decides nothing: CVAT and VOC are both .xml, Darwin and
    LabelMe are both .json. Guessing from the suffix sent every CVAT export to
    the VOC importer, which rejected it with a confusing "Not a Pascal VOC
    <annotation> document".
    """

    def detect(self, path):
        from potato.importers.cli import _detect_directory_format
        return _detect_directory_format(str(path))

    def test_cvat_xml_is_not_mistaken_for_voc(self, tmp_path):
        (tmp_path / "annotations.xml").write_text(cvat_xml())
        assert self.detect(tmp_path) == "cvat"

    def test_voc_xml_is_still_detected(self, tmp_path):
        (tmp_path / "000001.xml").write_text(
            "<annotation><filename>a.jpg</filename>"
            "<size><width>1</width><height>1</height></size></annotation>")
        assert self.detect(tmp_path) == "pascal_voc"

    def test_darwin_json_is_not_mistaken_for_labelme(self, tmp_path):
        import json as _json
        (tmp_path / "a.json").write_text(_json.dumps(darwin_doc([])))
        assert self.detect(tmp_path) == "darwin"

    def test_labelme_json_is_still_detected(self, tmp_path):
        import json as _json
        (tmp_path / "a.json").write_text(_json.dumps(
            {"imagePath": "a.jpg", "imageWidth": 1, "imageHeight": 1,
             "shapes": []}))
        assert self.detect(tmp_path) == "labelme"

    def test_yolo_wins_on_a_data_yaml(self, tmp_path):
        (tmp_path / "data.yaml").write_text("names: [a]\n")
        (tmp_path / "labels").mkdir()
        assert self.detect(tmp_path) == "yolo"

    def test_an_empty_directory_is_ambiguous_not_guessed(self, tmp_path):
        """Better to ask than to hand back a silently wrong import."""
        assert self.detect(tmp_path) is None

    def test_malformed_xml_does_not_crash_detection(self, tmp_path):
        (tmp_path / "bad.xml").write_text("<unclosed>")
        assert self.detect(tmp_path) == "pascal_voc"   # falls back, does not raise
