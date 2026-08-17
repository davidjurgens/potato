"""
Drawing telemetry, captured from real drawing rather than a synthesised event list.

The unit tests build event lists and assert the summary arithmetic over them.
That is correct arithmetic, and it cannot tell you whether the browser ever
emits the events, whether they carry the schema, whether a session survives to
a flush, or whether the numbers describe the wall clock. One of them did not:
`time_to_first_shape_ms` was measured from the first event rather than from
when the instance appeared, so it read zero whenever the annotator's first act
was drawing — which is most of the time.

Verified against the live SQLite row while writing these: two boxes drawn gave
`shapes_added: 2`, `shapes_drawn: 2`, `vertices_total: 8`, `tool_switches: 2`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

MEDIA = Path("examples/advanced/annotation-telemetry/media").resolve()

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "objects",
    "description": "Box every coloured object.",
    "source_field": "image_url",
    "tools": ["bbox", "polygon", "brush", "eraser"],
    "zoom_enabled": True,
    "pan_enabled": True,
    "labels": [{"name": "block", "color": "#d6604d"},
               {"name": "partial", "color": "#4575b4"}],
}]

TELEMETRY = {
    "enabled": True,
    "fidelity": "events",
    "store_events": True,
    "flush_interval_ms": 10000,
    "disclose_to_annotators": True,
}


@pytest.fixture
def telemetry_server(make_server):
    if not (MEDIA / "scene_1.png").is_file():
        pytest.skip("examples/advanced/annotation-telemetry media is missing")
    return make_server(
        SCHEMES,
        items=[{"id": f"scene_{i}", "image_url": f"/media/scene_{i}.png"}
               for i in (1, 2, 3)],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image_url"},
            "annotation_telemetry": TELEMETRY,
        },
    )


class TestDrawingTelemetry(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "objects")
        page.wait_for_function(
            "() => !!window.annotationTelemetryTracker", timeout=15_000)

    def _events(self, page, schema="objects"):
        return page.evaluate(
            """(schema) => {
                const t = window.annotationTelemetryTracker;
                const s = (t.sessions || {})[schema];
                return s ? s.events.map(e => e.action) : [];
            }""", schema)

    def test_the_annotator_is_told_it_is_recording(self, page, telemetry_server):
        """
        Content-blind capture is still capture. The disclosure is configured,
        so it has to be on screen — not merely in the config object.
        """
        self._open(page, telemetry_server)
        shown = page.evaluate(
            """() => {
                const wanted = (window.annotationTelemetryConfig || {}).disclosure_text;
                if (!wanted) return null;
                const nodes = Array.from(document.querySelectorAll('*')).filter(
                    e => e.children.length === 0
                         && e.textContent.includes(wanted.slice(0, 40)));
                return nodes.map(e => e.offsetParent !== null);
            }""")
        assert shown, "the disclosure text is not in the document at all"
        assert any(shown), "the disclosure is in the DOM but not visible"

    def test_drawing_produces_events_that_name_the_schema(
            self, page, telemetry_server):
        """
        `onTelemetry` drops anything without a schema, silently. An event that
        is emitted but unattributed is the same as no event at all.
        """
        self._open(page, telemetry_server)
        self.draw_bbox_on_image(page, "objects", 0.2, 0.2, 0.5, 0.5, label="block")
        page.wait_for_timeout(300)

        assert "shape_add" in self._events(page), self._events(page)

    def test_time_to_first_shape_measures_from_when_the_image_appeared(
            self, page, telemetry_server):
        """
        The metric this file exists for. The session clock has to start when
        the instance was shown; starting it at the first event made this zero
        whenever that first event was the shape, which is the common case and
        exactly the case the number is supposed to describe.
        """
        self._open(page, telemetry_server)
        # Look before drawing, the way an annotator does.
        page.wait_for_timeout(1500)
        self.draw_bbox_on_image(page, "objects", 0.2, 0.2, 0.5, 0.5, label="block")
        page.wait_for_timeout(300)

        first_shape_at = page.evaluate(
            """() => {
                const s = window.annotationTelemetryTracker.sessions.objects;
                const shape = s.events.find(e => e.action === 'shape_add');
                return shape ? shape.t_ms : null;
            }""")
        assert first_shape_at is not None, "no shape event was recorded"
        assert first_shape_at >= 1000, (
            f"waited 1.5 s before drawing and the metric says {first_shape_at} ms; "
            f"the clock is starting at the first event rather than at display")

    def test_a_session_reaches_the_server_when_it_ends(self, page, telemetry_server):
        """
        Events sitting in a browser are not data. The session flushes when it
        ends — on navigation or unload — not on the interval timer, so this
        drives the ending rather than waiting out the clock.
        """
        self._open(page, telemetry_server)
        self.draw_bbox_on_image(page, "objects", 0.2, 0.2, 0.5, 0.5, label="block")
        page.wait_for_timeout(300)

        posted = page.evaluate(
            """async () => {
                const realFetch = window.fetch;
                let hit = false;
                window.fetch = function (url) {
                    if (String(url).includes('track_annotation_telemetry')) hit = true;
                    return realFetch.apply(this, arguments);
                };
                const t = window.annotationTelemetryTracker;
                t.endAllSessions('test');
                t.flush(false);
                await new Promise(r => setTimeout(r, 1200));
                window.fetch = realFetch;
                return hit;
            }""")
        assert posted, "the ended session never reached /api/track_annotation_telemetry"

    def test_an_instance_that_was_only_looked_at_writes_nothing(
            self, page, telemetry_server):
        """
        Starting the clock at display time must not start a session. Otherwise
        every image an annotator opened and skipped becomes a row — and, worse,
        an answered instance, which ends the task early.
        """
        self._open(page, telemetry_server)
        page.wait_for_timeout(1200)

        sessions = page.evaluate(
            "() => Object.keys(window.annotationTelemetryTracker.sessions || {})")
        assert sessions == [], (
            f"a session exists before the annotator did anything: {sessions}")

    def test_it_counts_what_was_actually_drawn(self, page, telemetry_server):
        self._open(page, telemetry_server)
        self.draw_bbox_on_image(page, "objects", 0.1, 0.1, 0.3, 0.3, label="block")
        self.draw_bbox_on_image(page, "objects", 0.5, 0.5, 0.8, 0.8, label="partial")
        page.wait_for_timeout(300)

        actions = self._events(page)
        assert actions.count("shape_add") == 2, actions
