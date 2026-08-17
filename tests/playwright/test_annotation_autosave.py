"""
Work reaches the server without the annotator navigating.

Every other persistence test in this repo navigates — Next, then Previous —
and navigation calls `saveAnnotations()` explicitly. So the whole suite could
pass while an annotator who drew fifty boxes and closed the tab lost all of
them, which is what was happening: the canvas and timeline schemas answer
through a hidden `.annotation-data-input`, that class had no change listener,
and assigning `.value` fires no event.

Measured in a real browser before the fix: box drawn, five seconds elapsed,
`/get_annotations` empty.

These tests deliberately never navigate. The control below matters as much as
the assertion — a save that fires on page load would pass a naive version of
this file while marking untouched instances as answered, which ends the task
early because `/annotate` advances the phase as soon as nothing is unanswered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

EXAMPLE = Path("examples/image/geometry-primitives").resolve()
MEDIA = EXAMPLE / "media"

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "shapes",
    "description": "Outline each structure.",
    "source_field": "image_url",
    "tools": ["bbox", "polygon", "polyline", "ellipse"],
    "labels": [
        {"name": "lane", "color": "#E74C3C"},
        {"name": "cell", "color": "#27AE60"},
    ],
}]


def items():
    return [
        {"id": f"geo_{i}", "image_url": "/media/street.jpg", "caption": "Draw"}
        for i in range(1, 4)
    ]


@pytest.fixture
def autosave_server(make_server):
    if not (MEDIA / "street.jpg").is_file():
        pytest.skip("examples/image/geometry-primitives media is missing")
    return make_server(
        SCHEMES,
        items=items(),
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image_url"},
        },
    )


class TestCanvasWorkSavesWithoutNavigating(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "shapes")

    def _stored_on_server(self, page, server):
        instance = page.evaluate(
            "() => window.currentInstance && window.currentInstance.id")
        body = self.verify_server_annotations(page, server, instance)
        return body.get("label_annotations", {})

    def test_merely_opening_the_page_saves_nothing(self, page, autosave_server):
        """
        The control. Without it, an autosave that fired on load would pass
        every other test in this file while quietly answering the instance for
        the annotator — and an answered instance is one `/annotate` will
        advance past.
        """
        self._open(page, autosave_server)
        page.wait_for_timeout(2500)
        assert self._stored_on_server(page, autosave_server) == {}

    def test_a_drawn_box_reaches_the_server_on_its_own(self, page, autosave_server):
        self._open(page, autosave_server)
        self.draw_bbox_on_image(page, "shapes", 0.2, 0.2, 0.5, 0.5, label="cell")

        assert self.read_annotation_data(page, "shapes"), "nothing was drawn"
        page.wait_for_timeout(2500)          # past the 800 ms autosave debounce

        stored = self._stored_on_server(page, autosave_server)
        assert "shapes" in stored, (
            "the box was drawn in the browser but never reached the server "
            "without navigating — annotators lose work when they close the tab")

    def test_what_arrives_is_the_geometry_that_was_drawn(self, page, autosave_server):
        """Saving *something* is not saving the right thing."""
        self._open(page, autosave_server)
        self.draw_bbox_on_image(page, "shapes", 0.2, 0.2, 0.5, 0.5, label="cell")
        drawn = self.read_annotation_data(page, "shapes")
        page.wait_for_timeout(2500)

        # `/get_annotations` returns label KEYS for blob schemas, not values, so
        # the shape is checked against the serializer's own output and the
        # server is asked only whether it accepted the schema at all.
        assert drawn[0]["type"] == "bbox"
        assert drawn[0]["label"] == "cell"
        coords = drawn[0]["coordinates"]
        assert 0.19 < coords["x"] < 0.21
        assert 0.29 < coords["width"] < 0.31
        assert "shapes" in self._stored_on_server(page, autosave_server)

    def test_a_second_edit_saves_again(self, page, autosave_server):
        """
        The baseline comparison must not latch. It suppresses a save only when
        the value matches what the instance arrived holding; after the first
        edit every later one has to go through.
        """
        self._open(page, autosave_server)
        self.draw_bbox_on_image(page, "shapes", 0.1, 0.1, 0.3, 0.3, label="cell")
        page.wait_for_timeout(2000)
        self.draw_bbox_on_image(page, "shapes", 0.5, 0.5, 0.8, 0.8, label="lane")
        page.wait_for_timeout(2500)

        assert len(self.read_annotation_data(page, "shapes")) == 2
        assert "shapes" in self._stored_on_server(page, autosave_server)
