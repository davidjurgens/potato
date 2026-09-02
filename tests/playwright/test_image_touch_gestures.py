"""
Pinch-to-zoom and two-finger pan on the image canvas, from a touch device.

## The defect these cover

Panning was gated on `evt.altKey || this._spaceKeyDown` — both keyboard state.
A tablet held in two hands has neither, so once an annotator zoomed in there was
**no way to reach the rest of the image**. Not awkward: no gesture, no modifier,
no button. Zoom at least had the toolbar's +/−/Fit; pan had nothing at all.

That mattered because drawing already worked on touch (fabric normalizes the
first touch into its mouse events), and a stylus is a genuinely good surface for
tracing a boundary. Pan was the one missing piece.

## Why these use CDP rather than Playwright's touchscreen API

`page.touchscreen.tap()` sends a single touch point. A pinch needs two
simultaneously, which only the raw `Input.dispatchTouchEvent` CDP command can
express. The context must also be created with `has_touch=True`, or the client
never installs the handlers — they are gated on `'ontouchstart' in window`.
"""

import pytest

from tests.playwright.test_base import BasePlaywrightTest

SCHEMA = "objects"
TEST_IMAGE = "test_image_400x300.png"

IMAGE_SCHEME = {
    "annotation_type": "image_annotation",
    "name": SCHEMA,
    "description": "Mark the objects",
    "source_field": "image_url",
    "tools": ["bbox", "brush"],
    "labels": [{"name": "car", "color": "#FF0000"}],
}


@pytest.fixture(scope="module")
def touch_server():
    from tests.playwright.conftest import _make_server

    items = [{"id": f"img_{i}", "image_url": f"/test-image/{TEST_IMAGE}"}
             for i in range(3)]
    srv = _make_server(
        [IMAGE_SCHEME],
        items=items,
        extra_config={"item_properties": {"id_key": "id", "text_key": "image_url"}},
    )
    yield srv
    srv.stop()


@pytest.fixture
def touch_page(browser_instance):
    """
    A context that reports touch support.

    Without `has_touch=True` the browser omits `ontouchstart`, the gesture
    handlers are never installed, and every test here would pass or fail for
    the wrong reason.
    """
    context = browser_instance.new_context(
        viewport={"width": 1024, "height": 1366},   # iPad Pro portrait
        has_touch=True,
        is_mobile=False,     # a tablet, not a phone
        ignore_https_errors=True,
    )
    page = context.new_page()
    yield page
    page.close()
    context.close()


@pytest.mark.playwright
class TestTouchGestures(BasePlaywrightTest):

    # -- helpers ---------------------------------------------------------

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, SCHEMA)

    def _canvas_box(self, page):
        return page.locator(f"#canvas-{SCHEMA}").bounding_box()

    def _touch(self, page, kind, points):
        """One raw touch event with N simultaneous points, via CDP."""
        session = getattr(self, "_cdp", None)
        if session is None:
            session = self._cdp = page.context.new_cdp_session(page)
        session.send("Input.dispatchTouchEvent", {
            "type": kind,
            "touchPoints": [{"x": x, "y": y} for x, y in points],
        })

    def _viewport_transform(self, page):
        return page.evaluate(f"""() => {{
            const el = document.querySelector('#canvas-{SCHEMA}')
                .closest('.image-annotation-container');
            return Array.from(el.annotationManager.canvas.viewportTransform);
        }}""")

    def _pinch(self, page, from_gap, to_gap, steps=6, drift=(0, 0)):
        """Two fingers moving symmetrically about the canvas centre."""
        box = self._canvas_box(page)
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        def pair(gap, offset):
            return [(cx - gap / 2 + offset[0], cy + offset[1]),
                    (cx + gap / 2 + offset[0], cy + offset[1])]

        self._touch(page, "touchStart", pair(from_gap, (0, 0)))
        for step in range(1, steps + 1):
            ratio = step / steps
            gap = from_gap + (to_gap - from_gap) * ratio
            offset = (drift[0] * ratio, drift[1] * ratio)
            self._touch(page, "touchMove", pair(gap, offset))
            page.wait_for_timeout(16)
        self._touch(page, "touchEnd", [])
        page.wait_for_timeout(80)

    # -- the gate --------------------------------------------------------

    def test_the_context_actually_reports_touch(self, touch_page, touch_server):
        """
        The handlers are installed only when `ontouchstart` exists. If this
        assertion ever fails, every other test in the file is vacuous.
        """
        self._open(touch_page, touch_server)
        assert touch_page.evaluate("() => 'ontouchstart' in window") is True

    # -- pan, the thing that was impossible ------------------------------

    def test_two_fingers_pan_without_a_keyboard(self, touch_page, touch_server):
        """
        The headline. No Alt, no Space, no mouse — and the viewport moves.
        """
        self._open(touch_page, touch_server)
        before = self._viewport_transform(touch_page)

        # Constant gap: a pure translation, so this isolates pan from zoom.
        self._pinch(touch_page, 200, 200, drift=(120, 60))

        after = self._viewport_transform(touch_page)
        assert abs(after[4] - before[4]) > 50, (
            f"the canvas did not pan horizontally: {before} -> {after}")
        assert abs(after[5] - before[5]) > 20, (
            f"the canvas did not pan vertically: {before} -> {after}")

    def test_pan_survives_being_zoomed_in(self, touch_page, touch_server):
        """
        The situation the annotator was actually stuck in: zoomed in, with the
        rest of the image unreachable.
        """
        self._open(touch_page, touch_server)
        touch_page.evaluate(f"""() => {{
            const el = document.querySelector('#canvas-{SCHEMA}')
                .closest('.image-annotation-container');
            el.annotationManager.zoom(2.5);
        }}""")
        touch_page.wait_for_timeout(50)

        before = self._viewport_transform(touch_page)
        self._pinch(touch_page, 200, 200, drift=(150, 0))
        after = self._viewport_transform(touch_page)

        assert abs(after[4] - before[4]) > 50

    # -- pinch zoom ------------------------------------------------------

    def test_spreading_two_fingers_zooms_in(self, touch_page, touch_server):
        self._open(touch_page, touch_server)
        before = self._viewport_transform(touch_page)[0]

        self._pinch(touch_page, 120, 360)

        after = self._viewport_transform(touch_page)[0]
        assert after > before * 1.5, f"zoom did not increase: {before} -> {after}"

    def test_closing_two_fingers_zooms_out(self, touch_page, touch_server):
        self._open(touch_page, touch_server)
        touch_page.evaluate(f"""() => {{
            const el = document.querySelector('#canvas-{SCHEMA}')
                .closest('.image-annotation-container');
            el.annotationManager.zoom(3);
        }}""")
        touch_page.wait_for_timeout(50)
        before = self._viewport_transform(touch_page)[0]

        self._pinch(touch_page, 360, 120)

        after = self._viewport_transform(touch_page)[0]
        assert after < before * 0.8, f"zoom did not decrease: {before} -> {after}"

    def test_zoom_is_clamped_the_same_way_the_buttons_are(self, touch_page,
                                                          touch_server):
        """
        A pinch must not reach a magnification the toolbar refuses, or the two
        paths disagree about what the limits are.
        """
        self._open(touch_page, touch_server)
        for _ in range(6):
            self._pinch(touch_page, 100, 400)
        assert self._viewport_transform(touch_page)[0] <= 10.0 + 1e-6

    # -- it must not break drawing ---------------------------------------

    def test_a_pinch_leaves_no_stray_annotation(self, touch_page, touch_server):
        """
        The first finger already told fabric a drag had begun. Without an
        explicit abort, every pinch commits a speck of a bbox — an annotation
        the annotator never drew and would have to find and delete.
        """
        self._open(touch_page, touch_server)
        assert self.count_annotations(touch_page, SCHEMA) == 0

        self._pinch(touch_page, 120, 320, drift=(40, 40))

        assert self.count_annotations(touch_page, SCHEMA) == 0, (
            "a pinch created an annotation")

    def test_one_finger_still_draws(self, touch_page, touch_server):
        """
        Two fingers pan; ONE finger must still draw. Stealing the single-touch
        gesture for panning would trade a missing feature for a broken one.
        """
        self._open(touch_page, touch_server)
        box = self._canvas_box(touch_page)
        start = (box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
        end = (box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.6)

        self._touch(touch_page, "touchStart", [start])
        for step in range(1, 6):
            ratio = step / 5
            self._touch(touch_page, "touchMove", [(
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio)])
            touch_page.wait_for_timeout(16)
        self._touch(touch_page, "touchEnd", [])
        touch_page.wait_for_timeout(200)

        data = self.read_annotation_data(touch_page, SCHEMA)
        assert len(data) == 1, f"one-finger drag did not draw a shape: {data}"
        assert data[0]["type"] == "bbox"

    def test_a_shape_drawn_after_panning_lands_where_it_was_drawn(
            self, touch_page, touch_server):
        """
        The coordinate check. Panning changes the viewport transform, and a
        shape drawn afterwards must still store NORMALIZED image coordinates —
        otherwise touch users silently produce annotations that every exporter
        reads at the wrong place.
        """
        self._open(touch_page, touch_server)
        self._pinch(touch_page, 200, 200, drift=(80, 40))

        box = self._canvas_box(touch_page)
        start = (box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.4)
        end = (box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.55)
        self._touch(touch_page, "touchStart", [start])
        for step in range(1, 6):
            ratio = step / 5
            self._touch(touch_page, "touchMove", [(
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio)])
            touch_page.wait_for_timeout(16)
        self._touch(touch_page, "touchEnd", [])
        touch_page.wait_for_timeout(200)

        data = self.read_annotation_data(touch_page, SCHEMA)
        assert len(data) == 1
        for key, value in data[0]["coordinates"].items():
            assert 0.0 <= value <= 1.0, (
                f"{key}={value} is not normalized after a pan")
