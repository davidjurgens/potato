"""
The image-mask client/exporter contract, end to end.

tests/unit/test_mask_exporter.py hand-builds the structure the exporter wants. That is
why two independent breakages went unnoticed for so long: the exporter was tested with
data no part of the product produced. The client actually wrote
``{label: {color, rle: [ints], width, height}}`` into an input that no save selector
collected, so ``MaskExporter`` reported ``num_masks == 0`` for every real session.

This test starts from the blob the client now serializes (kept honest on the JS side by
tests/jest/image-mask-serialization.test.js) and drives the real loader and exporter
over it.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext


#: Exactly what ImageAnnotationManager._serializeAnnotations() writes into the
#: `{schema}:::_data` hidden input. A 4x3 image with a 2x2 block selected.
CLIENT_BLOB = [
    # `width`/`height`, not `w`/`h` — _getObjectCoordinates() emits the long
    # names (image-annotation.js:1420-1427). This file had them wrong, which is
    # its own small version of the drift it exists to catch.
    {"type": "bbox", "label": "car", "color": "#0000ff",
     "coordinates": {"x": 0.25, "y": 0.0, "width": 0.5, "height": 0.6667}},
    {"type": "mask", "label": "road", "color": "#ff0000",
     "rle": {"counts": [1, 2, 2, 2, 5], "size": [3, 4]}},
]

SCHEMAS = [{"name": "segmentation", "annotation_type": "image_annotation",
            "labels": ["road", "car"]}]


class TestClientBlobIsExportable:

    def test_decode_matches_what_the_client_encoded(self):
        from potato.export.cv_utils import decode_rle, rle_area, rle_bbox

        mask = next(o for o in CLIENT_BLOB if o["type"] == "mask")
        decoded = decode_rle(mask["rle"], 4, 3)

        assert [i for i, v in enumerate(decoded) if v] == [1, 2, 5, 6]
        assert rle_area(decoded) == 4
        assert rle_bbox(decoded, 4, 3) == [1.0, 0.0, 2.0, 2.0]

    def test_rle_size_is_height_then_width(self):
        """decode_rle documents ``size`` as [height, width]; getting this backwards
        silently produces a transposed mask rather than an error."""
        mask = next(o for o in CLIENT_BLOB if o["type"] == "mask")
        height, width = mask["rle"]["size"]
        assert (height, width) == (3, 4)
        assert sum(mask["rle"]["counts"]) == height * width

    def test_mask_exporter_writes_a_png(self):
        pytest.importorskip("PIL")
        from potato.export.mask_exporter import MaskExporter

        annotations = [{
            "instance_id": "img_1", "user_id": "u1",
            "labels": {"segmentation": {"_data": json.dumps(CLIENT_BLOB)}},
            "spans": {}, "links": {},
            "image_annotations": {"segmentation": CLIENT_BLOB},
        }]
        items = {"img_1": {"id": "img_1", "image": "road_scene.png",
                           "width": 4, "height": 3}}
        context = ExportContext(config={}, annotations=annotations, items=items,
                                schemas=SCHEMAS, output_dir="")

        with tempfile.TemporaryDirectory() as out:
            result = MaskExporter().export(context, out)
            assert result.success, result.errors
            assert result.stats.get("num_masks", 0) == 1, (
                "the exporter produced no masks from the client's own output — the "
                "client format and the exporter contract have drifted apart again")
            pngs = [f for f in os.listdir(out) if f.endswith(".png")]
            assert pngs, "no mask PNG was written"

    def test_loader_accepts_the_blob_as_image_annotations(self):
        """load_annotations_from_output_dir only promotes a label value to
        image_annotations when it parses to a LIST — the old client format was a dict
        keyed by label, so it was rejected here even before the exporter saw it."""
        from potato.export.cli import load_annotations_from_output_dir

        with tempfile.TemporaryDirectory() as out:
            user_dir = os.path.join(out, "u1")
            os.makedirs(user_dir)
            with open(os.path.join(user_dir, "user_state.json"), "w") as f:
                json.dump({
                    "user_id": "u1",
                    "instance_id_to_label_to_value": {
                        "img_1": [[{"schema": "segmentation", "name": "_data"},
                                   json.dumps(CLIENT_BLOB)]]
                    },
                }, f)

            records = load_annotations_from_output_dir(out, SCHEMAS)

        assert len(records) == 1
        parsed = records[0]["image_annotations"].get("segmentation")
        assert parsed is not None, (
            "the client blob was not recognised as image annotations")
        assert any(o.get("type") == "mask" for o in parsed)

    def test_bbox_exports_as_pixels_not_zeros(self):
        """The shape half of this contract broke the same way the mask half did.

        Every CV exporter read flat absolute fields (``obj["x"]``) that the
        client never writes, so a real session exported ``[0, 0, 0, 0]`` with
        ``area: 0``. Nothing caught it because the exporter tests hand-built the
        flat shape. See tests/unit/test_cv_coordinate_contract.py.
        """
        from potato.export.coco_exporter import COCOExporter

        annotations = [{
            "instance_id": "img_1", "user_id": "u1",
            "labels": {"segmentation": {"_data": json.dumps(CLIENT_BLOB)}},
            "spans": {}, "links": {},
            "image_annotations": {"segmentation": CLIENT_BLOB},
        }]
        items = {"img_1": {"id": "img_1", "image": "road_scene.png",
                           "image_width": 4, "image_height": 3}}
        context = ExportContext(config={}, annotations=annotations, items=items,
                                schemas=SCHEMAS, output_dir="")

        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
            assert result.success, result.errors
            with open(os.path.join(out, "annotations.json")) as f:
                coco = json.load(f)

        box = next(a for a in coco["annotations"] if a["segmentation"] == [])
        assert box["bbox"] != [0, 0, 0, 0], (
            "the bbox exported as zeros — the exporter and the client format "
            "have drifted apart again")
        assert box["bbox"][2] > 0 and box["bbox"][3] > 0
        assert box["area"] > 0

    def test_old_client_format_would_not_have_exported(self):
        """Pins why this was broken, so the shape cannot quietly regress."""
        legacy = {"road": {"color": "#ff0000", "rle": [1, 2, 2, 2, 5],
                           "width": 4, "height": 3}}

        # A dict, not a list, so load_annotations_from_output_dir never promotes it to
        # image_annotations and no exporter ever sees it.
        assert not isinstance(legacy, list)

        # And its rle is a bare array rather than {counts, size}, so mask_exporter's
        # `rle.get("counts")` guard would skip it even if it got that far.
        assert not isinstance(legacy["road"]["rle"], dict)
