"""
COCO in, COCO out.

The single most valuable test for the importer: parse a COCO file covering
every segmentation encoding, export it back, and assert the geometry survived.

Runs entirely in-process. It does NOT go through the annotation UI, because
imported annotations are pre-annotations -- they are deliberately not written
into anyone's user_state until a human saves, so an import->serve->export cycle
with no annotator would correctly produce an empty file.

Tolerances, and why they differ by type:

- bbox / polygon: within 1e-6 relative. The client stores normalized [0, 1]
  coordinates, so a round trip is a float division followed by a multiplication
  -- 10 / 640 * 640 == 10.000000000000002.
- masks: EXACT pixel equality. RLE passes through as integer counts and has no
  excuse to move at all.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter
from potato.export.cv_utils import decode_rle, rle_to_coco_rle
from potato.importers import import_registry

SCHEMA = "object_detection"
W, H = 64, 48


def _compressed_rle(rect):
    """A COCO compressed-RLE segmentation for an (x0, y0, x1, y1) rect."""
    x0, y0, x1, y1 = rect
    bitmap = [0] * (W * H)
    for y in range(y0, y1):
        for x in range(x0, x1):
            bitmap[y * W + x] = 1
    counts, current, run = [], 0, 0
    for v in bitmap:
        if v == current:
            run += 1
        else:
            counts.append(run)
            current = 1 - current
            run = 1
    counts.append(run)
    return rle_to_coco_rle({"counts": counts, "size": [H, W]}, W, H)


def _uncompressed_rle(rect):
    seg = _compressed_rle(rect)
    from potato.export.cv_utils import _decode_coco_rle_string
    return {"counts": _decode_coco_rle_string(seg["counts"]), "size": seg["size"]}


def _source_coco(annotations):
    return {
        "images": [
            {"id": 1, "file_name": "a.jpg", "width": W, "height": H},
            {"id": 2, "file_name": "b.jpg", "width": W, "height": H},
        ],
        # Sparse ids, as COCO 2017 uses.
        "categories": [
            {"id": 1, "name": "person", "supercategory": "person"},
            {"id": 18, "name": "dog", "supercategory": "animal"},
            {"id": 90, "name": "toothbrush", "supercategory": "indoor"},
        ],
        "annotations": annotations,
    }


#: One annotation per encoding, no multi-ring (which legitimately splits).
CANONICAL = [
    {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
     "bbox": [8, 10, 20, 24], "segmentation": []},
    {"id": 2, "image_id": 1, "category_id": 18, "iscrowd": 0,
     "bbox": [36, 16, 20, 16],
     "segmentation": [[36, 16, 56, 16, 56, 32, 36, 32]]},
    {"id": 3, "image_id": 2, "category_id": 1, "iscrowd": 0,
     "bbox": [38, 20, 20, 20], "segmentation": _uncompressed_rle((38, 20, 58, 40))},
    {"id": 4, "image_id": 2, "category_id": 1, "iscrowd": 0,
     "bbox": [4, 4, 8, 8], "segmentation": _compressed_rle((4, 4, 12, 12))},
    {"id": 5, "image_id": 2, "category_id": 90, "iscrowd": 1,
     "bbox": [0, 40, 64, 8], "segmentation": _compressed_rle((0, 40, 64, 48))},
]


def _roundtrip(source, options=None):
    """import -> ExportContext -> export, returning the exported COCO dict."""
    result = import_registry.parse("coco", source, options or {})

    annotations = [{
        "instance_id": img.instance_id,
        "user_id": "importer",
        "labels": {SCHEMA: {"_data": json.dumps(img.objects)}},
        "spans": {}, "links": {},
        "image_annotations": {SCHEMA: img.objects},
    } for img in result.images]

    items = {
        img.instance_id: {
            "id": img.instance_id,
            "file_name": img.file_name,
            "image_width": img.width,
            "image_height": img.height,
        }
        for img in result.images
    }

    schemas = [{
        "annotation_type": "image_annotation",
        "name": SCHEMA,
        "labels": result.labels,
    }]

    context = ExportContext(config={}, annotations=annotations, items=items,
                            schemas=schemas, output_dir="")
    with tempfile.TemporaryDirectory() as out:
        export_result = COCOExporter().export(context, out)
        assert export_result.success, export_result.errors
        with open(os.path.join(out, "annotations.json")) as f:
            return json.load(f), result


def _bitmap(seg, width=W, height=H):
    """Decode any COCO segmentation dict to a flat row-major bitmap."""
    from potato.export.cv_utils import coco_rle_to_rle
    return decode_rle(coco_rle_to_rle(seg), width, height)


class TestCanonicalRoundTrip:

    def setup_method(self):
        self.exported, self.imported = _roundtrip(_source_coco(CANONICAL))
        self.source = _source_coco(CANONICAL)

    def test_categories_survive_including_sparse_ids(self):
        got = {(c["id"], c["name"], c.get("supercategory", ""))
               for c in self.exported["categories"]}
        want = {(c["id"], c["name"], c.get("supercategory", ""))
                for c in self.source["categories"]}
        assert got == want, "sparse COCO category ids were renumbered"

    def test_images_survive(self):
        got = {(i["file_name"], i["width"], i["height"])
               for i in self.exported["images"]}
        want = {(i["file_name"], i["width"], i["height"])
                for i in self.source["images"]}
        assert got == want

    def test_annotation_counts_match_per_image_category_and_crowd(self):
        def key_counts(anns, id_to_file):
            out = {}
            for a in anns:
                k = (id_to_file[a["image_id"]], a["category_id"], a["iscrowd"])
                out[k] = out.get(k, 0) + 1
            return out

        src_files = {i["id"]: i["file_name"] for i in self.source["images"]}
        exp_files = {i["id"]: i["file_name"] for i in self.exported["images"]}

        assert key_counts(self.exported["annotations"], exp_files) == \
            key_counts(self.source["annotations"], src_files)

    def test_bbox_only_annotation_keeps_its_box(self):
        src = self.source["annotations"][0]
        match = [a for a in self.exported["annotations"]
                 if a["category_id"] == 1 and a["segmentation"] == []]
        assert len(match) == 1
        assert match[0]["bbox"] == pytest.approx(src["bbox"], rel=1e-6)
        assert match[0]["area"] == pytest.approx(20 * 24, rel=1e-6)

    def test_polygon_vertices_survive(self):
        src = self.source["annotations"][1]
        match = [a for a in self.exported["annotations"]
                 if a["category_id"] == 18]
        assert len(match) == 1
        got = match[0]["segmentation"]
        assert len(got) == 1
        assert got[0] == pytest.approx(src["segmentation"][0], rel=1e-6)
        assert len(got[0]) == len(src["segmentation"][0])

    @pytest.mark.parametrize("index", [2, 3, 4])
    def test_masks_are_pixel_exact(self, index):
        """RLE passes through as integer counts; any drift at all is a bug."""
        src = self.source["annotations"][index]
        src_bitmap = _bitmap(src["segmentation"])

        candidates = [a for a in self.exported["annotations"]
                      if isinstance(a["segmentation"], dict)]
        assert candidates, "no mask survived the round trip"

        assert any(_bitmap(a["segmentation"]) == src_bitmap for a in candidates), (
            f"annotation {src['id']} did not round-trip to an identical mask")

    def test_mask_area_and_bbox_are_exact(self):
        src = self.source["annotations"][2]
        src_bitmap = _bitmap(src["segmentation"])
        match = next(a for a in self.exported["annotations"]
                     if isinstance(a["segmentation"], dict)
                     and _bitmap(a["segmentation"]) == src_bitmap)
        assert match["area"] == sum(src_bitmap)
        assert match["bbox"] == [38.0, 20.0, 20.0, 20.0]

    def test_two_instances_of_one_class_stay_separate(self):
        """Annotations 3 and 4 are both `person` masks. Merging them would
        destroy exactly the instance segmentation this import exists for."""
        person_masks = [a for a in self.exported["annotations"]
                        if a["category_id"] == 1
                        and isinstance(a["segmentation"], dict)
                        and a["iscrowd"] == 0]
        assert len(person_masks) == 2
        assert _bitmap(person_masks[0]["segmentation"]) != \
            _bitmap(person_masks[1]["segmentation"])

    def test_crowd_flag_survives(self):
        crowd = [a for a in self.exported["annotations"] if a["iscrowd"] == 1]
        assert len(crowd) == 1
        assert crowd[0]["category_id"] == 90


class TestStability:

    def test_second_and_third_passes_are_byte_identical(self):
        """export -> import -> export must converge, not drift."""
        first, _ = _roundtrip(_source_coco(CANONICAL))
        second, _ = _roundtrip(first)
        third, _ = _roundtrip(second)
        assert json.dumps(second, sort_keys=True) == \
            json.dumps(third, sort_keys=True)


class TestDocumentedLossyBehaviour:
    """Where the round trip is NOT identity, assert the documented behaviour
    rather than quietly tolerating drift."""

    def test_multi_ring_polygon_becomes_one_annotation_per_ring(self):
        source = _source_coco([
            {"id": 1, "image_id": 1, "category_id": 90, "iscrowd": 0,
             "bbox": [10, 8, 20, 32],
             "segmentation": [[10, 8, 30, 8, 30, 40, 10, 40],
                              [16, 16, 24, 16, 24, 24, 16, 24]]},
        ])
        exported, imported = _roundtrip(source)

        # One source annotation with two rings -> two exported annotations.
        assert len(exported["annotations"]) == 2
        assert all(len(a["segmentation"]) == 1 for a in exported["annotations"])
        assert any("Multi-ring" in w for w in imported.warnings)

        # Both rings survive with their geometry intact; only their grouping
        # into a single annotation is lost.
        got = [a["segmentation"][0] for a in exported["annotations"]]
        for want in source["annotations"][0]["segmentation"]:
            assert any(ring == pytest.approx(want, rel=1e-6) for ring in got), (
                f"ring {want} did not survive the round trip")

    def test_crowd_regions_of_one_class_merge_to_a_single_annotation(self):
        """COCO permits at most one crowd annotation per category per image, so
        merging is correct -- but it is still a many-to-one, so pin it."""
        source = _source_coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "bbox": [0, 0, 8, 8], "segmentation": _compressed_rle((0, 0, 8, 8))},
            {"id": 2, "image_id": 1, "category_id": 1, "iscrowd": 1,
             "bbox": [20, 20, 8, 8],
             "segmentation": _compressed_rle((20, 20, 28, 28))},
        ])
        exported, _ = _roundtrip(source)

        assert len(exported["annotations"]) == 1
        merged = _bitmap(exported["annotations"][0]["segmentation"])
        # Union of both source regions, no more and no less.
        assert sum(merged) == 8 * 8 * 2

    def test_rle_as_polygon_changes_the_encoding_by_request(self):
        source = _source_coco([
            {"id": 1, "image_id": 1, "category_id": 1, "iscrowd": 0,
             "bbox": [4, 4, 8, 8], "segmentation": _compressed_rle((4, 4, 12, 12))},
        ])
        exported, imported = _roundtrip(source, {"rle_as_polygon": True})

        assert all(isinstance(a["segmentation"], list)
                   for a in exported["annotations"])
        assert any("Holes are dropped" in w for w in imported.warnings)


class TestTheGeneratedExample:
    """The shipped example must actually round-trip, not just parse."""

    def test_example_fixture_survives(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "examples", "image", "coco-import",
            "data", "annotations", "instances_sample.json")
        if not os.path.exists(path):
            pytest.skip("example fixture not present")

        with open(path) as f:
            source = json.load(f)

        exported, imported = _roundtrip(source)

        assert {c["id"] for c in exported["categories"]} == {1, 18, 90}
        assert len(exported["images"]) == 3
        # The crowd annotation V7 would have dropped is present.
        assert any(a["iscrowd"] == 1 for a in exported["annotations"])
        # Both person instances on image 2 survived as separate masks.
        person_masks = [a for a in exported["annotations"]
                        if a["category_id"] == 1
                        and isinstance(a["segmentation"], dict)
                        and a["iscrowd"] == 0]
        assert len(person_masks) == 2
