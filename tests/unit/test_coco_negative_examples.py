"""An image an annotator reviewed and left empty is a negative, not missing data.

`extract_image_annotations` drops a schema whose object list is empty, and the
COCO exporter iterates annotation records and skipped anything it returned
nothing for. So an annotator who opened the image and drew nothing --

    [[{"schema": "image_annotation", "name": "_data"}, "[]"]]

-- produced no image entry at all, identical to an image nobody opened. Measured
on a four-image round trip: `potato import -f coco` gave a project with 4 items
and the export wrote `num_images: 3`, with nothing noting that 4 went in.

In COCO those are different claims. An image present with no annotations is a
NEGATIVE EXAMPLE and therefore training data; an image absent is missing data.
A detection set round-tripped through Potato lost every negative it arrived with
and every negative its annotators confirmed.

An item with no annotation record at all is a separate question and is still
dropped.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter
from potato.export.cv_utils import has_image_annotation_record


BOX = [{"type": "bbox", "label": "alpha",
        "coordinates": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}]


def record(instance_id, objects, schema="image_annotation"):
    """An annotation record as `export.cli` builds one."""
    return {"instance_id": instance_id, "user": "u1", "spans": {}, "links": {},
            "labels": {schema: {"_data": json.dumps(objects)}},
            "image_annotations": {schema: objects}}


def export(records, items):
    context = ExportContext(
        config={}, annotations=records, items=items,
        schemas=[{"annotation_type": "image_annotation",
                  "name": "image_annotation", "labels": ["alpha"]}],
        output_dir="")
    with tempfile.TemporaryDirectory() as out:
        result = COCOExporter().export(context, out)
        with open(os.path.join(out, "annotations.json")) as fh:
            return json.load(fh), result


def image_item(instance_id, name):
    return {"id": instance_id, "image_url": name,
            "image_width": 200, "image_height": 100}


class TestTheReviewedEmptyImageSurvives:

    def test_it_gets_an_image_entry(self):
        data, _ = export([record("a", [])], {"a": image_item("a", "a.png")})
        assert [i["file_name"] for i in data["images"]] == ["a.png"], (
            "an image the annotator confirmed holds nothing is a negative "
            "example, and it was dropped from the export entirely")

    def test_it_gets_no_annotations(self):
        """A negative is an image with no objects, not an image with a fake
        one."""
        data, _ = export([record("a", [])], {"a": image_item("a", "a.png")})
        assert data["annotations"] == []

    def test_its_dimensions_are_written(self):
        data, _ = export([record("a", [])], {"a": image_item("a", "a.png")})
        assert (data["images"][0]["width"], data["images"][0]["height"]) == (
            200, 100)

    def test_it_sits_alongside_annotated_images(self):
        data, _ = export(
            [record("c", BOX), record("a", [])],
            {"c": image_item("c", "c.png"), "a": image_item("a", "a.png")})
        assert sorted(i["file_name"] for i in data["images"]) == [
            "a.png", "c.png"]
        assert len(data["annotations"]) == 1

    def test_image_ids_stay_unique(self):
        data, _ = export(
            [record("c", BOX), record("a", [])],
            {"c": image_item("c", "c.png"), "a": image_item("a", "a.png")})
        ids = [i["id"] for i in data["images"]]
        assert len(ids) == len(set(ids))

    def test_the_annotation_still_points_at_its_own_image(self):
        """Minting an extra image must not misalign the image_id references."""
        data, _ = export(
            [record("c", BOX), record("a", [])],
            {"c": image_item("c", "c.png"), "a": image_item("a", "a.png")})
        by_id = {i["id"]: i["file_name"] for i in data["images"]}
        assert by_id[data["annotations"][0]["image_id"]] == "c.png"


class TestNonImageRecordsAreStillExcluded:

    def test_a_text_only_record_mints_no_image(self):
        text_record = {"instance_id": "z", "user": "u1", "spans": {},
                       "links": {}, "labels": {"sentiment": {"label": "pos"}},
                       "image_annotations": {}}
        data, _ = export([text_record], {"z": {"id": "z", "text": "no image"}})
        assert data["images"] == [], (
            "a study with no image schema would acquire an images list")

    def test_a_record_with_no_image_annotations_key_mints_no_image(self):
        bare = {"instance_id": "z", "user": "u1", "spans": {}, "links": {},
                "labels": {}}
        data, _ = export([bare], {"z": {"id": "z"}})
        assert data["images"] == []


class TestTheWarningAgreesWithTheFile:
    """The absent-items warning names what is missing. Exporting the negative
    without teaching the warning about it would have had the warning call an
    item absent from a file it is in, which is worse than the silence it
    replaced."""

    def test_a_reviewed_empty_item_is_not_called_absent(self):
        data, result = export(
            [record("a", [])],
            {"a": image_item("a", "a.png"),
             "never": image_item("never", "never.png")})
        written = {i["file_name"] for i in data["images"]}
        assert "a.png" in written
        joined = " ".join(result.warnings)
        assert "never" in joined, "the item nobody opened must still be named"
        assert not any(w.startswith("2 item(s)") for w in result.warnings), (
            "the warning counted an item it had just written to the file")

    def test_nothing_is_warned_when_every_item_is_covered(self):
        _data, result = export([record("a", [])], {"a": image_item("a", "a.png")})
        assert not any("absent from" in w for w in result.warnings)

    def test_every_named_item_really_is_missing(self):
        """The general form: nothing the warning names may appear in
        `images`."""
        data, result = export(
            [record("c", BOX), record("a", [])],
            {"c": image_item("c", "c.png"), "a": image_item("a", "a.png"),
             "never": image_item("never", "never.png")})
        written = {i["file_name"] for i in data["images"]}
        for warning in result.warnings:
            if "absent from" not in warning:
                continue
            named = warning.split(":", 1)[1].split(".")[0]
            for token in named.replace(",", " ").split():
                assert f"{token}.png" not in written, (
                    f"{token} is named as absent and is in the file")


class TestTheReviewTest:
    """`has_image_annotation_record` is what separates the two cases."""

    def test_an_empty_list_counts_as_reviewed(self):
        assert has_image_annotation_record(record("a", [])) is True

    def test_a_populated_list_counts_as_reviewed(self):
        assert has_image_annotation_record(record("c", BOX)) is True

    @pytest.mark.parametrize("annotation", [
        {"image_annotations": {}},
        {"image_annotations": None},
        {"image_annotations": "not a dict"},
        {},
    ])
    def test_no_image_schema_is_not_reviewed(self, annotation):
        assert has_image_annotation_record(annotation) is False

    def test_a_non_list_value_is_not_reviewed(self):
        """A malformed value is not evidence that anyone looked."""
        assert has_image_annotation_record(
            {"image_annotations": {"s": "oops"}}) is False
