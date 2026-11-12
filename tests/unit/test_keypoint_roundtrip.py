"""
COCO keypoints must survive import -> annotate -> export.

The importer used to explode each set into one ``landmark`` per visible point,
labelled ``"person:left_shoulder"``. That discarded the ordering (the only thing
that makes index 5 mean "left shoulder"), the grouping (two people became an
indistinguishable pile of points), and the visibility flags (unlabelled points
were dropped; occluded ones became indistinguishable from visible ones). The
exporter then skipped landmarks outright, so the format was import-only.

These tests close the loop and pin each of those three losses.
"""

from __future__ import annotations

import json

import pytest

from potato.export.cv_utils import (
    normalize_annotation_object,
    to_client_object,
)

W, H = 640, 480

#: A four-point subset with one of each visibility state.
FLAT = [320, 96, 2,      # visible
        288, 144, 2,     # visible
        352, 144, 1,     # labelled but occluded
        0, 0, 0]         # not labelled


class TestContract:
    def test_flat_coco_triplets_are_accepted(self):
        c = normalize_annotation_object(
            {"type": "keypoint_set", "label": "person", "keypoints": FLAT}, W, H)
        assert c["points"] == [[320.0, 96.0], [288.0, 144.0],
                               [352.0, 144.0], [0.0, 0.0]]
        assert c["visibility"] == [2, 2, 1, 0]

    def test_occluded_is_distinguishable_from_visible(self):
        """v=1 and v=2 must not collapse — that was one of the three losses."""
        c = normalize_annotation_object(
            {"type": "keypoint_set", "label": "p", "keypoints": FLAT}, W, H)
        assert 1 in c["visibility"]
        assert 2 in c["visibility"]

    def test_unlabelled_points_do_not_drag_the_bbox_to_the_origin(self):
        c = normalize_annotation_object(
            {"type": "keypoint_set", "label": "p", "keypoints": FLAT}, W, H)
        x, y, w, h = c["bbox"]
        assert x == 288.0 and y == 96.0
        assert w == 64.0 and h == 48.0

    def test_ordering_is_preserved(self):
        c = normalize_annotation_object(
            {"type": "keypoint_set", "label": "p", "keypoints": FLAT}, W, H)
        # Index 2 is the occluded one, and must stay at index 2.
        assert c["visibility"][2] == 1
        assert c["points"][2] == [352.0, 144.0]

    def test_round_trips_through_the_client_shape(self):
        canon = normalize_annotation_object(
            {"type": "keypoint_set", "label": "p", "keypoints": FLAT}, W, H)
        client = to_client_object(
            "keypoint_set", "p", img_w=W, img_h=H,
            keypoints=[[x, y, v] for (x, y), v in
                       zip(canon["points"], canon["visibility"])],
            skeleton="coco_person")
        again = normalize_annotation_object(client, W, H)
        assert again["points"] == canon["points"]
        assert again["visibility"] == canon["visibility"]
        assert again["skeleton"] == "coco_person"


class TestImporterEmitsOneSet:
    def test_one_annotation_becomes_one_keypoint_set(self):
        from potato.importers.coco_importer import COCOImporter

        importer = COCOImporter()
        objects = importer._convert_keypoints(
            {"keypoints": FLAT}, "person", "#f00", W, H,
            ["nose", "left_eye", "right_eye", "left_ear"], set())

        assert len(objects) == 1, "a skeleton is ONE annotation, not N points"
        assert objects[0]["type"] == "keypoint_set"
        assert len(objects[0]["coordinates"]) == 4

    def test_two_people_stay_separate(self):
        """The grouping loss: two sets must not merge into a pile of points."""
        from potato.importers.coco_importer import COCOImporter

        importer = COCOImporter()
        tools = set()
        a = importer._convert_keypoints(
            {"keypoints": FLAT}, "person", "#f00", W, H, ["a", "b", "c", "d"], tools)
        b = importer._convert_keypoints(
            {"keypoints": [10, 10, 2, 20, 20, 2, 30, 30, 2, 40, 40, 2]},
            "person", "#f00", W, H, ["a", "b", "c", "d"], tools)

        assert len(a) == 1 and len(b) == 1
        assert a[0]["coordinates"] != b[0]["coordinates"]

    def test_registers_the_right_tool(self):
        from potato.importers.coco_importer import COCOImporter

        tools = set()
        COCOImporter()._convert_keypoints(
            {"keypoints": FLAT}, "person", "#f00", W, H, ["a"], tools)
        assert "keypoint_set" in tools
        assert "landmark" not in tools

    def test_coco_person_skeleton_is_recognised(self):
        from potato.importers.coco_importer import COCOImporter

        names = ["nose", "left_eye", "right_eye", "left_ear", "right_ear",
                 "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                 "left_wrist", "right_wrist", "left_hip", "right_hip",
                 "left_knee", "right_knee", "left_ankle", "right_ankle"]
        assert COCOImporter._skeleton_name("person", names) == "coco_person"
        assert COCOImporter._skeleton_name("dog", ["a", "b"]) == "dog"
        assert COCOImporter._skeleton_name("x", []) == ""


class TestExporterReassembles:
    def _export(self, objects, labels=("person",)):
        from potato.export.base import ExportContext
        from potato.export.coco_exporter import COCOExporter
        import tempfile
        import os

        schemas = [{
            "annotation_type": "image_annotation", "name": "pose",
            "labels": [{"name": l} for l in labels],
        }]
        out_dir = tempfile.mkdtemp()
        ctx = ExportContext(
            schemas=schemas,
            annotations=[{
                "instance_id": "img_1",
                "image_annotations": {"pose": objects},
            }],
            items={"img_1": {"image_width": W, "image_height": H,
                             "file_name": "img_1.jpg"}},
            config={},
            output_dir=out_dir,
        )
        COCOExporter().export(ctx, out_dir)
        # The exporter writes annotations.json INSIDE output_path.
        with open(os.path.join(out_dir, "annotations.json")) as fh:
            return json.load(fh)

    def test_keypoints_array_is_emitted(self):
        client = to_client_object(
            "keypoint_set", "person", img_w=W, img_h=H,
            keypoints=FLAT, skeleton="coco_person")
        doc = self._export([client])

        assert doc["annotations"], "keypoint_set produced no COCO annotation"
        ann = doc["annotations"][0]
        assert "keypoints" in ann, "exporter did not reassemble the array"
        assert ann["keypoints"] == [320.0, 96.0, 2, 288.0, 144.0, 2,
                                    352.0, 144.0, 1, 0.0, 0.0, 0]

    def test_num_keypoints_counts_labelled_points_only(self):
        client = to_client_object(
            "keypoint_set", "person", img_w=W, img_h=H, keypoints=FLAT)
        ann = self._export([client])["annotations"][0]
        # Three of the four are labelled (v=2, v=2, v=1); the v=0 does not count.
        assert ann["num_keypoints"] == 3

    def test_unlabelled_points_export_as_zero_triplets(self):
        """COCO's convention: an unlabelled point is (0, 0, 0), not its position."""
        client = to_client_object(
            "keypoint_set", "person", img_w=W, img_h=H,
            keypoints=[100, 100, 0, 200, 200, 2])
        ann = self._export([client])["annotations"][0]
        assert ann["keypoints"][:3] == [0.0, 0.0, 0]

    def test_full_round_trip_is_lossless(self):
        """COCO in -> Potato -> COCO out, with nothing dropped."""
        from potato.importers.coco_importer import COCOImporter

        objects = COCOImporter()._convert_keypoints(
            {"keypoints": FLAT}, "person", "#f00", W, H,
            ["a", "b", "c", "d"], set())
        ann = self._export(objects)["annotations"][0]
        assert ann["keypoints"] == FLAT
        assert ann["num_keypoints"] == 3


class TestAgreement:
    def _kp(self, triplets):
        return normalize_annotation_object(
            {"type": "keypoint_set", "label": "p", "keypoints": triplets}, W, H)

    def test_identical_skeletons_agree(self):
        from potato.server_utils.iaa import geometry

        a = self._kp(FLAT)
        assert geometry.similarity(a, self._kp(FLAT)) == pytest.approx(1.0)

    def test_distant_skeletons_disagree(self):
        from potato.server_utils.iaa import geometry

        far = [10, 10, 2, 20, 20, 2, 30, 30, 2, 0, 0, 0]
        assert geometry.similarity(self._kp(FLAT), self._kp(far)) < 0.2

    def test_uses_oks_not_iou(self):
        """A point set has no area; IoU would report 0 for everything."""
        from potato.server_utils.iaa import geometry

        assert geometry.similarity(self._kp(FLAT), self._kp(FLAT)) > 0.0

    def test_a_keypoint_set_never_matches_a_bbox(self):
        from potato.server_utils.iaa import geometry

        box = normalize_annotation_object(
            {"type": "bbox", "label": "p",
             "coordinates": {"x": 0.4, "y": 0.1, "width": 0.2, "height": 0.2}},
            W, H)
        assert geometry.similarity(self._kp(FLAT), box) == 0.0
