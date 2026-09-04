"""
Audit 6: the four widgets that let an annotator advance on an unfinished answer,
and the tiered initialiser that gave up silently, driven in a real browser.

These are the assertions the unit and jest suites cannot make. A shortfall
declaration is only worth anything if Next actually stops, and a Peaks
initialiser is only fixed if the things after the throwing line ran.

Run:  pytest tests/playwright/test_audit6_gates.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_config,
    create_test_data_file,
    create_test_directory,
)
from tests.playwright.test_base import BasePlaywrightTest

AUDIO_SCHEMA = "audio_segmentation"
AUDIO_CONTAINER = ".audio-annotation-container"
TIERED_SCHEMA = "speaker_tiers"


# --------------------------------------------------------------------------
# min_segments
# --------------------------------------------------------------------------

# Class-scoped, not module-scoped: FlaskTestServer runs IN THIS PROCESS and
# the two servers below would share the item/user/config singletons, so the
# newest one answers for both ports. Class scope tears each down before the
# next starts.
@pytest.fixture(scope="class")
def min_segments_server():
    """An audio task that asks for two segments and says so."""
    test_dir = create_test_directory("pw_audit6_min_segments")
    data = [
        {"id": "a1", "audio_url": "/test-audio/test_audio_10s.mp3"},
        {"id": "a2", "audio_url": "/test-audio/test_audio_10s.mp3"},
    ]
    data_file = create_test_data_file(test_dir, data, filename="audio.jsonl")
    schemes = [{
        "annotation_type": "audio_annotation",
        "name": AUDIO_SCHEMA,
        "description": "Mark both of the speakers",
        "mode": "label",
        "labels": [
            {"name": "speech", "color": "#4ECDC4", "key_value": "1"},
            {"name": "music", "color": "#FF6B6B", "key_value": "2"},
        ],
        "min_segments": 2,
        "label_requirement": {"required": True},
    }]
    config_file = create_test_config(
        test_dir, schemes, data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "audio_url"},
    )
    server = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start the min_segments server")
    yield server
    server.stop()


def _audio_ready(page, timeout=20000):
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.audio-annotation-container');
            return c && c.audioAnnotationManager
                && c.audioAnnotationManager.isReady === true
                && !!c.audioAnnotationManager.peaks;
        }""",
        timeout=timeout,
    )


def _shortfall(page):
    return page.evaluate(
        """() => {
            const f = document.querySelector('form.audio-annotation');
            return f ? f.getAttribute('data-incomplete-reason') : null;
        }"""
    )


def _instance_id(page):
    """The id in the hidden input, not the optional #instance-id chrome.

    `BasePlaywrightTest.get_instance_id` reads a header element this task's
    layout does not render, so it returns None on both sides of a navigation
    and any comparison against it holds trivially.
    """
    return page.evaluate(
        """() => {
            const el = document.getElementById('instance_id');
            return el ? el.value : null;
        }"""
    )


def _segment_count(page):
    return page.evaluate(
        """() => document.querySelector('.audio-annotation-container')
                     .audioAnnotationManager.segments.length"""
    )


def _rdrag(page, box, x0f, x1f):
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * x0f, y)
    page.mouse.down(button="right")
    page.mouse.move(box["x"] + box["width"] * x1f, y, steps=10)
    page.mouse.up(button="right")
    page.wait_for_timeout(300)


@pytest.mark.playwright
class TestMinSegmentsIsEnforced(BasePlaywrightTest):
    """
    `min_segments: 2` reached the browser as `minSegments` and was read by
    nobody, and `label_requirement.required` never reached it at all -- the
    scheme emitted no `validation` attribute. One segment satisfied both, and
    Next advanced.
    """

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.wait_for_selector(AUDIO_CONTAINER, state="visible", timeout=15000)
        _audio_ready(page)

    def test_one_segment_of_two_blocks_next_and_says_why(self, page, min_segments_server):
        self._open(page, min_segments_server)
        first = _instance_id(page)

        box = page.wait_for_selector(
            f"#waveform-{AUDIO_SCHEMA}, .waveform-container",
            state="visible", timeout=10000).bounding_box()
        _rdrag(page, box, 0.1, 0.3)
        assert _segment_count(page) == 1
        assert _shortfall(page) == "1 of 2 segments marked"

        self.click_next(page)
        page.wait_for_timeout(1200)
        assert _instance_id(page) == first, (
            "Next advanced on one segment of the two the scheme asks for")

        body = page.inner_text("body")
        assert "1 of 2 segments marked" in body, (
            "the annotator is stopped but not told what is missing")

    def test_the_second_segment_clears_the_gate(self, page, min_segments_server):
        self._open(page, min_segments_server)
        first = _instance_id(page)

        box = page.wait_for_selector(
            f"#waveform-{AUDIO_SCHEMA}, .waveform-container",
            state="visible", timeout=10000).bounding_box()
        _rdrag(page, box, 0.1, 0.3)
        _rdrag(page, box, 0.5, 0.75)
        assert _segment_count(page) == 2
        assert _shortfall(page) is None

        self.wait_for_debounce(page)
        self.click_next(page)
        page.wait_for_selector(AUDIO_CONTAINER, state="visible", timeout=15000)
        page.wait_for_timeout(800)
        assert _instance_id(page) != first, (
            "Next did not advance once both segments were marked")


# --------------------------------------------------------------------------
# tiered_annotation: the initialiser that gave up
# --------------------------------------------------------------------------

@pytest.fixture(scope="class")
def tiered_server():
    test_dir = create_test_directory("pw_audit6_tiered")
    data = [{"id": "t1", "audio_url": "/test-audio/test_audio_10s.mp3"}]
    data_file = create_test_data_file(test_dir, data, filename="tiered.jsonl")
    schemes = [{
        "annotation_type": "tiered_annotation",
        "name": TIERED_SCHEMA,
        "description": "Who is speaking",
        "source_field": "audio_url",
        "media_type": "audio",
        "tiers": [{
            "name": "utterance",
            "tier_type": "independent",
            "labels": [
                {"name": "Caller", "color": "#4ECDC4"},
                {"name": "agent", "color": "#FF6B6B"},
            ],
        }],
        "tier_height": 50,
        "zoom_enabled": True,
    }]
    config_file = create_test_config(
        test_dir, schemes, data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "audio_url"},
    )
    server = FlaskTestServer(port=find_free_port(), debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start the tiered server")
    yield server
    server.stop()


@pytest.mark.playwright
class TestTieredInitialiserCompletes(BasePlaywrightTest):
    """
    `zoomview.on('dblclick', ...)` threw on every load -- the bundled Peaks
    build's views are not event emitters -- and the throw escaped into
    `_initPeaks`'s outer try/catch. Everything after the listener wiring was
    skipped: auto-scroll, the initial zoom and start time, the post-layout
    refit, the resize refit, the zoom-range sync, and both seek handlers. The
    widget looked alive because the two listeners registered BEFORE the
    throwing line survived.
    """

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.wait_for_selector(".tiered-annotation-container", state="visible",
                               timeout=15000)
        page.wait_for_function(
            """(schema) => {
                const m = document.getElementById(schema)
                    && document.getElementById(schema)._tieredManager;
                return m && m.mediaMetadata.duration > 0;
            }""",
            arg=TIERED_SCHEMA, timeout=20000)

    def test_peaks_initialises_without_giving_up(self, page, tiered_server):
        warnings = []
        page.on("console", lambda m: warnings.append(m.text)
                if m.type in ("warning", "error") else None)
        self._open(page, tiered_server)
        page.wait_for_timeout(1500)

        failed = [w for w in warnings if "Failed to initialize Peaks.js" in w]
        assert not failed, f"the initialiser still gave up: {failed}"

        assert not [w for w in warnings if "is not a function" in w], (
            f"a Peaks API that does not exist was called: {warnings}")

    def test_double_click_on_the_waveform_seeks(self, page, tiered_server):
        # The observable symptom of the abandoned initialiser: the seek
        # handlers were registered after the throwing line, so double-clicking
        # the waveform left audio.currentTime at 0.0 forever.
        self._open(page, tiered_server)
        page.wait_for_timeout(1000)

        box = page.wait_for_selector(
            f"#zoomview-{TIERED_SCHEMA}, .tiered-zoomview, .tiered-waveform-zoomview",
            state="visible", timeout=10000).bounding_box()
        page.mouse.dblclick(box["x"] + box["width"] * 0.6,
                            box["y"] + box["height"] / 2)
        page.wait_for_timeout(500)

        current = page.evaluate(
            """(schema) => document.getElementById(schema)
                   ._tieredManager.mediaElement.currentTime""",
            TIERED_SCHEMA)
        assert current > 0.1, (
            f"double-clicking the waveform did not move the playhead "
            f"(currentTime={current})")

    def test_the_zoomview_is_configured_after_the_listeners(self, page, tiered_server):
        # enableAutoScroll / setZoom / setStartTime all run AFTER
        # _setupPeaksEventListeners, so the throw took them with it.
        self._open(page, tiered_server)
        page.wait_for_timeout(1000)
        window_seconds = page.evaluate(
            """(schema) => {
                const m = document.getElementById(schema)._tieredManager;
                const zv = m.peaks && m.peaks.views.getView('zoomview');
                if (!zv) return null;
                return zv.getEndTime() - zv.getStartTime();
            }""",
            TIERED_SCHEMA)
        duration = page.evaluate(
            """(schema) => document.getElementById(schema)
                   ._tieredManager.mediaMetadata.duration""",
            TIERED_SCHEMA)
        assert window_seconds is not None, "no zoomview at all"
        assert window_seconds < duration, (
            f"the zoomview still shows the whole {duration:.1f}s clip, so "
            f"setZoom never ran")
