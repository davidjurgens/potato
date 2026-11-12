"""
Open-vocabulary detection: type a phrase, get boxes, accept the good ones.

Grounding DINO tiny runs in the browser through ONNX Runtime Web. Jest covers
the caption building, the token→phrase attribution and the postprocessing
arithmetic against fixtures; none of that proves the model finds a cat, that
the box lands on the cat, or that accepting one turns it into an annotation.
This was previously exercised only by a throwaway capture script, so nothing
re-ran it.

Measured live while writing these, against `examples/image/text-prompt-labeling`
with the prompt "cat, bus, stop sign" on the two-cat photo: two suggestions,
"cat (72%)" and "cat (69%)", first inference ~19 s, and accepting one stored a
bbox with coordinates byte-identical to the suggestion's.

The model is 151 MB and runs on the CPU, so these are slow and skip when it has
not been downloaded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS = REPO_ROOT / "potato" / "models"
MEDIA = REPO_ROOT / "examples" / "image" / "text-prompt-labeling" / "media"

PHRASES = ["cat", "bus", "stop sign"]

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "objects",
    "description": "Type what to look for, then accept or reject what comes back",
    "source_field": "image",
    "tools": ["bbox", "polygon"],
    "labels": [
        {"name": "cat", "color": "#6e56cf"},
        {"name": "bus", "color": "#2f9e6f"},
        {"name": "stop sign", "color": "#d1495b"},
    ],
    "text_prompt": {
        "phrases": PHRASES,
        "box_threshold": 0.3,
        "text_threshold": 0.25,
    },
}]


def model_is_downloaded():
    return ((MODELS / "grounding_dino_tiny" / "model.onnx").is_file()
            and (MODELS / "grounding_dino_tiny" / "vocab.txt").is_file()
            and (MODELS / "onnxruntime" / "ort.wasm.min.js").is_file())


@pytest.fixture
def prompt_server(make_server):
    if not model_is_downloaded():
        pytest.skip("run `potato download-models grounding_dino_tiny` first")
    if not (MEDIA / "cats.jpg").is_file():
        pytest.skip("run examples/image/text-prompt-labeling/fetch_images.py")
    return make_server(
        SCHEMES,
        # cats.jpg first — that is the picture the expectations below describe.
        items=[{"id": "cats", "image": "/media/cats.jpg"},
               {"id": "bus", "image": "/media/bus.jpg"},
               {"id": "stop-sign", "image": "/media/stop-sign.jpg"}],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image"},
        },
    )


class TestTextPrompting(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "objects")

    def _run_detector(self, page, phrase=None, timeout=300_000):
        """Type a prompt, press Find, wait for the run to finish."""
        if phrase is not None:
            page.fill(".text-prompt-input", phrase)
        page.click("button:has-text('Find')")
        # The status line is the only thing that reports completion; the model
        # holds the main thread while it runs, so this is a long wait by nature.
        page.wait_for_function(
            """() => {
                const el = document.querySelector('[class*="text-prompt-status"]');
                if (!el) return false;
                const t = el.textContent.trim();
                return /suggestion|nothing|no matches|failed|could not/i.test(t);
            }""", timeout=timeout)
        return page.evaluate(
            """() => document.querySelector(
                '[class*="text-prompt-status"]').textContent.trim()""")

    def _suggestions(self, page):
        return page.evaluate(
            """() => {
                const c = document.querySelector('.image-annotation-container');
                const a = c.aiAssistant;
                return (a && a.suggestions || []).map(s => ({
                    id: s.id, type: s.type,
                    label: s.data && s.data.label,
                    confidence: s.data && s.data.confidence,
                    bbox: s.data && s.data.bbox,
                }));
            }""")

    @pytest.mark.timeout(600)
    def test_a_typed_phrase_finds_the_object(self, page, prompt_server):
        self._open(page, prompt_server)
        status = self._run_detector(page, "cat, bus, stop sign")

        found = self._suggestions(page)
        assert found, f"no suggestions; status said {status!r}"
        assert any(s["label"] == "cat" for s in found), (
            f"asked for cats on a photo of cats, got {[s['label'] for s in found]}")
        for s in found:
            assert s["label"] in PHRASES, (
                f"{s['label']!r} is not one of the phrases that were asked for")
            assert 0 < s["confidence"] <= 1, s["confidence"]

    @pytest.mark.timeout(600)
    def test_the_boxes_are_normalized_and_land_on_the_image(
            self, page, prompt_server):
        """
        A detector that returns pixels, or 800-space coordinates, or xyxy where
        the contract says xywh, still produces boxes that render — just in the
        wrong place. Only the numbers catch it.
        """
        self._open(page, prompt_server)
        self._run_detector(page, "cat")

        for s in self._suggestions(page):
            box = s["bbox"]
            assert 0 <= box["x"] <= 1 and 0 <= box["y"] <= 1, box
            assert 0 < box["width"] <= 1 and 0 < box["height"] <= 1, box
            assert box["x"] + box["width"] <= 1.02, f"box runs off the right: {box}"
            assert box["y"] + box["height"] <= 1.02, f"box runs off the bottom: {box}"
            # A whole-image box means the phrase matched nothing in particular.
            assert box["width"] * box["height"] < 0.95, box

    @pytest.mark.timeout(600)
    def test_a_suggestion_is_not_an_annotation_until_it_is_accepted(
            self, page, prompt_server):
        """
        The point of the whole design. A dataset assembled from unreviewed
        model output agrees with the model rather than with reality, and every
        agreement statistic computed over it looks better than it should.
        """
        self._open(page, prompt_server)
        self._run_detector(page, "cat")

        assert self._suggestions(page), "nothing to test with"
        assert self.read_annotation_data(page, "objects") == []
        assert self.count_annotations(page, "objects") == 0

    @pytest.mark.timeout(600)
    def test_accepting_stores_exactly_the_box_that_was_shown(
            self, page, prompt_server):
        self._open(page, prompt_server)
        self._run_detector(page, "cat")

        found = self._suggestions(page)
        assert found
        first = found[0]
        page.evaluate(
            """(id) => document.querySelector('.image-annotation-container')
                   .aiAssistant.acceptSuggestion(id)""", first["id"])
        page.wait_for_function(
            """() => {
                const el = document.getElementById('input-objects');
                return el && el.value && JSON.parse(el.value).length > 0;
            }""", timeout=30_000)

        stored = self.read_annotation_data(page, "objects")
        assert len(stored) == 1
        assert stored[0]["type"] == "bbox"
        assert stored[0]["label"] == first["label"]
        # Byte-identical, not merely close: accepting is meant to keep the
        # model's box, and any drift here is a coordinate conversion nobody
        # asked for.
        assert stored[0]["coordinates"] == first["bbox"]

        # The rest stay pending rather than being swept in.
        assert len(self._suggestions(page)) == len(found) - 1

    @pytest.mark.timeout(600)
    def test_rejecting_removes_it_without_storing_anything(
            self, page, prompt_server):
        self._open(page, prompt_server)
        self._run_detector(page, "cat")

        found = self._suggestions(page)
        assert found
        page.evaluate(
            """(id) => document.querySelector('.image-annotation-container')
                   .aiAssistant.rejectSuggestion(id)""", found[0]["id"])
        page.wait_for_timeout(500)

        assert len(self._suggestions(page)) == len(found) - 1
        assert self.read_annotation_data(page, "objects") == []

    @pytest.mark.timeout(600)
    def test_an_accepted_box_survives_navigating_away_and_back(
            self, page, prompt_server):
        self._open(page, prompt_server)
        self._run_detector(page, "cat")
        found = self._suggestions(page)
        assert found
        page.evaluate(
            """(id) => document.querySelector('.image-annotation-container')
                   .aiAssistant.acceptSuggestion(id)""", found[0]["id"])
        page.wait_for_function(
            """() => {
                const el = document.getElementById('input-objects');
                return el && el.value && JSON.parse(el.value).length > 0;
            }""", timeout=30_000)

        before = self.read_annotation_data(page, "objects")
        restored = self.assert_persists_across_navigation(
            page, "objects", expected_types=["bbox"])
        assert restored[0]["coordinates"] == before[0]["coordinates"]
