"""
Base helpers for Playwright annotation tests.

Provides ``BasePlaywrightTest`` — a mixin that mirrors the Selenium
``BaseSeleniumTest`` API: auto-register, auto-login, and a
``verify_server_annotations()`` helper that hits the ``/get_annotations``
API to confirm persistence (the gold standard).

Usage:
    import pytest
    from tests.playwright.test_base import BasePlaywrightTest

    @pytest.mark.playwright
    class TestMySchema(BasePlaywrightTest):
        def test_something(self, page, server):
            self.register_and_login(page, server)
            page.goto(f"{server.base_url}/annotate")
            # ... interact ...
            anns = self.verify_server_annotations(page, server, "instance_0")
            assert "my_schema" in anns
"""

import time
import json
import pytest

try:
    from playwright.sync_api import expect, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@pytest.mark.playwright
class BasePlaywrightTest:
    """Mixin providing auth helpers and annotation verification for Playwright tests."""

    _user_counter = 0

    @classmethod
    def _next_user(cls):
        cls._user_counter += 1
        return f"pw_user_{cls.__name__}_{cls._user_counter}_{int(time.time())}"

    # ---- auth ----

    def register_and_login(self, page: "Page", server, username=None):
        """Register and log in a unique user, ending up on the annotation page.

        Works for both ``require_password=False`` (simple login) and
        ``require_password=True`` (register tab + login tab) flows.
        """
        if username is None:
            username = self._next_user()
        self._current_user = username

        page.goto(f"{server.base_url}/")
        page.wait_for_selector("#login-email", timeout=10_000)

        # Detect password mode
        register_tab = page.query_selector("#register-tab")
        if register_tab:
            # Password mode — register first
            register_tab.click()
            page.wait_for_selector("#register-content", state="visible")
            page.fill("#register-email", username)
            page.fill("#register-pass", "test_password_123")
            page.click("#register-content form button[type='submit'], #register-content form input[type='submit']")
            page.wait_for_timeout(500)

            # Now login
            page.goto(f"{server.base_url}/")
            login_tab = page.query_selector("#login-tab")
            if login_tab:
                login_tab.click()
            page.wait_for_selector("#login-email", state="visible")
            page.fill("#login-email", username)
            page.fill("#login-pass", "test_password_123")
            page.click("#login-content form button[type='submit'], #login-content form input[type='submit']")
        else:
            # Simple mode
            page.fill("#login-email", username)
            page.click("button[type='submit']")

        # Wait for annotation interface
        page.wait_for_selector("#main-content", state="visible", timeout=15_000)
        return username

    # ---- annotation verification ----

    def verify_server_annotations(self, page: "Page", server, instance_id):
        """Hit the ``/get_annotations`` API and return the parsed JSON.

        This is the gold-standard check — it reads from the server's
        in-memory state, bypassing any browser caching.
        """
        resp = page.request.get(
            f"{server.base_url}/get_annotations?instance_id={instance_id}"
        )
        assert resp.ok, f"/get_annotations returned {resp.status}"
        return resp.json()

    # ---- navigation helpers ----

    def click_next(self, page: "Page"):
        """Click the Next button and wait for new content to load."""
        page.click("#next-instance-btn, #annotate-next-btn, button:has-text('Next')")
        page.wait_for_timeout(500)

    def click_prev(self, page: "Page"):
        """Click the Previous button and wait for content to load."""
        page.click("#prev-instance-btn, #annotate-prev-btn, button:has-text('Previous'), button:has-text('Prev')")
        page.wait_for_timeout(500)

    def wait_for_debounce(self, page: "Page", ms=1500):
        """Wait long enough for the annotation debounce timer to fire."""
        page.wait_for_timeout(ms)

    # ---- JS helpers ----

    def get_current_annotations(self, page: "Page"):
        """Return the in-browser ``currentAnnotations`` object."""
        return page.evaluate("() => window.currentAnnotations || {}")

    def get_instance_id(self, page: "Page"):
        """Return the current instance ID shown in the browser."""
        return page.evaluate("""() => {
            const el = document.getElementById('instance-id');
            return el ? el.textContent.trim() : null;
        }""")

    # ---- image-annotation canvas helpers ----
    #
    # A fabric canvas is one <canvas> element: there is nothing in the DOM to
    # click at, and Playwright's element selectors cannot reach a shape. These
    # drive the manager through the same entry points the UI uses, and read
    # state back from the hidden input the save path actually collects -- not
    # from anything the test itself put there.

    def image_manager_ready(self, page: "Page", schema: str, timeout=15_000):
        """Wait until the ImageAnnotationManager exists and its image has loaded.

        Drawing before the image loads silently produces nothing, because the
        manager converts screen coordinates through `this.image`.
        """
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                return !!(c && c.annotationManager && c.annotationManager.image);
            }""",
            arg=schema,
            timeout=timeout,
        )

    def select_tool(self, page: "Page", schema: str, tool: str):
        """Arm a drawing tool by clicking its toolbar button.

        Clicking rather than calling setTool() directly: the button click is
        what also syncs `active` classes and `aria-pressed`, and a test that
        bypasses it would not notice those breaking.
        """
        page.click(
            f'.image-annotation-container[data-schema="{schema}"] '
            f'.tool-btn[data-tool="{tool}"]')

    def select_label(self, page: "Page", schema: str, label: str):
        """Arm a label by clicking its button."""
        page.click(
            f'.image-annotation-container[data-schema="{schema}"] '
            f'.label-btn[data-label="{label}"]')

    def image_rect(self, page: "Page", schema: str):
        """Where the image sits on the canvas, in canvas pixels.

        The image is scaled to fit and centred, so canvas (0, 0) is usually
        *outside* it. Drawing there produces negative normalized coordinates —
        correct behaviour, but rarely what a test means.

        Goes through the viewport transform, which is not a refinement: under
        `viewer: deepzoom` the image object is a placeholder at (0, 0) with
        scale 1 and the transform carries the whole of the scaling, so reading
        `img.left`/`img.scaleX` alone would report image-pixel coordinates as
        though they were canvas pixels and every drag would land somewhere
        else. It is the same calculation `_renderAllMasks` uses, for the same
        reason.
        """
        return page.evaluate(
            """(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                const manager = c && c.annotationManager;
                const img = manager && manager.image;
                if (!img) return null;
                const vpt = manager.canvas.viewportTransform;
                const zoom = manager.canvas.getZoom();
                return {
                    left: img.left * zoom + vpt[4],
                    top: img.top * zoom + vpt[5],
                    width: img.width * img.scaleX * zoom,
                    height: img.height * img.scaleY * zoom,
                };
            }""",
            arg=schema,
        )

    def arm(self, page: "Page", schema: str, tool: str, label=None):
        """Select the label and tool, then let the layout settle.

        Arming CHANGES THE LAYOUT — measured: clicking a tool button took the
        canvas element from 800 CSS px wide to 858, which fires the manager's
        ResizeObserver and re-fits the image, moving the picture inside the
        canvas. So the image rect must be read after this, never before.

        Reading it first is what `draw_bbox_on_image` used to do, and it put
        every box ~29 px left of where the test asked for. Nothing caught it
        because the tests that draw do not assert where the result landed.
        """
        if label:
            self.select_label(page, schema, label)
        if tool:
            self.select_tool(page, schema, tool)
        # One rendered frame, so a resize triggered by the click is applied
        # before anything measures.
        page.evaluate("() => new Promise(requestAnimationFrame)")

    def draw_bbox_on_image(self, page: "Page", schema: str,
                           fx0, fy0, fx1, fy1, label=None):
        """Draw a bbox using IMAGE-relative fractions (0-1), not canvas pixels.

        This is the unit the stored contract uses, and it keeps a test from
        accidentally drawing outside the image just because the canvas is
        larger than the picture.
        """
        self.arm(page, schema, "bbox", label)
        rect = self.image_rect(page, schema)
        assert rect, f"no image loaded for schema '{schema}'"
        return self.draw_bbox(
            page, schema,
            rect["left"] + fx0 * rect["width"], rect["top"] + fy0 * rect["height"],
            rect["left"] + fx1 * rect["width"], rect["top"] + fy1 * rect["height"],
            armed=True,
        )

    def drag_shape_on_image(self, page: "Page", schema: str, tool,
                            fx0, fy0, fx1, fy1, label=None):
        """Drag any drag-drawn tool (bbox, ellipse, the cuboid front face).

        Same arm-then-measure order as `draw_bbox_on_image`, for the same
        reason.
        """
        self.arm(page, schema, tool, label)
        rect = self.image_rect(page, schema)
        assert rect, f"no image loaded for schema '{schema}'"
        canvas = page.locator(f"#canvas-{schema}")
        box = canvas.bounding_box()
        assert box, f"canvas-{schema} has no layout box"

        def at(fx, fy):
            return (box["x"] + rect["left"] + fx * rect["width"],
                    box["y"] + rect["top"] + fy * rect["height"])

        start, end = at(fx0, fy0), at(fx1, fy1)
        page.mouse.move(*start)
        page.mouse.down()
        # Fabric needs an intermediate move to register a drag rather than a
        # click, and the tools that size themselves while dragging need one to
        # have any size at all.
        page.mouse.move((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        page.mouse.move(*end)
        page.mouse.up()

    def click_points_on_image(self, page: "Page", schema: str, tool, points,
                              label=None, complete=False, arm=True):
        """Click a sequence of image-relative points with a click-built tool.

        Polygons, polylines and skeletons are built one click at a time. Pass
        `complete=True` to double-click the last point, which is how a polygon
        or an unfinished skeleton is committed.

        Pass `arm=False` to continue a shape already in progress. Re-selecting
        a tool clears `cuboidFront`, `polygonPoints` and `keypointPoints` on
        purpose — a half-finished shape must not survive a tool switch — so
        re-arming between the two halves of a cuboid throws the front face away
        and the second click silently starts a new one.
        """
        if arm:
            self.arm(page, schema, tool, label)
        rect = self.image_rect(page, schema)
        assert rect, f"no image loaded for schema '{schema}'"
        box = page.locator(f"#canvas-{schema}").bounding_box()
        assert box, f"canvas-{schema} has no layout box"

        last = None
        for fx, fy in points:
            last = (box["x"] + rect["left"] + fx * rect["width"],
                    box["y"] + rect["top"] + fy * rect["height"])
            page.mouse.click(*last)
        if complete and last:
            page.mouse.dblclick(*last)

    def paint_stroke_on_image(self, page: "Page", schema: str, points,
                              label=None, tool="brush"):
        """Paint a stroke using IMAGE-relative fractions (0-1)."""
        self.arm(page, schema, tool, label)
        rect = self.image_rect(page, schema)
        assert rect, f"no image loaded for schema '{schema}'"
        return self.paint_stroke(
            page, schema,
            [(rect["left"] + fx * rect["width"], rect["top"] + fy * rect["height"])
             for fx, fy in points],
            tool=tool, armed=True,
        )

    def draw_bbox(self, page: "Page", schema: str, x0, y0, x1, y1, label=None,
                  armed=False):
        """Drag a bounding box on the canvas, in CANVAS pixel coordinates.

        Uses real mouse events so the manager's own mouse:down/move/up path
        runs — the same code an annotator exercises.

        Pass ``armed=True`` when the caller has already selected the tool and
        measured afterwards; arming here would move the picture out from under
        coordinates that were computed against the previous layout.
        """
        if not armed:
            if label:
                self.select_label(page, schema, label)
            self.select_tool(page, schema, "bbox")

        canvas = page.locator(f"#canvas-{schema}")
        box = canvas.bounding_box()
        assert box, f"canvas-{schema} has no layout box (is it visible?)"

        page.mouse.move(box["x"] + x0, box["y"] + y0)
        page.mouse.down()
        # Fabric needs at least one intermediate move to register a drag.
        page.mouse.move(box["x"] + (x0 + x1) / 2, box["y"] + (y0 + y1) / 2)
        page.mouse.move(box["x"] + x1, box["y"] + y1)
        page.mouse.up()

    def paint_stroke(self, page: "Page", schema: str, points, label=None,
                     tool="brush", armed=False):
        """Paint a mask stroke through a list of (x, y) canvas points.

        Mask events are bound to the *mask* canvas overlay, not the fabric one,
        so this targets that element deliberately.

        ``armed=True`` when the caller already selected the tool — see
        ``draw_bbox``.
        """
        if not armed:
            if label:
                self.select_label(page, schema, label)
            self.select_tool(page, schema, tool)

        mask = page.locator(f"#mask-canvas-{schema}")
        box = mask.bounding_box()
        assert box, f"mask-canvas-{schema} has no layout box"

        first = points[0]
        page.mouse.move(box["x"] + first[0], box["y"] + first[1])
        page.mouse.down()
        for x, y in points[1:]:
            page.mouse.move(box["x"] + x, box["y"] + y)
        page.mouse.up()

    def read_annotation_data(self, page: "Page", schema: str):
        """Parse the hidden input the save path collects.

        This is the client contract as actually written -- normalized
        coordinates under `coordinates`, masks as absolute RLE. Reading the
        manager's in-memory state instead would hide serialization bugs, which
        is precisely how the exporters stayed broken for so long.
        """
        raw = page.evaluate(
            """(schema) => {
                const el = document.getElementById('input-' + schema);
                return el ? el.value : null;
            }""",
            arg=schema,
        )
        if not raw:
            return []
        return json.loads(raw)

    def count_annotations(self, page: "Page", schema: str):
        """Annotation count as the manager reports it (shapes plus masks)."""
        return page.evaluate(
            """(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                return c && c.annotationManager
                    ? c.annotationManager.getAnnotationCount() : null;
            }""",
            arg=schema,
        )

    def assert_persists_across_navigation(self, page: "Page", schema: str,
                                          expected_types=None):
        """Navigate away and back, then assert the annotations returned.

        NOT a page refresh. Browsers restore form state across a refresh, so a
        refresh-based test passes even when the server never stored anything --
        a recurring source of false-positive persistence tests in this repo.
        Going forward and back forces a real server round trip.

        Returns the reloaded annotation list so callers can assert further.
        """
        before = self.read_annotation_data(page, schema)
        assert before, "nothing to test: no annotations before navigating"

        self.wait_for_debounce(page)
        self.click_next(page)
        self.click_prev(page)
        self.image_manager_ready(page, schema)

        after = self.read_annotation_data(page, schema)
        assert after, (
            f"annotations for '{schema}' were lost on navigation "
            f"({len(before)} before, 0 after)")
        assert len(after) == len(before), (
            f"annotation count changed across navigation: "
            f"{len(before)} -> {len(after)}")

        if expected_types is not None:
            assert sorted(a.get("type") for a in after) == sorted(expected_types)
        return after
