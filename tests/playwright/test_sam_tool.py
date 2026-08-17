"""
The magic wand, running the real MobileSAM ONNX model in a real browser.

Everything downstream of a click here is untested by anything else: the
preprocessing, the encoder, the decoder, the mapping from a canvas click into
image pixels, and the RLE that comes back. Jest covers the session's tensor
plumbing against fixtures; only this proves the model segments the thing the
annotator pointed at.

The fixture is synthetic on purpose. `scene_1.png` is a dark background with a
red square at x[90,210] y[60,180] and a green square at x[320,440] y[160,280],
so "did it segment the right object?" has an exact answer instead of an
eyeballed one. Measured live before these were written: clicking the red
square's centre returned a mask bounded exactly at x[90,210] y[60,180], area
11397 px against the square's true 11497 — 99.1%.

Slow by nature: the runtime is 13.5 MB of wasm and the encoder runs on the CPU,
so allow the model a generous budget rather than a flaky short one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS = REPO_ROOT / "potato" / "models"
EXAMPLE = REPO_ROOT / "examples" / "image" / "interactive-segmentation"
MEDIA = EXAMPLE / "media"

#: The fixture's ground truth, in image pixels.
RED_SQUARE = {"x": (90, 210), "y": (60, 180), "area": 11497}
GREEN_SQUARE = {"x": (320, 440), "y": (160, 280), "area": 11497}
IMAGE = (520, 340)

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "objects",
    "description": "Click an object with the magic wand.",
    "source_field": "image_url",
    "tools": ["sam", "brush", "eraser", "bbox"],
    "mask_mode": "instance",
    "segmentation": {"model": "mobile_sam"},
    "labels": [
        {"name": "object", "color": "#e6194b"},
        {"name": "background_thing", "color": "#3cb44b"},
    ],
}]


def model_is_downloaded():
    return ((MODELS / "mobile_sam" / "encoder.onnx").is_file()
            and (MODELS / "mobile_sam" / "decoder.onnx").is_file()
            and (MODELS / "onnxruntime" / "ort.wasm.min.js").is_file())


@pytest.fixture
def sam_server(make_server):
    if not model_is_downloaded():
        pytest.skip("run `potato download-models --model mobile_sam` first")
    if not (MEDIA / "scene_1.png").is_file():
        pytest.skip("examples/image/interactive-segmentation media is missing")
    # Three items, not two: on the LAST assigned item `/annotate` advances the
    # phase before it reads the requested action, so pressing Previous there
    # lands on the completion page and the navigation check times out with a
    # misleading "manager never became ready".
    return make_server(
        SCHEMES,
        # The FIRST item must be scene_1 — that is the picture the ground truth
        # above describes. The third only exists to keep Previous usable.
        items=[{"id": "scene_1", "image_url": "/media/scene_1.png"},
               {"id": "scene_2", "image_url": "/media/scene_2.png"},
               {"id": "scene_3", "image_url": "/media/scene_1.png"}],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image_url"},
        },
    )


def decode_bounds(rle):
    """Bounds and area of an RLE mask, in image pixels.

    Potato's wire format is background-first, **row-major** — see the header of
    `potato/static/mask-buffer.js`. Decoding it column-major (the COCO
    convention) gives plausible-looking nonsense: the first attempt at this
    reported that the mask did not contain the clicked point, when it did.
    """
    height, width = rle["size"]
    index, painted = 0, False
    min_x, min_y, max_x, max_y, area = width, height, -1, -1, 0
    for run in rle["counts"]:
        if painted:
            for offset in range(run):
                position = index + offset
                y, x = divmod(position, width)
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
            area += run
        index += run
        painted = not painted
    return {"x": (min_x, max_x), "y": (min_y, max_y), "area": area}


class TestMagicWand(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "objects")

    def _arm_wand(self, page, label="object"):
        self.arm(page, "objects", "sam", label)
        page.wait_for_function(
            """() => {
                const m = document.querySelector(
                    '.image-annotation-container').annotationManager;
                return !!(m.samTool && m.samTool.session
                          && m.samTool.session._encoder);
            }""", timeout=120_000)

    def _click_image_pixel(self, page, px, py):
        """Click a point given in ORIGINAL image pixels."""
        page.evaluate(
            """([px, py]) => {
                const m = document.querySelector(
                    '.image-annotation-container').annotationManager;
                const img = m.image;
                const vpt = m.canvas.viewportTransform;
                const zoom = m.canvas.getZoom();
                const rect = m.canvas.upperCanvasEl.getBoundingClientRect();
                const x = rect.left + img.left * zoom + vpt[4]
                          + (px / img.width) * img.width * img.scaleX * zoom;
                const y = rect.top + img.top * zoom + vpt[5]
                          + (py / img.height) * img.height * img.scaleY * zoom;
                for (const type of ['mousedown', 'mouseup']) {
                    m.canvas.upperCanvasEl.dispatchEvent(new MouseEvent(type, {
                        clientX: x, clientY: y, bubbles: true, cancelable: true,
                        view: window, button: 0,
                        buttons: type === 'mouseup' ? 0 : 1,
                    }));
                }
            }""", [px, py])

    def _wait_for_mask(self, page, timeout=180_000):
        page.wait_for_function(
            """() => {
                const m = document.querySelector(
                    '.image-annotation-container').annotationManager;
                return !!(m.samTool && m.samTool.preview);
            }""", timeout=timeout)
        return page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.image-annotation-container').annotationManager;
                const p = m.samTool.preview;
                return {rle: p.rle, bbox: p.bbox, score: p.score};
            }""")

    # ---- the model actually segments the thing that was clicked ----

    @pytest.mark.timeout(400)
    def test_clicking_an_object_segments_that_object(self, page, sam_server):
        self._open(page, sam_server)
        self._arm_wand(page)
        self._click_image_pixel(page, 150, 120)      # centre of the red square

        preview = self._wait_for_mask(page)
        got = decode_bounds(preview["rle"])

        # Four pixels of slack: the model works at 1024 and the mask is
        # resampled back, so the edge lands within a pixel or two.
        assert abs(got["x"][0] - RED_SQUARE["x"][0]) <= 4, got
        assert abs(got["x"][1] - RED_SQUARE["x"][1]) <= 4, got
        assert abs(got["y"][0] - RED_SQUARE["y"][0]) <= 4, got
        assert abs(got["y"][1] - RED_SQUARE["y"][1]) <= 4, got
        assert got["area"] > 0.95 * RED_SQUARE["area"], (
            f"mask area {got['area']} against a true {RED_SQUARE['area']}")

    @pytest.mark.timeout(400)
    def test_it_picks_the_object_under_the_cursor_not_a_fixed_one(
            self, page, sam_server):
        """
        The control for the test above. A pipeline that ignored the prompt and
        returned the most salient object would pass it every time; clicking the
        OTHER square has to give the other answer.
        """
        self._open(page, sam_server)
        self._arm_wand(page)
        self._click_image_pixel(page, 380, 220)      # centre of the green square

        got = decode_bounds(self._wait_for_mask(page)["rle"])
        assert abs(got["x"][0] - GREEN_SQUARE["x"][0]) <= 4, got
        assert abs(got["y"][0] - GREEN_SQUARE["y"][0]) <= 4, got
        # And it is emphatically not the red one.
        assert got["x"][0] > RED_SQUARE["x"][1], (
            f"clicked the green square and got something at x={got['x']}")

    @pytest.mark.timeout(400)
    def test_the_rle_is_sized_for_the_original_image(self, page, sam_server):
        """
        `size` is [height, width] and must describe the ORIGINAL image, not the
        1024 the model works at nor the canvas it is displayed on. Getting this
        wrong exports masks that no longer line up with their pictures.
        """
        self._open(page, sam_server)
        self._arm_wand(page)
        self._click_image_pixel(page, 150, 120)
        rle = self._wait_for_mask(page)["rle"]
        assert rle["size"] == [IMAGE[1], IMAGE[0]]

    @pytest.mark.timeout(400)
    def test_enter_accepts_the_mask_into_the_answer(self, page, sam_server):
        self._open(page, sam_server)
        self._arm_wand(page)
        self._click_image_pixel(page, 150, 120)
        self._wait_for_mask(page)

        assert self.read_annotation_data(page, "objects") == [], (
            "a previewed mask must not be stored until it is accepted")

        page.evaluate(
            "() => document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key: 'Enter', bubbles: true, cancelable: true}))")
        page.wait_for_function(
            """() => {
                const el = document.getElementById('input-objects');
                return el && el.value && JSON.parse(el.value).length > 0;
            }""", timeout=30_000)

        stored = self.read_annotation_data(page, "objects")
        assert [a["type"] for a in stored] == ["mask"]
        assert stored[0]["label"] == "object"
        assert stored[0]["rle"]["size"] == [IMAGE[1], IMAGE[0]]

        # Instance-keyed, so two adjacent objects of one class stay separate.
        keys = page.evaluate(
            """() => Object.keys(document.querySelector(
                '.image-annotation-container').annotationManager.masks || {})""")
        assert keys == ["object#0"], keys

    @pytest.mark.timeout(400)
    def test_an_accepted_mask_survives_navigating_away_and_back(
            self, page, sam_server):
        self._open(page, sam_server)
        self._arm_wand(page)
        self._click_image_pixel(page, 150, 120)
        self._wait_for_mask(page)
        page.evaluate(
            "() => document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key: 'Enter', bubbles: true, cancelable: true}))")
        page.wait_for_function(
            """() => {
                const el = document.getElementById('input-objects');
                return el && el.value && JSON.parse(el.value).length > 0;
            }""", timeout=30_000)

        before = decode_bounds(self.read_annotation_data(page, "objects")[0]["rle"])
        restored = self.assert_persists_across_navigation(
            page, "objects", expected_types=["mask"])
        assert decode_bounds(restored[0]["rle"]) == before, (
            "the mask came back a different shape than it went in")
