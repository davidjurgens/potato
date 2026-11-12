"""
COCO import -- every segmentation encoding, no preprocessing.

The point of this importer is that a stock COCO file works as-is. These tests
cover each encoding that appears in the wild, and pin the two behaviours that
differentiate it: crowd RLE is imported rather than dropped (V7 skips those
annotations outright), and sparse category IDs survive.
"""

import pytest

from potato.export.cv_utils import decode_rle
from potato.importers import import_registry
from potato.importers.coco_importer import COCOImporter


def _coco(annotations, categories=None, width=100, height=50):
    return {
        "images": [{"id": 1, "file_name": "img1.jpg",
                    "width": width, "height": height}],
        "annotations": annotations,
        "categories": categories or [{"id": 1, "name": "cat"}],
    }


class TestDetect:

    def test_detects_a_coco_file(self):
        assert COCOImporter().detect(_coco([])) is True

    def test_detects_an_empty_but_wellformed_file(self):
        assert COCOImporter().detect(
            {"images": [], "annotations": [], "categories": []}) is True

    @pytest.mark.parametrize("data", [
        None, [], "coco", {"images": "no"}, {"annotations": []},
        {"images": [{"no_id": 1}], "annotations": []},
    ])
    def test_rejects_non_coco(self, data):
        assert COCOImporter().detect(data) is False

    def test_registry_autodetects(self):
        assert import_registry.detect_format(_coco([])) == "coco"


class TestBboxOnly:

    def test_bbox_with_empty_segmentation(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1,
             "bbox": [10, 5, 20, 10], "segmentation": [], "iscrowd": 0},
        ]))
        obj, = result.images[0].objects
        assert obj["type"] == "bbox"
        assert obj["coordinates"]["x"] == pytest.approx(0.1)
        assert obj["coordinates"]["y"] == pytest.approx(0.1)
        assert obj["coordinates"]["width"] == pytest.approx(0.2)
        assert obj["coordinates"]["height"] == pytest.approx(0.2)
        assert "bbox" in result.tools

    def test_bbox_with_segmentation_absent_entirely(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]},
        ]))
        assert result.images[0].objects[0]["type"] == "bbox"


class TestPolygonSegmentation:

    def test_single_ring(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": [[10, 5, 30, 5, 30, 15, 10, 15]],
             "bbox": [10, 5, 20, 10]},
        ]))
        obj, = result.images[0].objects
        assert obj["type"] == "polygon"
        assert len(obj["coordinates"]) == 4
        assert obj["coordinates"][0] == {"x": pytest.approx(0.1),
                                         "y": pytest.approx(0.1)}
        assert "polygon" in result.tools

    def test_multi_ring_becomes_multiple_polygons_with_one_warning(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": [[0, 0, 20, 0, 20, 20, 0, 20],
                              [5, 5, 10, 5, 10, 10, 5, 10]],
             "bbox": [0, 0, 20, 20]},
        ]))
        objs = result.images[0].objects
        assert len(objs) == 2
        assert all(o["type"] == "polygon" for o in objs)
        assert sum("Multi-ring" in w for w in result.warnings) == 1

    def test_degenerate_ring_falls_back_to_bbox(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": [[1, 1, 2, 2]], "bbox": [1, 1, 5, 5]},
        ]))
        assert result.images[0].objects[0]["type"] == "bbox"
        assert any("fewer than 3 points" in w for w in result.warnings)


class TestRLESegmentation:

    UNCOMPRESSED = {"counts": [2, 4], "size": [2, 3]}

    def test_uncompressed_rle(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": dict(self.UNCOMPRESSED), "bbox": [0, 0, 3, 2]},
        ], width=3, height=2))
        obj, = result.images[0].objects
        assert obj["type"] == "mask"
        assert obj["rle"]["size"] == [2, 3]
        assert decode_rle(obj["rle"], 3, 2).count(1) == 4
        assert {"brush", "eraser", "fill"} <= set(result.tools)

    def test_compressed_rle_string(self):
        pytest.importorskip("pycocotools")
        import numpy as np
        from pycocotools import mask as mask_utils

        arr = np.array([[1, 0, 1], [0, 1, 0]], dtype=np.uint8, order="F")
        encoded = mask_utils.encode(arr)

        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": {"counts": encoded["counts"].decode("ascii"),
                              "size": list(encoded["size"])},
             "bbox": [0, 0, 3, 2]},
        ], width=3, height=2))

        obj, = result.images[0].objects
        assert obj["type"] == "mask"
        assert decode_rle(obj["rle"], 3, 2) == [1, 0, 1, 0, 1, 0]

    def test_noncrowd_instances_each_get_an_index(self):
        """Two instances of one class must not merge -- that is the whole point
        of instance segmentation."""
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": {"counts": [0, 2, 4], "size": [2, 3]}},
            {"id": 2, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": {"counts": [4, 2], "size": [2, 3]}},
        ], width=3, height=2))

        objs = result.images[0].objects
        assert len(objs) == 2
        assert sorted(o["instance"] for o in objs) == [0, 1]
        assert all(o.get("iscrowd", 0) == 0 for o in objs)

    def test_undecodable_rle_falls_back_to_bbox(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": {"counts": [1, 1]}, "bbox": [1, 1, 5, 5]},
        ]))
        assert result.images[0].objects[0]["type"] == "bbox"
        assert any("undecodable" in w for w in result.warnings)


class TestCrowdHandling:
    """V7 drops iscrowd=1 annotations outright. Canonical COCO pairs iscrowd=1
    with RLE, so a stock file loses exactly those instances there."""

    def test_crowd_rle_is_imported_not_dropped(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "segmentation": {"counts": [2, 4], "size": [2, 3]}},
        ], width=3, height=2))

        obj, = result.images[0].objects
        assert obj["type"] == "mask"
        assert obj["iscrowd"] == 1
        assert decode_rle(obj["rle"], 3, 2).count(1) == 4

    def test_crowd_regions_of_one_class_merge_into_one_mask(self):
        """COCO permits at most one crowd annotation per category per image."""
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "segmentation": {"counts": [0, 2, 4], "size": [2, 3]}},
            {"id": 2, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "segmentation": {"counts": [4, 2], "size": [2, 3]}},
        ], width=3, height=2))

        obj, = result.images[0].objects
        assert obj["iscrowd"] == 1
        # union of pixels 0-1 and pixels 4-5
        assert decode_rle(obj["rle"], 3, 2).count(1) == 4

    def test_merge_crowd_can_be_disabled(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "segmentation": {"counts": [0, 2, 4], "size": [2, 3]}},
            {"id": 2, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "segmentation": {"counts": [4, 2], "size": [2, 3]}},
        ], width=3, height=2), {"merge_crowd": False})
        assert len(result.images[0].objects) == 2


class TestSparseCategoryIds:

    def test_original_ids_are_preserved_as_label_id(self):
        result = import_registry.parse("coco", _coco(
            [],
            categories=[
                {"id": 1, "name": "person", "supercategory": "person"},
                {"id": 18, "name": "dog", "supercategory": "animal"},
                {"id": 90, "name": "toothbrush"},
            ]))
        assert [l["label_id"] for l in result.labels] == [1, 18, 90]
        assert result.labels[1]["supercategory"] == "animal"
        assert all(l.get("color") for l in result.labels)

    def test_unknown_category_id_warns_and_skips(self):
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 999, "bbox": [0, 0, 5, 5]},
        ]))
        assert result.images[0].objects == []
        assert any("unknown category_id" in w for w in result.warnings)


class TestMissingDimensionsAreAHardError:
    """Silently emitting zeros is exactly the defect that was already live in
    the exporters; the importer must refuse instead."""

    @pytest.mark.parametrize("img", [
        {"id": 1, "file_name": "a.jpg"},
        {"id": 1, "file_name": "a.jpg", "width": 0, "height": 0},
        {"id": 1, "file_name": "a.jpg", "width": 640},
    ])
    def test_raises_naming_the_image(self, img):
        data = {"images": [img], "annotations": [], "categories": []}
        with pytest.raises(ValueError) as exc:
            import_registry.parse("coco", data)
        assert "a.jpg" in str(exc.value)
        assert "--image-dir" in str(exc.value)


class TestKeypoints:

    #: One person: nose visible (v=2), eye occluded (v=1), ear unlabelled (v=0).
    DATA = _coco([
        {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
         "bbox": [0, 0, 10, 10], "segmentation": [],
         "keypoints": [10, 5, 2, 20, 10, 1, 30, 15, 0]},
    ], categories=[{"id": 1, "name": "person",
                    "keypoints": ["nose", "eye", "ear"]}])

    def test_opt_in_produces_one_keypoint_set(self):
        """
        Deliberate contract change: a skeleton is ONE annotation.

        This used to emit one ``landmark`` per visible point, labelled
        ``person:nose``. That threw away the ordering, the grouping and the
        visibility flags, so nothing could rebuild the COCO ``keypoints`` array
        and the format was import-only. See test_keypoint_roundtrip.py.
        """
        without = import_registry.parse("coco", self.DATA)
        assert all(o["type"] != "keypoint_set"
                   for o in without.images[0].objects)

        with_kp = import_registry.parse("coco", self.DATA, {"keypoints": True})
        sets = [o for o in with_kp.images[0].objects
                if o["type"] == "keypoint_set"]

        assert len(sets) == 1, "one person is one annotation, not N points"
        assert sets[0]["label"] == "person"
        # All three points are kept, including the unlabelled one: its slot in
        # the ordering is what makes index 2 mean "ear".
        assert len(sets[0]["coordinates"]) == 3

    def test_visibility_flags_survive(self):
        with_kp = import_registry.parse("coco", self.DATA, {"keypoints": True})
        coords = next(o for o in with_kp.images[0].objects
                      if o["type"] == "keypoint_set")["coordinates"]
        assert [p["v"] for p in coords] == [2, 1, 0]

    def test_no_landmarks_are_emitted_any_more(self):
        with_kp = import_registry.parse("coco", self.DATA, {"keypoints": True})
        assert all(o["type"] != "landmark" for o in with_kp.images[0].objects)


class TestRleAsPolygon:

    def test_opt_in_converts_and_warns_about_fidelity(self):
        seg = {"counts": [0, 4, 4, 4, 4], "size": [4, 4]}
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": seg, "bbox": [0, 0, 4, 4]},
        ], width=4, height=4), {"rle_as_polygon": True})

        objs = result.images[0].objects
        assert objs and all(o["type"] == "polygon" for o in objs)
        assert any("Holes are dropped" in w for w in result.warnings)

    def test_default_keeps_rle_as_a_mask(self):
        seg = {"counts": [0, 4, 4, 4, 4], "size": [4, 4]}
        result = import_registry.parse("coco", _coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "segmentation": seg, "bbox": [0, 0, 4, 4]},
        ], width=4, height=4))
        assert result.images[0].objects[0]["type"] == "mask"


class TestImageUrlPrefix:

    def test_prefix_is_joined_without_doubling_slashes(self):
        result = import_registry.parse(
            "coco", _coco([]), {"image_url_prefix": "/files/"})
        assert result.images[0].extra["image_url"] == "/files/img1.jpg"

    def test_no_prefix_keeps_the_bare_file_name(self):
        result = import_registry.parse("coco", _coco([]))
        assert result.images[0].extra["image_url"] == "img1.jpg"
