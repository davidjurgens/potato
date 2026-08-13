"""
The coordinate contract between the browser and the CV exporters.

Every CV exporter used to read flat, absolute-pixel fields (``obj["x"]``,
``obj["points"]``) that ``ImageAnnotationManager._serializeAnnotations()`` has
never written. The client writes normalized coordinates nested under
``coordinates``. The result was that real annotation sessions exported bboxes
as ``[0, 0, 0, 0]`` with ``area: 0``, and polygons hit ``if not points:
continue`` and vanished silently. Only masks survived, because the mask half of
the contract had already been fixed.

The existing exporter tests hand-built the flat shape, so they passed the whole
time. That is the same failure mode ``test_mask_client_contract.py`` was written
to catch, one layer up.

Every test here starts from the shape the client actually emits.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.cv_utils import (
    build_coco_category_map,
    normalize_annotation_object,
    to_client_object,
)


#: Exactly what _serializeAnnotations() writes for a 640x480 image.
#: bbox  -> x=64, y=48, w=128, h=96 in pixels
#: polygon -> (64,48) (192,48) (192,144) (64,144) in pixels
CLIENT_BLOB = [
    {"type": "bbox", "label": "cat", "color": "#f00",
     "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}},
    {"type": "polygon", "label": "dog", "color": "#0f0",
     "coordinates": [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1},
                     {"x": 0.3, "y": 0.3}, {"x": 0.1, "y": 0.3}]},
    {"type": "landmark", "label": "cat", "color": "#00f",
     "coordinates": {"x": 0.5, "y": 0.25}},
]

IMG_W, IMG_H = 640, 480

SCHEMAS = [{
    "name": "img", "annotation_type": "image_annotation",
    "labels": [{"name": "cat"}, {"name": "dog"}],
}]


def _flat(points):
    """pytest.approx cannot compare nested sequences; compare flattened."""
    return [c for p in points for c in p]


class TestNormalizeReadsTheClientShape:

    def test_bbox_denormalizes_to_pixels(self):
        canon = normalize_annotation_object(CLIENT_BLOB[0], IMG_W, IMG_H)
        assert canon["bbox"] == pytest.approx([64.0, 48.0, 128.0, 96.0])
        assert canon["area"] == pytest.approx(128.0 * 96.0)

    def test_polygon_coordinates_are_objects_not_pairs(self):
        """The client emits [{x, y}, ...]; cv_utils' polygon helpers want
        [[x, y], ...]. Reading obj["points"] returns nothing at all."""
        assert "points" not in CLIENT_BLOB[1]
        canon = normalize_annotation_object(CLIENT_BLOB[1], IMG_W, IMG_H)
        assert _flat(canon["points"]) == pytest.approx(
            _flat([[64.0, 48.0], [192.0, 48.0], [192.0, 144.0], [64.0, 144.0]]))
        assert canon["bbox"] == pytest.approx([64.0, 48.0, 128.0, 96.0])

    def test_landmark_denormalizes(self):
        canon = normalize_annotation_object(CLIENT_BLOB[2], IMG_W, IMG_H)
        assert _flat(canon["points"]) == pytest.approx(_flat([[320.0, 120.0]]))

    def test_bbox_accepts_w_h_aliases(self):
        """Some fixtures write w/h rather than width/height."""
        obj = {"type": "bbox", "label": "cat",
               "coordinates": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}}
        canon = normalize_annotation_object(obj, IMG_W, IMG_H)
        assert canon["bbox"] == pytest.approx([64.0, 48.0, 128.0, 96.0])

    def test_mask_rle_passes_through_untouched(self):
        obj = {"type": "mask", "label": "cat",
               "rle": {"counts": [2, 3, 1], "size": [2, 3]}}
        canon = normalize_annotation_object(obj, 3, 2)
        assert canon["rle"] is obj["rle"]
        assert canon["area"] == 3
        assert canon["iscrowd"] == 1, "a label-keyed brush mask is crowd-like"

    def test_mask_keeps_explicit_iscrowd_zero(self):
        """Imported per-instance masks must not be relabelled as crowd."""
        obj = {"type": "mask", "label": "cat", "iscrowd": 0, "instance": 2,
               "rle": {"counts": [2, 3, 1], "size": [2, 3]}}
        canon = normalize_annotation_object(obj, 3, 2)
        assert canon["iscrowd"] == 0
        assert canon["instance"] == 2


class TestLegacyAbsoluteShapeStillWorks:
    """Pre-2.x data and hand-written fixtures use flat absolute pixels."""

    def test_flat_bbox_is_passed_through(self):
        obj = {"type": "bbox", "label": "cat",
               "x": 10, "y": 20, "width": 100, "height": 50}
        canon = normalize_annotation_object(obj, IMG_W, IMG_H)
        assert canon["bbox"] == pytest.approx([10.0, 20.0, 100.0, 50.0])

    def test_flat_polygon_pairs_are_passed_through(self):
        obj = {"type": "polygon", "label": "cat",
               "points": [[10, 10], [100, 10], [100, 80], [10, 80]]}
        canon = normalize_annotation_object(obj, IMG_W, IMG_H)
        assert canon["bbox"] == pytest.approx([10.0, 10.0, 90.0, 70.0])


class TestNormalizedVersusAbsoluteIsStructural:
    """The two spaces cannot be told apart by magnitude, only by structure."""

    def test_unit_box_at_origin_is_ambiguous_by_value(self):
        """A 1x1 pixel box at the origin is [0, 0, 1, 1] in BOTH spaces.
        Any magnitude heuristic gets exactly one of these wrong."""
        normalized = {"type": "bbox", "label": "cat",
                      "coordinates": {"x": 0, "y": 0, "width": 1, "height": 1}}
        absolute = {"type": "bbox", "label": "cat",
                    "x": 0, "y": 0, "width": 1, "height": 1}

        # Same numbers in, different pixels out — decided by the presence of
        # the `coordinates` key, never by how large the values look.
        assert normalize_annotation_object(normalized, 640, 480)["bbox"] == \
            pytest.approx([0.0, 0.0, 640.0, 480.0])
        assert normalize_annotation_object(absolute, 640, 480)["bbox"] == \
            pytest.approx([0.0, 0.0, 1.0, 1.0])


class TestRoundTripProperty:
    """normalize(to_client(x)) == x for every geometry type."""

    @pytest.mark.parametrize("obj_type,kwargs,expect_bbox", [
        ("bbox", {"bbox": [64.0, 48.0, 128.0, 96.0]}, [64.0, 48.0, 128.0, 96.0]),
        ("polygon", {"points": [[10.0, 10.0], [100.0, 10.0], [100.0, 80.0]]},
         [10.0, 10.0, 90.0, 70.0]),
        ("landmark", {"points": [[320.0, 120.0]]}, [320.0, 120.0, 0.0, 0.0]),
    ])
    def test_to_client_then_normalize_is_identity(self, obj_type, kwargs,
                                                  expect_bbox):
        client = to_client_object(obj_type, "cat", "#f00",
                                  img_w=IMG_W, img_h=IMG_H, **kwargs)
        assert "coordinates" in client, "to_client_object must emit the client shape"
        canon = normalize_annotation_object(client, IMG_W, IMG_H)
        assert canon["bbox"] == pytest.approx(expect_bbox)
        if "points" in kwargs:
            assert _flat(canon["points"]) == pytest.approx(_flat(kwargs["points"]))

    def test_mask_round_trips_untouched(self):
        rle = {"counts": [2, 3, 1], "size": [2, 3]}
        client = to_client_object("mask", "cat", "#f00", img_w=3, img_h=2, rle=rle)
        assert client["rle"] == rle
        assert normalize_annotation_object(client, 3, 2)["rle"] == rle


class TestSparseCocoCategoryIds:
    """COCO 2017 uses IDs 1..90 with gaps. Renumbering them densely means a
    file cannot survive an import/export round trip."""

    def test_label_id_is_preserved(self):
        schemas = [{
            "name": "img", "annotation_type": "image_annotation",
            "labels": [
                {"name": "person", "label_id": 1, "supercategory": "person"},
                {"name": "dog", "label_id": 18, "supercategory": "animal"},
                {"name": "toothbrush", "label_id": 90},
            ],
        }]
        mapping, categories = build_coco_category_map(schemas, [])
        assert mapping == {"person": 1, "dog": 18, "toothbrush": 90}
        assert [c["id"] for c in categories] == [1, 18, 90]
        assert categories[1]["supercategory"] == "animal"

    def test_labels_without_ids_do_not_collide_with_explicit_ones(self):
        schemas = [{
            "name": "img", "annotation_type": "image_annotation",
            "labels": [{"name": "dog", "label_id": 18}, {"name": "novel"}],
        }]
        mapping, _ = build_coco_category_map(schemas, [])
        assert mapping["dog"] == 18
        assert mapping["novel"] > 18

    def test_defaults_to_one_indexed_when_no_label_ids(self):
        """Preserves the historical numbering for configs written by hand."""
        mapping, _ = build_coco_category_map(SCHEMAS, [])
        assert mapping == {"cat": 1, "dog": 2}


class TestExportersConsumeTheClientBlob:
    """The end-to-end proof. Each of these produced zeros or nothing before."""

    def _context(self):
        return ExportContext(
            config={},
            annotations=[{
                "instance_id": "img1", "user_id": "u1",
                "labels": {"img": {"_data": json.dumps(CLIENT_BLOB)}},
                "spans": {}, "links": {},
                "image_annotations": {"img": CLIENT_BLOB},
            }],
            items={"img1": {"id": "img1", "image": "cat.jpg",
                            "image_width": IMG_W, "image_height": IMG_H}},
            schemas=SCHEMAS,
            output_dir="",
        )

    def test_coco_exports_real_geometry(self):
        from potato.export.coco_exporter import COCOExporter

        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(self._context(), out)
            assert result.success
            with open(os.path.join(out, "annotations.json")) as f:
                coco = json.load(f)

        # landmark is skipped by COCO, so bbox + polygon remain
        assert len(coco["annotations"]) == 2

        box = next(a for a in coco["annotations"] if a["segmentation"] == [])
        assert box["bbox"] == pytest.approx([64.0, 48.0, 128.0, 96.0]), (
            "bbox exported as zeros — the exporter is reading fields the client "
            "never writes")
        assert box["area"] > 0

        poly = next(a for a in coco["annotations"] if a["segmentation"] != [])
        assert poly["segmentation"] == [pytest.approx(
            [64.0, 48.0, 192.0, 48.0, 192.0, 144.0, 64.0, 144.0])]
        assert poly["area"] > 0

    def test_yolo_exports_real_geometry(self):
        from potato.export.yolo_exporter import YOLOExporter

        with tempfile.TemporaryDirectory() as out:
            result = YOLOExporter().export(self._context(), out)
            assert result.success
            label_file = os.path.join(out, "labels", "cat.txt")
            assert os.path.exists(label_file)
            lines = [l for l in open(label_file).read().splitlines() if l.strip()]

        assert lines, "no YOLO rows written"
        for line in lines:
            parts = line.split()
            cx, cy, nw, nh = (float(p) for p in parts[1:5])
            assert nw > 0 and nh > 0, f"degenerate YOLO box: {line}"
            assert 0 <= cx <= 1 and 0 <= cy <= 1

    def test_pascal_voc_exports_real_geometry(self):
        import xml.etree.ElementTree as ET
        from potato.export.pascal_voc_exporter import PascalVOCExporter

        with tempfile.TemporaryDirectory() as out:
            result = PascalVOCExporter().export(self._context(), out)
            assert result.success
            tree = ET.parse(os.path.join(out, "cat.xml"))

        boxes = tree.getroot().findall("object")
        assert boxes, "no VOC objects written"
        for obj in boxes:
            bnd = obj.find("bndbox")
            xmin = int(bnd.find("xmin").text)
            xmax = int(bnd.find("xmax").text)
            ymin = int(bnd.find("ymin").text)
            ymax = int(bnd.find("ymax").text)
            assert xmax > xmin and ymax > ymin, "degenerate VOC box"
