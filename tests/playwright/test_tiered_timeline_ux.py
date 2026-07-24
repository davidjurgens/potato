"""
Playwright UX tests for the tiered (ELAN-style) timeline annotation interface.

Focuses on the custom zoomed-timeline canvas:
  - left-drag on the zoomed canvas creates a time-aligned annotation
  - edge auto-scroll: a drag that reaches the visible edge pans the zoom window
    so the annotation can extend past the original window
  - the raw media path is NOT shown as a header

The tiered ELAN interface already supports annotating on the full-duration tier
rows (the "zoomed-out" view); this suite exercises the zoomed-in detail canvas
and the new edge auto-scroll.

Run:  pytest tests/playwright/test_tiered_timeline_ux.py -v
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
)
from tests.playwright.test_base import BasePlaywrightTest


TIERED_CONTAINER = ".tiered-annotation-container"
SCHEMA = "linguistic_tiers"
ZOOM_CANVAS = f"#zoomed-canvas-{SCHEMA}"


@pytest.fixture(scope="module")
def tiered_server():
    test_dir = create_test_directory("pw_tiered_ux")
    data = [
        {"id": "t1", "audio_url": "/test-audio/test_audio_10s.mp3"},
        {"id": "t2", "audio_url": "/test-audio/test_audio_10s.mp3"},
    ]
    data_file = create_test_data_file(test_dir, data, filename="tiered_data.jsonl")
    schemes = [
        {
            "annotation_type": "tiered_annotation",
            "name": SCHEMA,
            "description": "Annotate speech with hierarchical tiers",
            "source_field": "audio_url",
            "media_type": "audio",
            "tiers": [
                {
                    "name": "utterance",
                    "tier_type": "independent",
                    "labels": [
                        {"name": "Speaker_A", "color": "#4ECDC4"},
                        {"name": "Speaker_B", "color": "#FF6B6B"},
                    ],
                },
                {
                    "name": "gesture",
                    "tier_type": "independent",
                    "labels": [
                        {"name": "Point", "color": "#DDA0DD"},
                        {"name": "Nod", "color": "#87CEEB"},
                    ],
                },
            ],
            "tier_height": 50,
            "zoom_enabled": True,
        }
    ]
    config_file = create_test_config(
        test_dir,
        schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "audio_url"},
    )
    server = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start tiered Flask server")
    yield server
    server.stop()


def _state(page):
    return page.evaluate(
        """(schema) => {
            const c = document.getElementById(schema);
            const m = c && c._tieredManager;
            if (!m) return null;
            let count = 0;
            const anns = [];
            for (const t in m.annotations) {
                for (const a of m.annotations[t]) {
                    count++;
                    anns.push({tier: t, start: a.start_time, end: a.end_time});
                }
            }
            return {
                ready: !!(m.mediaMetadata.duration > 0 && m.zoomedTimelineView),
                duration: m.mediaMetadata.duration,
                viewStart: m.zoomedViewStart,
                viewDur: m.zoomedViewDuration,
                count, anns,
            };
        }""",
        SCHEMA,
    )


def _set_window(page, start, dur):
    page.evaluate(
        """([schema, start, dur]) => {
            const m = document.getElementById(schema)._tieredManager;
            m.zoomedViewStart = start;
            m.zoomedViewDuration = dur;
            m._updateZoomedView();
            m._updateZoomedSlider();
        }""",
        [SCHEMA, start, dur],
    )


def _wait_ready(page, timeout=20000):
    page.wait_for_function(
        """(schema) => {
            const c = document.getElementById(schema);
            const m = c && c._tieredManager;
            return m && m.mediaMetadata.duration > 0 && m.zoomedTimelineView;
        }""",
        arg=SCHEMA,
        timeout=timeout,
    )


def _box(page, selector):
    el = page.wait_for_selector(selector, state="visible", timeout=10000)
    return el.bounding_box()


def _ldrag(page, box, x0f, x1f, yf=0.5, hold_ms=0, steps=10):
    """Left-drag across a box from fraction x0f to x1f of its width."""
    y = box["y"] + box["height"] * yf
    page.mouse.move(box["x"] + box["width"] * x0f, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * x1f, y, steps=steps)
    if hold_ms:
        page.wait_for_timeout(hold_ms)
    page.mouse.up()
    page.wait_for_timeout(300)


@pytest.mark.playwright
class TestTieredTimelineUX(BasePlaywrightTest):
    def _login(self, page, server):
        self.register_and_login(page, server)
        page.wait_for_selector(TIERED_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)

    def test_zoomed_canvas_drag_creates_annotation(self, page, tiered_server):
        self._login(page, tiered_server)
        before = _state(page)
        assert before and before["ready"], "tiered manager not ready"

        box = _box(page, ZOOM_CANVAS)
        # Drag within the top tier row (utterance).
        _ldrag(page, box, 0.2, 0.5, yf=0.25)

        after = _state(page)
        assert after["count"] == before["count"] + 1, "zoomed-canvas drag did not create an annotation"

    def test_edge_autoscroll_extends_past_window(self, page, tiered_server):
        self._login(page, tiered_server)

        # Constrain the zoom window to the first 2.5s of the clip.
        _set_window(page, 0.0, 2.5)
        page.wait_for_timeout(200)
        start_state = _state(page)
        assert start_state["viewStart"] == 0.0
        initial_view_end = start_state["viewDur"]  # 2.5s (window is [0, 2.5])

        box = _box(page, ZOOM_CANVAS)
        # Left-drag to the far right edge of the canvas and hold to auto-scroll.
        _ldrag(page, box, 0.15, 0.99, yf=0.25, hold_ms=1400, steps=12)

        end_state = _state(page)
        assert end_state["viewStart"] > start_state["viewStart"] + 0.1, (
            f"zoom window did not auto-scroll (start {start_state['viewStart']} -> {end_state['viewStart']})"
        )
        assert end_state["count"] >= start_state["count"] + 1, "no annotation created during edge drag"
        newest = end_state["anns"][-1]
        assert newest["end"] / 1000.0 > initial_view_end, (
            f"annotation end {newest['end']/1000.0:.2f}s did not extend past the original "
            f"window end {initial_view_end:.2f}s"
        )

    def test_media_path_not_shown_as_header(self, page, tiered_server):
        self._login(page, tiered_server)
        visible_text = page.evaluate("() => document.body.innerText")
        assert "/test-audio/" not in visible_text, "raw media path leaked into the visible page"
