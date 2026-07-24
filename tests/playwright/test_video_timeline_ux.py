"""
Playwright UX tests for the video temporal-segment annotation interface.

Mirrors the audio waveform UX tests for the Peaks.js video timeline:
  - right-click-drag selection on the zoomed-in timeline
  - right-click-drag selection on the zoomed-out overview (reaches whole clip)
  - edge auto-scroll during a drag
  - persistence across navigate-away-and-back
  - the raw media path is NOT shown as a header

Uses a local WebM clip (Chromium supports VP9/Opus; bundled Chromium often
lacks H.264) served from the /test-video/ route.

Run:  pytest tests/playwright/test_video_timeline_ux.py -v
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


VIDEO_CONTAINER = ".video-annotation-container"


@pytest.fixture(scope="module")
def video_server():
    test_dir = create_test_directory("pw_video_ux")
    data = [
        {"id": "video_001", "video_url": "/test-video/test_video_6s.webm"},
        {"id": "video_002", "video_url": "/test-video/test_video_6s.webm"},
        {"id": "video_003", "video_url": "/test-video/test_video_6s.webm"},
    ]
    data_file = create_test_data_file(test_dir, data, filename="video_data.jsonl")
    schemes = [
        {
            "annotation_type": "video_annotation",
            "name": "video_segmentation",
            "description": "Segment the video by content type",
            "mode": "segment",
            "labels": [
                {"name": "intro", "color": "#4ECDC4", "key_value": "1"},
                {"name": "main", "color": "#FF6B6B", "key_value": "2"},
                {"name": "outro", "color": "#95A5A6", "key_value": "3"},
            ],
            "timeline_height": 70,
            "overview_height": 40,
            "zoom_enabled": True,
            "playback_rate_control": True,
        }
    ]
    config_file = create_test_config(
        test_dir,
        schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "video_url"},
    )
    server = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start video Flask server")
    yield server
    server.stop()


def _video_state(page):
    return page.evaluate(
        """() => {
            const c = document.querySelector('.video-annotation-container');
            if (!c || !c.videoAnnotationManager) return null;
            const m = c.videoAnnotationManager;
            const zv = m.peaks && m.peaks.views.getView('zoomview');
            return {
                ready: !!m.peaks,
                count: m.segments.length,
                segs: m.segments.map(s => ({start: s.startTime, end: s.endTime})),
                viewStart: zv ? zv.getStartTime() : null,
                viewEnd: zv ? zv.getEndTime() : null,
                duration: m.peaks ? m.peaks.player.getDuration() : null,
            };
        }"""
    )


def _wait_ready(page, timeout=25000):
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.video-annotation-container');
            return c && c.videoAnnotationManager && !!c.videoAnnotationManager.peaks
                && c.videoAnnotationManager.peaks.player.getDuration() > 0;
        }""",
        timeout=timeout,
    )


def _set_zoom_seconds(page, secs):
    return page.evaluate(
        """(secs) => {
            const m = document.querySelector('.video-annotation-container').videoAnnotationManager;
            const zv = m.peaks.views.getView('zoomview');
            zv.setZoom({seconds: secs});
            return {viewStart: zv.getStartTime(), viewEnd: zv.getEndTime()};
        }""",
        secs,
    )


def _box(page, selector):
    el = page.wait_for_selector(selector, state="visible", timeout=10000)
    return el.bounding_box()


def _rdrag(page, box, x0f, x1f, hold_ms=0, steps=10):
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * x0f, y)
    page.mouse.down(button="right")
    page.mouse.move(box["x"] + box["width"] * x1f, y, steps=steps)
    if hold_ms:
        page.wait_for_timeout(hold_ms)
    page.mouse.up(button="right")
    page.wait_for_timeout(300)


@pytest.mark.playwright
class TestVideoTimelineUX(BasePlaywrightTest):
    def _login(self, page, server):
        self.register_and_login(page, server)
        page.wait_for_selector(VIDEO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)

    def test_zoomview_right_drag_creates_segment(self, page, video_server):
        self._login(page, video_server)
        before = _video_state(page)
        assert before and before["ready"], "video manager / Peaks not ready"

        box = _box(page, "#zoomview-video_segmentation, .timeline-container")
        _rdrag(page, box, 0.2, 0.5)

        after = _video_state(page)
        assert after["count"] == before["count"] + 1, "zoomview right-drag did not create a segment"

    def test_overview_right_drag_reaches_whole_clip(self, page, video_server):
        self._login(page, video_server)
        _set_zoom_seconds(page, 2)
        page.wait_for_timeout(200)
        state = _video_state(page)
        visible_end = state["viewEnd"]
        assert visible_end < state["duration"] - 0.5, "timeline still shows whole clip"

        ov = _box(page, "#overview-video_segmentation, .overview-container")
        before = _video_state(page)["count"]
        _rdrag(page, ov, 0.75, 0.95)

        after = _video_state(page)
        assert after["count"] == before + 1, "overview right-drag did not create a segment"
        assert after["segs"][-1]["start"] > visible_end, "overview segment not beyond visible window"

    def test_edge_autoscroll_extends_past_window(self, page, video_server):
        self._login(page, video_server)
        _set_zoom_seconds(page, 1.5)
        page.wait_for_timeout(200)
        start_state = _video_state(page)
        initial_view_start = start_state["viewStart"]
        initial_view_end = start_state["viewEnd"]

        box = _box(page, "#zoomview-video_segmentation, .timeline-container")
        _rdrag(page, box, 0.15, 0.99, hold_ms=1400, steps=12)

        end_state = _video_state(page)
        assert end_state["viewStart"] > initial_view_start + 0.1, "timeline did not auto-scroll"
        assert end_state["count"] >= start_state["count"] + 1, "no segment created during edge drag"
        assert end_state["segs"][-1]["end"] > initial_view_end, "segment did not extend past window"

    def test_segments_persist_across_navigation(self, page, video_server):
        self._login(page, video_server)
        first_id = self.get_instance_id(page)

        box = _box(page, "#zoomview-video_segmentation, .timeline-container")
        _rdrag(page, box, 0.2, 0.45)
        _rdrag(page, box, 0.55, 0.8)
        made = _video_state(page)["count"]
        assert made >= 2
        self.wait_for_debounce(page)

        self.click_next(page)
        page.wait_for_selector(VIDEO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)
        assert _video_state(page)["count"] == 0, "fresh instance should have no segments"

        self.click_prev(page)
        page.wait_for_selector(VIDEO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)
        restored = _video_state(page)
        assert self.get_instance_id(page) == first_id
        assert restored["count"] == made, f"expected {made} restored, got {restored['count']}"

    def test_media_path_not_shown_as_header(self, page, video_server):
        self._login(page, video_server)
        visible_text = page.evaluate("() => document.body.innerText")
        assert "/test-video/" not in visible_text, "raw media path leaked into the visible page"
        hidden = page.evaluate(
            "() => { const t = document.getElementById('text-content'); return t ? t.textContent.trim() : null; }"
        )
        assert hidden and "/test-video/" in hidden, "hidden #text-content should retain the media URL"
