"""The exporters ask the config where the media is before guessing.

`get_image_filename` located the image by trying six field names:

    for key in ("image", "image_path", "image_url", "file_name", "filename", "img"):

`source_field` -- the scheme key whose only job is to say which field holds the
media, and which the display layer honours -- was not among them. So a study
whose field is called anything else exported `file_name: "<instance id>"`, and
with no filename there is no file, with no file there are no dimensions, and
the client stores normalized coordinates, so every box multiplied by zero and
landed at the origin.

Paired control, one image, one box, one field renamed:

    source_field: pic         file_name "img1"              [0, 0, 0, 0]
    source_field: image_url   file_name "/media/scene.png"  [40, 40, 120, 120]

The page rendered the image correctly in both, and the geometry pipeline was
never wrong -- an arm with explicit `image_width`/`image_height` exported the
right box even under the broken lookup.

This is the fourth time a media field has been known to the display layer and
not to a consumer: `source_field` without `instance_display`, `/media/...`
refused by the waveform containment check, `generate_waveform` on video, and
this. Each time a different function had rediscovered the same lookup badly.
"""

import json
import os
import tempfile

import pytest

from potato.export.base import ExportContext
from potato.export.coco_exporter import COCOExporter
from potato.export.cv_utils import _configured_media_keys, get_image_filename


BOX = [{"type": "bbox", "label": "obj",
        "coordinates": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6}}]


def scheme(field, annotation_type="image_annotation"):
    return {"annotation_type": annotation_type, "name": "boxes",
            "source_field": field, "labels": ["obj"]}


@pytest.fixture
def project(tmp_path):
    from PIL import Image

    media = tmp_path / "media"
    media.mkdir()
    Image.new("RGB", (200, 200), (240, 240, 240)).save(media / "scene.png")

    from potato.export import cv_utils

    cv_utils._DIMENSION_CACHE.clear()
    cv_utils._UNMEASURABLE_SEEN.clear()
    return tmp_path


def export_with(project, field):
    config = {"task_dir": str(project), "media_directory": "media",
              "annotation_schemes": [scheme(field)]}
    annotation = {"instance_id": "img1", "user": "u1", "spans": {}, "links": {},
                  "labels": {"boxes": {"_data": json.dumps(BOX)}},
                  "image_annotations": {"boxes": BOX}}
    context = ExportContext(
        config=config, annotations=[annotation],
        items={"img1": {"id": "img1", field: "/media/scene.png"}},
        schemas=config["annotation_schemes"], output_dir="")
    with tempfile.TemporaryDirectory() as out:
        result = COCOExporter().export(context, out)
        with open(os.path.join(out, "annotations.json")) as fh:
            data = json.load(fh)
    return data, result


class TestAnyFieldNameWorks:

    @pytest.mark.parametrize("field", ["pic", "camera_a", "frame_src",
                                       "image_url"])
    def test_the_file_name_is_the_path_not_the_instance_id(self, project,
                                                           field):
        data, _ = export_with(project, field)
        assert data["images"][0]["file_name"] == "/media/scene.png", (
            "a COCO consumer cannot locate the image the record describes")

    @pytest.mark.parametrize("field", ["pic", "camera_a", "image_url"])
    def test_the_dimensions_are_read(self, project, field):
        data, _ = export_with(project, field)
        image = data["images"][0]
        assert (image["width"], image["height"]) == (200, 200)

    @pytest.mark.parametrize("field", ["pic", "camera_a", "image_url"])
    def test_the_box_does_not_collapse_to_the_origin(self, project, field):
        data, _ = export_with(project, field)
        assert [round(v) for v in data["annotations"][0]["bbox"]] == [
            40, 40, 120, 120], (
            "no filename means no file means no dimensions, and normalized "
            "coordinates multiplied by zero land at the origin")

    @pytest.mark.parametrize("field", ["pic", "camera_a", "image_url"])
    def test_nothing_is_warned_about(self, project, field):
        _data, result = export_with(project, field)
        assert not [w for w in result.warnings if "pixel size" in w]

    def test_every_arm_agrees(self, project):
        """The paired control: the field name must not change the output."""
        outputs = []
        for field in ("pic", "camera_a", "image_url"):
            data, _ = export_with(project, field)
            outputs.append((data["images"][0]["file_name"],
                            data["images"][0]["width"],
                            [round(v) for v in data["annotations"][0]["bbox"]]))
        assert len(set(map(str, outputs))) == 1


class TestTheGuessesStillWork:
    """A study that names its field one of the six conventional names, and
    declares no `source_field`, must be unaffected."""

    @pytest.mark.parametrize("key", ["image", "image_path", "image_url",
                                     "file_name", "filename", "img"])
    def test_a_conventional_name_is_still_found(self, key):
        assert get_image_filename({key: "/media/a.png"}) == "/media/a.png"

    def test_no_config_is_fine(self):
        assert get_image_filename({"image": "/media/a.png"}, None) == \
            "/media/a.png"

    def test_a_configured_field_wins_over_a_guess(self):
        """When both are present, the config is the one that was declared."""
        config = {"annotation_schemes": [scheme("pic")]}
        item = {"pic": "/media/right.png", "image": "/media/wrong.png"}
        assert get_image_filename(item, config) == "/media/right.png"

    def test_an_absent_configured_field_falls_through(self):
        config = {"annotation_schemes": [scheme("pic")]}
        assert get_image_filename({"image": "/media/a.png"}, config) == \
            "/media/a.png"

    def test_an_item_with_nothing_returns_none(self):
        assert get_image_filename({"text": "no media"}, None) is None


class TestWhichSchemesContribute:

    def test_a_media_scheme_contributes_its_field(self):
        assert _configured_media_keys(
            {"annotation_schemes": [scheme("pic")]}) == ["pic"]

    def test_a_non_media_scheme_does_not(self):
        """A `source_field` on an extractive_qa scheme names a passage, not a
        file."""
        assert _configured_media_keys(
            {"annotation_schemes": [scheme("passage", "extractive_qa")]}) == []

    def test_video_and_audio_schemes_contribute(self):
        config = {"annotation_schemes": [
            scheme("clip", "video_annotation"),
            scheme("track", "audio_annotation")]}
        assert _configured_media_keys(config) == ["clip", "track"]

    def test_duplicates_are_collapsed(self):
        config = {"annotation_schemes": [scheme("pic"),
                                         scheme("pic", "video_annotation")]}
        assert _configured_media_keys(config) == ["pic"]

    @pytest.mark.parametrize("config", [
        None, {}, {"annotation_schemes": None},
        {"annotation_schemes": ["not a dict"]},
        {"annotation_schemes": [{"annotation_type": "image_annotation"}]},
    ])
    def test_malformed_config_yields_nothing(self, config):
        assert _configured_media_keys(config) == []
