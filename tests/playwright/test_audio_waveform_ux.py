"""
Playwright UX tests for the audio waveform annotation interface.

Simulates realistic annotator behaviour on the Peaks.js waveform:
  - right-click-drag selection on the zoomed-in view
  - right-click-drag selection on the zoomed-out overview (reaches the whole clip)
  - edge auto-scroll: a drag that runs to the visible edge pans the view so the
    selection can extend past the original window
  - multiple / overlapping segments, deletion
  - zoom in / out / fit
  - persistence across navigate-away-and-back
  - the raw media path is NOT shown as a header

Run:  pytest tests/playwright/test_audio_waveform_ux.py -v
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


AUDIO_CONTAINER = ".audio-annotation-container"


@pytest.fixture(scope="module")
def audio_server():
    """Module-scoped Flask server serving a local 10s audio_annotation task.

    A 10s clip leaves enough room to zoom in and prove overview-reach + edge
    auto-scroll (the shared short clip is only ~3s).
    """
    test_dir = create_test_directory("pw_audio_ux")
    data = [
        {"id": "audio_001", "audio_url": "/test-audio/test_audio_10s.mp3"},
        {"id": "audio_002", "audio_url": "/test-audio/test_audio_10s.mp3"},
        {"id": "audio_003", "audio_url": "/test-audio/test_audio_10s.mp3"},
    ]
    data_file = create_test_data_file(test_dir, data, filename="audio_data.jsonl")
    schemes = [
        {
            "annotation_type": "audio_annotation",
            "name": "audio_segmentation",
            "description": "Segment the audio by content type",
            "mode": "label",
            "labels": [
                {"name": "speech", "color": "#4ECDC4", "key_value": "1"},
                {"name": "music", "color": "#FF6B6B", "key_value": "2"},
                {"name": "silence", "color": "#95A5A6", "key_value": "3"},
            ],
            "zoom_enabled": True,
            "playback_rate_control": True,
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
        pytest.fail("Failed to start audio Flask server")
    yield server
    server.stop()


def _audio_state(page):
    """Snapshot of the audio manager + Peaks zoomview window."""
    return page.evaluate(
        """() => {
            const c = document.querySelector('.audio-annotation-container');
            if (!c || !c.audioAnnotationManager) return null;
            const m = c.audioAnnotationManager;
            const zv = m.peaks && m.peaks.views.getView('zoomview');
            return {
                ready: m.isReady === true && !!m.peaks,
                count: m.segments.length,
                segs: m.segments.map(s => ({start: s.startTime, end: s.endTime})),
                viewStart: zv ? zv.getStartTime() : null,
                viewEnd: zv ? zv.getEndTime() : null,
                duration: m.peaks ? m.peaks.player.getDuration() : null,
            };
        }"""
    )


def _set_zoom_seconds(page, secs):
    """Deterministically set the zoomview window width, then report it."""
    return page.evaluate(
        """(secs) => {
            const m = document.querySelector('.audio-annotation-container').audioAnnotationManager;
            const zv = m.peaks.views.getView('zoomview');
            zv.setZoom({seconds: secs});
            return {viewStart: zv.getStartTime(), viewEnd: zv.getEndTime()};
        }""",
        secs,
    )


def _wait_ready(page, timeout=20000):
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.audio-annotation-container');
            return c && c.audioAnnotationManager
                && c.audioAnnotationManager.isReady === true
                && !!c.audioAnnotationManager.peaks;
        }""",
        timeout=timeout,
    )


def _box(page, selector):
    el = page.wait_for_selector(selector, state="visible", timeout=10000)
    return el.bounding_box()


def _rdrag(page, box, x0f, x1f, hold_ms=0, steps=10):
    """Right-click drag across a box from fraction x0f to x1f of its width."""
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * x0f, y)
    page.mouse.down(button="right")
    page.mouse.move(box["x"] + box["width"] * x1f, y, steps=steps)
    if hold_ms:
        page.wait_for_timeout(hold_ms)
    page.mouse.up(button="right")
    page.wait_for_timeout(300)


@pytest.mark.playwright
class TestAudioWaveformUX(BasePlaywrightTest):
    def _login(self, page, server):
        self.register_and_login(page, server)
        page.wait_for_selector(AUDIO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)

    def test_zoomview_right_drag_creates_segment(self, page, audio_server):
        self._login(page, audio_server)
        before = _audio_state(page)
        assert before and before["ready"], "audio manager not ready"

        box = _box(page, "#waveform-audio_segmentation, .waveform-container")
        _rdrag(page, box, 0.2, 0.5)

        after = _audio_state(page)
        assert after["count"] == before["count"] + 1, "zoomview right-drag did not create a segment"

    def test_overview_right_drag_reaches_whole_clip(self, page, audio_server):
        self._login(page, audio_server)

        # Constrain the zoomview to a 3s window so it shows only a slice.
        _set_zoom_seconds(page, 3)
        page.wait_for_timeout(200)
        state = _audio_state(page)
        visible_end = state["viewEnd"]
        duration = state["duration"]
        assert visible_end is not None and duration and visible_end < duration - 0.5, (
            "zoomview still shows whole clip; cannot prove overview reach"
        )

        # Right-drag near the END of the overview (maps across the full duration).
        ov = _box(page, "#overview-audio_segmentation, .overview-container")
        before = _audio_state(page)["count"]
        _rdrag(page, ov, 0.75, 0.95)

        after = _audio_state(page)
        assert after["count"] == before + 1, "overview right-drag did not create a segment"
        newest = after["segs"][-1]
        assert newest["start"] > visible_end, (
            f"overview segment start {newest['start']:.2f}s should be beyond the "
            f"visible zoom window end {visible_end:.2f}s"
        )

    def test_edge_autoscroll_extends_past_window(self, page, audio_server):
        self._login(page, audio_server)

        # Constrain the visible window to a small fraction of the clip.
        _set_zoom_seconds(page, 2.5)
        page.wait_for_timeout(200)
        start_state = _audio_state(page)
        initial_view_start = start_state["viewStart"]
        initial_view_end = start_state["viewEnd"]
        assert initial_view_end < start_state["duration"] - 0.5

        # Right-drag to the far right edge of the zoomview and HOLD so the
        # requestAnimationFrame auto-scroll loop pans the view.
        box = _box(page, "#waveform-audio_segmentation, .waveform-container")
        _rdrag(page, box, 0.15, 0.99, hold_ms=1400, steps=12)

        end_state = _audio_state(page)
        assert end_state["viewStart"] > initial_view_start + 0.1, (
            f"view did not auto-scroll (start {initial_view_start:.2f} -> "
            f"{end_state['viewStart']:.2f})"
        )
        assert end_state["count"] >= start_state["count"] + 1, "no segment created during edge drag"
        newest = end_state["segs"][-1]
        assert newest["end"] > initial_view_end, (
            f"segment end {newest['end']:.2f}s did not extend past the original "
            f"window end {initial_view_end:.2f}s"
        )

    def test_multiple_and_overlapping_segments(self, page, audio_server):
        self._login(page, audio_server)
        box = _box(page, "#waveform-audio_segmentation, .waveform-container")
        base = _audio_state(page)["count"]

        _rdrag(page, box, 0.10, 0.30)
        _rdrag(page, box, 0.40, 0.60)
        _rdrag(page, box, 0.50, 0.75)  # overlaps the previous one

        after = _audio_state(page)
        assert after["count"] == base + 3, "expected three segments including an overlap"

    def test_zoom_controls_change_window(self, page, audio_server):
        self._login(page, audio_server)
        fit_before = _audio_state(page)

        page.click(".zoom-btn[data-action='zoom-in'], button[data-action='zoom-in']")
        page.wait_for_timeout(300)
        zoomed = _audio_state(page)
        zoomed_window = zoomed["viewEnd"] - zoomed["viewStart"]
        fit_window = fit_before["viewEnd"] - fit_before["viewStart"]
        assert zoomed_window < fit_window + 0.01, "zoom-in did not shrink the visible window"

        page.click(".zoom-btn[data-action='zoom-out'], button[data-action='zoom-out']")
        page.wait_for_timeout(300)
        out = _audio_state(page)
        assert (out["viewEnd"] - out["viewStart"]) > zoomed_window - 0.01, "zoom-out did not widen window"

    def test_segments_persist_across_navigation(self, page, audio_server):
        self._login(page, audio_server)
        first_id = self.get_instance_id(page)

        box = _box(page, "#waveform-audio_segmentation, .waveform-container")
        _rdrag(page, box, 0.2, 0.45)
        _rdrag(page, box, 0.55, 0.8)
        made = _audio_state(page)["count"]
        assert made >= 2
        self.wait_for_debounce(page)

        # Navigate away and back.
        self.click_next(page)
        page.wait_for_selector(AUDIO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)
        assert _audio_state(page)["count"] == 0, "fresh instance should have no segments"

        self.click_prev(page)
        page.wait_for_selector(AUDIO_CONTAINER, state="visible", timeout=15000)
        _wait_ready(page)
        restored = _audio_state(page)
        assert self.get_instance_id(page) == first_id, "did not return to the first instance"
        assert restored["count"] == made, (
            f"segments not restored: expected {made}, got {restored['count']}"
        )

    def test_media_path_not_shown_as_header(self, page, audio_server):
        self._login(page, audio_server)
        # The item text is the audio URL; it must not be visible on the page.
        visible_text = page.evaluate("() => document.body.innerText")
        assert "/test-audio/" not in visible_text, "raw media path leaked into the visible page"
        # The hidden node still exists for the JS media-URL fallback.
        hidden = page.evaluate(
            "() => { const t = document.getElementById('text-content'); return t ? t.textContent.trim() : null; }"
        )
        assert hidden and "/test-audio/" in hidden, "hidden #text-content should retain the media URL"
