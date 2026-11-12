"""
CV exports wrote `"width": 0, "height": 0` for any item that did not declare
its own dimensions.

Audit 26. The auditor's COCO export carried

    "images": [{"id": 1, "file_name": "scan.png", "width": 0, "height": 0}]
    "annotations": [{..., "segmentation": {"size": [400, 640], ...}}]

The annotation knows the size and the image record does not, so the mask
decodes correctly -- `annToMask` reads the segmentation's own size -- and the
file survives a casual check. Anything reading `img['width']` gets zero:
coordinate normalization, detector training, visualization, COCOeval.

`get_image_dimensions` reads item metadata keys and nothing else, and returns
`(0, 0)` when they are absent. That is the ordinary case for a study built in
Potato: the data file names an image, it does not describe one. Every existing
COCO test supplies `image_width`/`image_height`, which is why nothing caught
it.

Eleven exporters call that function. YOLO refuses the export with a clear
message when the dimensions are missing, which is the right behavior and shows
the condition was known; COCO wrote zeros. The dimensions are now derived --
from a mask's own RLE size, or by reading the image file -- so the refusal and
the zeros both become rare.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter
from potato.export.cv_utils import get_image_dimensions


def _write_png(directory, name="scan.png", width=640, height=400):
    from PIL import Image
    media = os.path.join(directory, "media")
    os.makedirs(media, exist_ok=True)
    Image.new("RGB", (width, height), (10, 20, 30)).save(
        os.path.join(media, name))
    return name


def _mask_annotation(instance_id="img1"):
    """A stored mask, in the shape the manager persists.

    `size` is `[height, width]`, which is where the true dimensions are when
    the item itself does not carry them.
    """
    return {
        "instance_id": instance_id,
        "user_id": "user1",
        "image_annotations": {
            "img": [{
                "type": "mask",
                "label": "affected",
                "rle": {"size": [400, 640], "counts": [256000]},
            }]
        },
    }


class TestDimensionsComeFromTheData:

    def test_metadata_still_wins(self):
        """The declared value is authoritative and cheapest."""
        item = {"image": "scan.png", "image_width": 800, "image_height": 600}
        assert get_image_dimensions(item) == (800, 600)

    def test_an_undescribed_item_still_resolves_from_the_file(self, tmp_path):
        """A data file that names an image does not describe one.

        This is the ordinary shape of a study built in Potato, and it is what
        produced the zeros.
        """
        name = _write_png(str(tmp_path))
        dimensions = get_image_dimensions(
            {"image": name},
            config={"task_dir": str(tmp_path), "media_directory": "media"})
        assert dimensions == (640, 400), dimensions

    def test_a_mask_supplies_its_own_size_without_touching_the_disk(self):
        """The RLE carries `[height, width]`, so a mask export needs no file.

        Asserted separately because it is the path that works when the image
        is remote, missing, or served from somewhere the exporter cannot read.
        """
        dimensions = get_image_dimensions(
            {"image": "unreachable.png"},
            annotation=_mask_annotation())
        assert dimensions == (640, 400), dimensions

    def test_nothing_to_go_on_still_returns_zeros(self):
        """The control. Callers like YOLO refuse on zero, and that refusal has
        to keep working when there is genuinely no way to know."""
        assert get_image_dimensions({"image": "nope.png"}) == (0, 0)


class TestCOCOExportCarriesTheDimensions:

    def test_the_image_record_is_not_zeroed(self, tmp_path):
        """The finding, end to end.

        Asserting the image record rather than the segmentation: the
        segmentation was already right, which is what made this survive.
        """
        name = _write_png(str(tmp_path))
        context = ExportContext(
            config={"task_dir": str(tmp_path), "media_directory": "media"},
            annotations=[_mask_annotation()],
            items={"img1": {"image": name}},
            schemas=[{"annotation_type": "image_annotation", "name": "img",
                      "labels": [{"name": "affected"}]}],
            output_dir="",
        )
        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
            assert result.success, result
            with open(os.path.join(out, "annotations.json")) as handle:
                coco = json.load(handle)

        image = coco["images"][0]
        assert image["width"] == 640, coco["images"]
        assert image["height"] == 400, coco["images"]

    def test_several_images_each_get_their_own_size(self, tmp_path):
        """The auditor asked whether the zeros were specific to one image.

        Two items of different sizes: a per-item lookup that had regressed to
        a single cached value would give both the same answer.
        """
        _write_png(str(tmp_path), "a.png", 640, 400)
        _write_png(str(tmp_path), "b.png", 320, 240)
        annotations = [_mask_annotation("a"), {
            "instance_id": "b",
            "user_id": "user1",
            "image_annotations": {"img": [
                {"type": "bbox", "label": "affected",
                 "x": 1, "y": 2, "width": 3, "height": 4}]},
        }]
        context = ExportContext(
            config={"task_dir": str(tmp_path), "media_directory": "media"},
            annotations=annotations,
            items={"a": {"image": "a.png"}, "b": {"image": "b.png"}},
            schemas=[{"annotation_type": "image_annotation", "name": "img",
                      "labels": [{"name": "affected"}]}],
            output_dir="",
        )
        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
            assert result.success, result
            with open(os.path.join(out, "annotations.json")) as handle:
                coco = json.load(handle)

        sizes = {img["file_name"]: (img["width"], img["height"])
                 for img in coco["images"]}
        assert sizes == {"a.png": (640, 400), "b.png": (320, 240)}, sizes


class TestBlankItemsAreReported:
    """An item nobody marked is absent from every CV export.

    Audit 27. The auditor's three-image study exported two images from every
    one of eleven formats; `grep -rl street3` across all of them returned
    nothing -- not even an image entry with an empty annotation list. Each
    exporter walks `context.annotations`, so an item with no marks produces no
    record at all.

    Whether it SHOULD be there is a real design question and differs by format:
    most of these are annotation interchange rather than dataset manifests, and
    an empty entry is noise in several of them. What is not defensible is the
    silence. A researcher reconciling "I had 300 images" against a COCO file
    listing 214 cannot tell whether the rest errored or were simply blank, and
    for detector training an image with no objects is a negative example rather
    than a missing one.
    """

    def _context(self, tmp_path, annotated_ids, all_ids):
        name = _write_png(str(tmp_path))
        return ExportContext(
            config={"task_dir": str(tmp_path), "media_directory": "media"},
            annotations=[_mask_annotation(iid) for iid in annotated_ids],
            items={iid: {"image": name} for iid in all_ids},
            schemas=[{"annotation_type": "image_annotation", "name": "img",
                      "labels": [{"name": "affected"}]}],
            output_dir="",
        )

    def test_an_unmarked_item_is_named_in_the_warnings(self, tmp_path):
        context = self._context(tmp_path, ["a"], ["a", "b", "c"])
        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
        assert result.success
        blank = [w for w in result.warnings if "no image annotation" in w]
        assert blank, result.warnings
        assert "b" in blank[0] and "c" in blank[0], blank
        assert "2 item(s)" in blank[0], blank

    def test_a_study_where_everything_was_marked_says_nothing(self, tmp_path):
        """The control. A warning that always fires is not a warning."""
        context = self._context(tmp_path, ["a", "b"], ["a", "b"])
        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
        assert result.success
        assert not [w for w in result.warnings if "no image annotation" in w], \
            result.warnings

    def test_the_export_still_succeeds_and_still_writes_the_marked_images(
            self, tmp_path):
        """The warning reports; it does not refuse. The blank items are a
        judgment call for the researcher, not an error."""
        context = self._context(tmp_path, ["a"], ["a", "b", "c"])
        with tempfile.TemporaryDirectory() as out:
            result = COCOExporter().export(context, out)
            with open(os.path.join(out, "annotations.json")) as handle:
                coco = json.load(handle)
        assert result.success
        assert [img["id"] for img in coco["images"]] == [1], coco["images"]
