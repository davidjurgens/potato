"""
The VLM-as-judge review queue, driven in a browser.

Two layers, deliberately separated:

* the **wiring** — does a verdict become a card, does Delete remove the right
  annotation, does the staleness notice appear only once something actually
  changed — checked against a stubbed response so it is deterministic and needs
  no model;
* the **model**, behind `POTATO_CRITIQUE_LIVE=1`, which asks a real vision
  endpoint to review a deliberately bad box.

The stub mirrors a response captured from a live run against
`google/gemma-4-12B-it-qat-w4a16-ct`, including the `verdicts` / `missed` split
and the `[x, y, w, h]` normalized bbox the missed-object entries use. A stub
invented from the client's reading of the contract would pass while the server
sent something else, which is the failure this project keeps rediscovering.

Live measurement, for the record: two boxes drawn on a street scene — one
loose box on a car and one over empty road labelled "person" — came back in
~18 s with "The outline contains the car but is much larger than the object"
and "The outlined region is empty and contains no visible objects", plus two
genuinely missed people and a sign.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

MEDIA = Path("examples/image/annotation-critique/media").resolve()
LIVE = os.environ.get("POTATO_CRITIQUE_LIVE") == "1"

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "objects",
    "description": "Box every car, person and sign.",
    "source_field": "image_url",
    "tools": ["bbox", "polygon"],
    "zoom_enabled": True,
    "labels": [{"name": "car", "color": "#d6604d", "key_value": "1"},
               {"name": "person", "color": "#4575b4", "key_value": "2"},
               {"name": "sign", "color": "#5aa469", "key_value": "3"}],
    "ai_support": {
        "enabled": True,
        "features": {"critique": True, "detection": False,
                     "pre_annotate": False, "hint": False},
        "critique": {"context_ratio": 0.6, "min_confidence": 0.5,
                     "max_regions": 24, "max_workers": 4},
    },
}]

#: Shaped from a real response. `verdicts` carries an `index` into the
#: annotation list, which is what Delete acts on.
STUB = {
    "cached": False,
    "instance_id": None,          # filled in per request
    "schema": "objects",
    "model": "stub-vision-model",
    "image_width": 640,
    "image_height": 420,
    "verdicts": [
        {"index": 0, "label": "car", "verdict": "loose_boundary",
         "boundary": "loose", "confidence": 1, "error": "", "flagged": True,
         "suggested_label": "car",
         "rationale": "The outline contains the car but is much larger than "
                      "the object."},
        {"index": 1, "label": "person", "verdict": "not_an_object",
         "boundary": "unknown", "confidence": 0.9, "error": "", "flagged": True,
         "suggested_label": "",
         "rationale": "The outlined region is empty and contains no visible "
                      "objects."},
    ],
    "missed": [
        {"bbox": [0.771, 0.568, 0.048, 0.212], "confidence": 0.95,
         "label": "person",
         "rationale": "There is a person standing on the right side."},
    ],
    "summary": {
        "by_verdict": {"loose_boundary": 1, "not_an_object": 1},
        "caveat": "These are a vision model's opinions, not ground truth.",
        "confirmed": 0, "errors": 0, "flagged": 2, "missed": 1,
        "reviewed": 2, "skipped": 0, "uncertain": 0,
    },
}


@pytest.fixture
def critique_server(make_server):
    if not (MEDIA / "street_1.jpg").is_file():
        candidates = sorted(MEDIA.glob("*.jpg")) + sorted(MEDIA.glob("*.png"))
        if not candidates:
            pytest.skip("examples/image/annotation-critique media is missing")
    images = sorted(p.name for p in MEDIA.iterdir()
                    if p.suffix.lower() in {".jpg", ".png"})
    return make_server(
        SCHEMES,
        items=[{"id": Path(name).stem, "image_url": f"/media/{name}"}
               for name in images[:3]],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image_url"},
            # Top-level, not just on the scheme. `annotation_critique.js` is
            # gated on `config["ai_support"]["enabled"]` while the Review
            # button is gated on the SCHEME's ai_support — so a scheme-only
            # config renders a button whose handler never loaded, and the
            # first version of this file waited forever for a card that
            # nothing was listening to produce. See internal F7.
            "ai_support": {
                "enabled": True,
                # Required by config validation. Never reached: the browser
                # request to /api/critique_annotations is fulfilled by the
                # stub, so the server never calls out.
                "endpoint_type": "openai_vision",
                "base_url": "http://127.0.0.1:9",
                "model": "stub-vision-model",
            },
        },
    )


class TestCritiqueQueue(BasePlaywrightTest):

    def _open(self, page, server, stub=True):
        if stub:
            def handle(route):
                body = dict(STUB)
                body["instance_id"] = json.loads(
                    route.request.post_data or "{}").get("instance_id")
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(body))
            page.route("**/api/critique_annotations", handle)

        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "objects")

    def _draw_two(self, page):
        self.draw_bbox_on_image(page, "objects", 0.30, 0.45, 0.55, 0.70,
                                label="car")
        self.draw_bbox_on_image(page, "objects", 0.05, 0.05, 0.20, 0.20,
                                label="person")

    def _review(self, page, timeout=120_000):
        page.click("button:has-text('Review')")
        page.wait_for_selector(".critique-card", timeout=timeout)

    # ---- wiring ----

    def test_each_verdict_becomes_a_card_with_its_reason(
            self, page, critique_server):
        self._open(page, critique_server)
        self._draw_two(page)
        self._review(page)

        cards = page.eval_on_selector_all(
            ".critique-card",
            "els => els.map(e => e.textContent.replace(/\\s+/g, ' ').trim())")
        assert len(cards) == 3, cards        # two verdicts plus one missed
        joined = " ".join(cards)
        assert "much larger than the object" in joined
        assert "contains no visible objects" in joined

    def test_a_flagged_region_offers_delete_and_keep(self, page, critique_server):
        self._open(page, critique_server)
        self._draw_two(page)
        self._review(page)

        buttons = page.eval_on_selector_all(
            ".critique-card.critique-warn button",
            "els => els.map(e => e.textContent.trim())")
        assert "Delete" in buttons and "Keep as is" in buttons, buttons

    def test_delete_removes_the_annotation_the_card_refers_to(
            self, page, critique_server):
        """
        The card carries an INDEX into the annotation list. Off by one here
        deletes the annotator's good box and leaves the bad one, which looks
        like the tool working.
        """
        self._open(page, critique_server)
        self._draw_two(page)
        before = self.read_annotation_data(page, "objects")
        assert [a["label"] for a in before] == ["car", "person"]

        self._review(page)
        page.click(".critique-card.critique-warn button:has-text('Delete')")
        page.wait_for_timeout(800)

        after = self.read_annotation_data(page, "objects")
        assert [a["label"] for a in after] == ["car"], (
            "Delete removed the wrong annotation")

    def test_the_stale_notice_waits_for_an_actual_change(
            self, page, critique_server):
        """
        It has to be hidden when the review lands and shown after an edit. A
        notice that is always on is a notice annotators learn to ignore.
        """
        self._open(page, critique_server)
        self._draw_two(page)
        self._review(page)

        assert page.eval_on_selector(".critique-stale", "e => e.hidden") is True

        page.click(".critique-card.critique-warn button:has-text('Delete')")
        page.wait_for_timeout(800)
        assert page.eval_on_selector(".critique-stale", "e => e.hidden") is False

    def test_a_missed_object_is_offered_without_a_delete(
            self, page, critique_server):
        """
        There is nothing of the annotator's to delete for something they did
        not draw, so that card points at the area instead.
        """
        self._open(page, critique_server)
        self._draw_two(page)
        self._review(page)

        texts = page.eval_on_selector_all(
            ".critique-card",
            "els => els.map(e => ({t: e.textContent, b: Array.from("
            "e.querySelectorAll('button')).map(x => x.textContent.trim())}))")
        missed = [c for c in texts if "Possibly missed" in c["t"]]
        assert missed, texts
        for card in missed:
            assert "Delete" not in card["b"], card["b"]

    def test_the_caveat_is_shown_rather_than_buried(self, page, critique_server):
        """
        The panel tells annotators these are opinions. It is load-bearing: a
        flag treated as ground truth turns the dataset into the model's
        dataset.
        """
        self._open(page, critique_server)
        self._draw_two(page)
        self._review(page)

        caveat = page.eval_on_selector(
            ".critique-caveat", "e => [e.textContent.trim(), e.offsetParent !== null]")
        assert "not ground truth" in caveat[0]
        assert caveat[1] is True, "the caveat is in the DOM but not visible"


@pytest.mark.skipif(not LIVE, reason="set POTATO_CRITIQUE_LIVE=1 with an endpoint")
class TestCritiqueAgainstARealModel(BasePlaywrightTest):
    """
    Opt-in. Asks a real vision endpoint about a box drawn over nothing.

    Kept separate from the wiring tests because a model's wording is not a
    stable assertion — this checks only that it flags the empty region at all.
    """

    @pytest.mark.timeout(600)
    def test_it_flags_a_box_drawn_over_empty_ground(self, page, critique_server):
        opener = TestCritiqueQueue._open.__get__(self)
        opener(page, critique_server, stub=False)
        TestCritiqueQueue._draw_two.__get__(self)(page)
        TestCritiqueQueue._review.__get__(self)(page, timeout=300_000)

        flagged = page.eval_on_selector_all(
            ".critique-card",
            "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())")
        assert any("person" in text.lower() for text in flagged), flagged
