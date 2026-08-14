"""
Unit tests for potato.ai.critique_service — the I/O half of the critique pass.

Uses a fake endpoint that records what it was shown, so the properties that
can only be checked at this layer get checked: that the annotator's outline is
actually drawn into the crop (without it the model answers about a boundary it
imagined), that a per-region failure does not lose the other regions, and that
the image cannot be read from outside the project.
"""

import base64
import io
import json
import os

import pytest

PIL = pytest.importorskip("PIL", reason="critique cropping needs Pillow")
from PIL import Image, ImageDraw  # noqa: E402

from potato.ai.critique import CritiqueError  # noqa: E402
from potato.ai.critique_service import (  # noqa: E402
    OUTLINE_RGB,
    CritiqueService,
    crop_to_image_data,
    load_image,
    render_region_crop,
)
from potato.ai.critique import CritiqueRegion  # noqa: E402

LABELS = ["cat", "dog"]


@pytest.fixture
def project(tmp_path):
    """A project directory with one image under media/."""
    media = tmp_path / "media"
    media.mkdir()
    image = Image.new("RGB", (400, 300), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 200, 200], fill=(20, 120, 60))
    image.save(media / "scene.png")
    return {"task_dir": str(tmp_path), "media_directory": "media"}


class FakeEndpoint:
    """Records prompts and images, answers from a scripted queue."""

    model = "fake-vlm"

    def __init__(self, answers=None, fail_on=None):
        self.answers = list(answers or [])
        self.fail_on = fail_on or set()
        self.calls = []

    def query_with_image(self, prompt, image_data, output_format):
        index = len(self.calls)
        self.calls.append({"prompt": prompt, "image": image_data})
        if index in self.fail_on:
            raise RuntimeError("model exploded")
        if self.answers:
            return self.answers.pop(0)
        return {"verdict": "confirmed", "boundary": "tight", "confidence": 0.9}

    def decoded(self, index):
        """The image sent on call ``index``, as PIL."""
        data = self.calls[index]["image"]
        return Image.open(io.BytesIO(base64.b64decode(data.data))).convert("RGB")


def bbox_obj(label, x, y, w, h, iw=400.0, ih=300.0):
    return {"type": "bbox", "label": label,
            "coordinates": {"x": x / iw, "y": y / ih,
                            "width": w / iw, "height": h / ih}}


class TestLoadImage:
    def test_a_media_url_path_resolves(self, project):
        image = load_image("/media/scene.png", project)
        assert image.size == (400, 300)

    def test_a_bare_relative_path_resolves(self, project):
        image = load_image("media/scene.png", project)
        assert image.size == (400, 300)

    def test_traversal_out_of_the_project_is_refused(self, project, tmp_path):
        """These bytes leave the machine, so a weak check here is not an
        arbitrary file read but an exfiltration path."""
        secret = tmp_path.parent / "secret.png"
        Image.new("RGB", (10, 10)).save(secret)
        with pytest.raises(CritiqueError):
            load_image("/media/../../secret.png", project)

    def test_a_missing_file_says_so(self, project):
        with pytest.raises(CritiqueError) as excinfo:
            load_image("/media/nope.png", project)
        assert "not found" in str(excinfo.value).lower()

    def test_an_empty_reference_says_so(self, project):
        with pytest.raises(CritiqueError) as excinfo:
            load_image("", project)
        assert "no image" in str(excinfo.value).lower()


class TestRenderRegionCrop:
    def _image(self):
        return Image.new("RGB", (400, 300), (255, 255, 255))

    def test_the_outline_is_drawn_into_the_crop(self):
        """Without it the model is asked about a boundary it cannot see, and
        every answer about boundary quality is noise."""
        region = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(100, 100, 80, 80))
        crop, _ = render_region_crop(self._image(), region)
        colours = {c for _, c in crop.getcolors(crop.width * crop.height)}
        assert any(abs(c[0] - OUTLINE_RGB[0]) < 40 and c[1] < 60 and c[2] < 60
                   for c in colours), "no red outline found in the crop"

    def test_the_crop_shows_context_beyond_the_region(self):
        region = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(150, 120, 60, 60))
        crop, window = render_region_crop(self._image(), region)
        assert window.x0 < 150 and window.x1 > 210

    def test_a_polygon_is_outlined_as_a_polygon(self):
        """Drawing every type as a rectangle asks whether a box is tight around
        a shape the annotator actually traced — a different, easier question."""
        square = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(100, 100, 100, 100))
        triangle = CritiqueRegion(index=1, label="cat", type="polygon",
                                  bbox=(100, 100, 100, 100),
                                  points=[[100, 200], [200, 200], [150, 100]])
        square_crop, _ = render_region_crop(self._image(), square)
        triangle_crop, _ = render_region_crop(self._image(), triangle)
        assert list(square_crop.tobytes()) != list(triangle_crop.tobytes())

    def test_a_tiny_region_is_upscaled_to_something_legible(self):
        region = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(10, 10, 6, 6))
        crop, _ = render_region_crop(self._image(), region)
        assert max(crop.width, crop.height) >= 336

    def test_a_huge_region_is_downscaled(self):
        image = Image.new("RGB", (4000, 3000), (255, 255, 255))
        region = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(0, 0, 3000, 2000))
        crop, _ = render_region_crop(image, region)
        assert max(crop.width, crop.height) <= 768

    def test_crops_encode_to_something_an_endpoint_accepts(self):
        region = CritiqueRegion(index=0, label="cat", type="bbox",
                                bbox=(100, 100, 50, 50))
        crop, _ = render_region_crop(self._image(), region)
        data = crop_to_image_data(crop)
        assert data.source == "base64"
        assert data.mime_type == "image/jpeg"
        assert base64.b64decode(data.data)[:2] == b"\xff\xd8"  # JPEG SOI


class TestCritiquePass:
    def _service(self, project, endpoint, **options):
        options.setdefault("max_workers", 1)
        options.setdefault("check_missed", False)
        return CritiqueService(project, endpoint, options)

    def test_one_call_per_region(self, project):
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint)
        result = service.critique(
            [bbox_obj("cat", 100, 100, 50, 50), bbox_obj("dog", 200, 150, 40, 40)],
            "/media/scene.png", LABELS)
        assert len(endpoint.calls) == 2
        assert len(result.verdicts) == 2

    def test_verdicts_come_back_in_annotation_order(self, project):
        """as_completed returns in finish order; a queue that jumps around is
        much harder to work through than one that follows the drawing order."""
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint, max_workers=4)
        objects = [bbox_obj("cat", 20 * i, 20 * i, 30, 30) for i in range(6)]
        result = service.critique(objects, "/media/scene.png", LABELS)
        assert [v.index for v in result.verdicts] == list(range(6))

    def test_one_failing_region_does_not_lose_the_others(self, project):
        endpoint = FakeEndpoint(fail_on={1})
        service = self._service(project, endpoint)
        objects = [bbox_obj("cat", 20 * i, 20 * i, 30, 30) for i in range(3)]
        result = service.critique(objects, "/media/scene.png", LABELS)
        assert len(result.verdicts) == 3
        assert result.verdicts[1].error
        assert result.summary.errors == 1

    def test_a_failed_region_is_not_flagged(self, project):
        """Showing an outage in the review queue manufactures a finding."""
        endpoint = FakeEndpoint(fail_on={0})
        service = self._service(project, endpoint)
        result = service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                                  "/media/scene.png", LABELS)
        assert result.verdicts[0].flagged is False
        assert result.summary.flagged == 0

    def test_regions_beyond_the_cap_are_reported_as_skipped(self, project):
        """A truncated review that reads as complete is worse than no review."""
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint, max_regions=2)
        objects = [bbox_obj("cat", 10 * i, 10 * i, 30, 30) for i in range(5)]
        result = service.critique(objects, "/media/scene.png", LABELS)
        assert len(endpoint.calls) == 2
        assert result.summary.skipped == 3

    def test_unusable_objects_count_as_skipped(self, project):
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint)
        result = service.critique(
            [bbox_obj("cat", 100, 100, 50, 50), {"junk": 1}],
            "/media/scene.png", LABELS)
        assert result.summary.reviewed == 1
        assert result.summary.skipped == 1

    def test_an_image_with_no_annotations_is_not_an_error(self, project):
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint)
        result = service.critique([], "/media/scene.png", LABELS)
        assert result.verdicts == []
        assert result.summary.reviewed == 0

    def test_the_real_image_size_is_reported(self, project):
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint)
        result = service.critique([], "/media/scene.png", LABELS)
        assert (result.image_width, result.image_height) == (400, 300)

    def test_the_model_name_is_carried_through(self, project):
        service = self._service(project, FakeEndpoint())
        result = service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                                  "/media/scene.png", LABELS)
        assert result.model == "fake-vlm"

    def test_the_missed_pass_runs_on_the_whole_image(self, project):
        endpoint = FakeEndpoint(answers=[
            {"verdict": "confirmed", "boundary": "tight", "confidence": 0.9},
            {"missed": [{"label": "dog", "confidence": 0.9,
                         "bbox": {"x": 0.8, "y": 0.8, "width": 0.1,
                                  "height": 0.1}}]},
        ])
        service = self._service(project, endpoint, check_missed=True)
        result = service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                                  "/media/scene.png", LABELS)
        assert len(result.missed) == 1
        # The last call carried the whole image, not a crop.
        whole = endpoint.decoded(len(endpoint.calls) - 1)
        assert whole.size == (400, 300)

    def test_a_missed_object_inside_an_oversized_box_is_suppressed(self, project):
        """The live case: a box three times too big around the object. IoU is
        low because the box is loose, so only a containment test catches it."""
        endpoint = FakeEndpoint(answers=[
            {"verdict": "loose_boundary", "boundary": "loose", "confidence": 0.9},
            {"missed": [{"label": "cat", "confidence": 0.9,
                         "bbox": {"x": 120 / 400, "y": 120 / 300,
                                  "width": 30 / 400, "height": 30 / 300}}]},
        ])
        service = self._service(project, endpoint, check_missed=True)
        result = service.critique([bbox_obj("cat", 100, 100, 150, 150)],
                                  "/media/scene.png", LABELS)
        assert result.missed == []

    def test_a_missed_object_over_an_existing_region_is_suppressed(self, project):
        endpoint = FakeEndpoint(answers=[
            {"verdict": "confirmed", "boundary": "tight", "confidence": 0.9},
            {"missed": [{"label": "dog", "confidence": 0.9,
                         "bbox": {"x": 100 / 400, "y": 100 / 300,
                                  "width": 50 / 400, "height": 50 / 300}}]},
        ])
        service = self._service(project, endpoint, check_missed=True)
        result = service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                                  "/media/scene.png", LABELS)
        assert result.missed == []

    def test_the_missed_pass_is_skipped_when_there_are_no_labels(self, project):
        endpoint = FakeEndpoint()
        service = self._service(project, endpoint, check_missed=True)
        service.critique([], "/media/scene.png", [])
        assert endpoint.calls == []

    def test_a_missing_image_raises_a_stated_reason(self, project):
        service = self._service(project, FakeEndpoint())
        with pytest.raises(CritiqueError):
            service.critique([bbox_obj("cat", 10, 10, 20, 20)],
                             "/media/absent.png", LABELS)

    def test_the_result_serializes_to_json(self, project):
        service = self._service(project, FakeEndpoint())
        result = service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                                  "/media/scene.png", LABELS)
        assert json.loads(json.dumps(result.to_dict()))["summary"]["caveat"]


class TestPromptsSeenByTheModel:
    def test_each_region_prompt_names_that_regions_own_label(self, project):
        endpoint = FakeEndpoint()
        service = CritiqueService(project, endpoint,
                                  {"max_workers": 1, "check_missed": False})
        service.critique([bbox_obj("cat", 100, 100, 50, 50),
                          bbox_obj("dog", 200, 150, 40, 40)],
                         "/media/scene.png", LABELS)
        assert '"cat"' in endpoint.calls[0]["prompt"]
        assert '"dog"' in endpoint.calls[1]["prompt"]

    def test_the_prompt_and_the_drawn_colour_agree(self, project):
        """If they drift, the prompt directs the model at a colour that is not
        in the picture and the answers are about nothing."""
        from potato.ai.critique_service import OUTLINE_NAME

        endpoint = FakeEndpoint()
        service = CritiqueService(project, endpoint,
                                  {"max_workers": 1, "check_missed": False})
        service.critique([bbox_obj("cat", 100, 100, 50, 50)],
                         "/media/scene.png", LABELS)
        assert OUTLINE_NAME in endpoint.calls[0]["prompt"]
        assert OUTLINE_RGB == (255, 0, 0)
        assert "red" in OUTLINE_NAME
