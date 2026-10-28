"""
The deep-zoom viewer's layout: the slide fits at home, nothing is squashed,
and every shape sits on the slide pixels it describes.

Two bugs, both released, both invisible to the tests that compare fabric's
transform with OpenSeadragon's own answer (they agreed with each other while
both were wrong):

* The fabric canvas kept its 600 px fallback height in a 496 px box, and that
  600 was handed to OpenSeadragon as its container size. OpenSeadragon drew a
  600-tall frame into a 496-tall element, so the slide was squashed
  vertically while the shapes were not, and they drew lower than the tissue
  by more the further down the slide they were.
* OpenSeadragon is built before the page is laid out, opens into a 1x1
  element and homes there. Its resize keeps the zoom, so a slide wider than
  a square fitted by width and its bottom was cut off at the home view.

So these tests measure the page: element rects, the drawing canvas's backing
size, and the screen pixels under a shape.
"""

import json
import os
from io import BytesIO

import pytest
import yaml

pytest.importorskip("playwright.sync_api")
pytest.importorskip("PIL")

from tests.playwright.test_base import BasePlaywrightTest  # noqa: E402

SCHEMA = "regions"
W, H = 1600, 1200
# A dark square low on the slide, where the vertical error was largest, and a
# pre-annotated polygon on exactly its corners.
SQUARE = (1200, 900, 1400, 1100)
DARK = (0x20, 0x20, 0x20)


@pytest.fixture(scope="module")
def layout_server():
    from PIL import Image, ImageDraw

    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("playwright_deepzoom_layout")
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    image = Image.new("RGB", (W, H), "white")
    ImageDraw.Draw(image).rectangle(
        [SQUARE[0], SQUARE[1], SQUARE[2] - 1, SQUARE[3] - 1], fill=DARK)
    image.save(os.path.join(media, "slide.png"))

    x0, y0, x1, y1 = (SQUARE[0] / W, SQUARE[1] / H, SQUARE[2] / W, SQUARE[3] / H)
    region = {"type": "polygon", "label": "tissue",
              "coordinates": [{"x": x0, "y": y0}, {"x": x1, "y": y0},
                              {"x": x1, "y": y1}, {"x": x0, "y": y1}]}
    items = [{"id": f"slide_{i}", "image": "slide.png",
              "predictions": {SCHEMA: [region]}} for i in range(2)]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "Deep zoom layout",
        "task_dir": test_dir,
        "media_directory": media,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "pre_annotation": {"enabled": True, "field": "predictions",
                           "allow_modification": True},
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Correct the regions",
            "source_field": "image",
            "viewer": "deepzoom",
            "tools": ["polygon", "bbox"],
            "labels": [{"name": "tissue", "color": "#c0397b"}],
        }],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    server = FlaskTestServer(port=find_free_port(), debug=False,
                             config_file=config_path)
    if not server.start():
        pytest.fail("Failed to start the deep-zoom layout server")
    yield server
    server.stop()


MEASURE = """(args) => {
    const [schema, points] = args;
    const c = document.querySelector(
        `.image-annotation-container[data-schema="${schema}"]`);
    const m = c.annotationManager;
    const viewer = m.deepZoom.viewer;
    const item = viewer.world.getItemAt(0);
    const rect = (el) => {
        const b = el.getBoundingClientRect();
        return [b.left, b.top, b.width, b.height];
    };
    const host = c.querySelector('.deepzoom-host');
    const hostRect = host.getBoundingClientRect();
    const fabricRect = m.canvas.lowerCanvasEl.getBoundingClientRect();
    const vpt = m.canvas.viewportTransform;
    const drawer = viewer.drawer.canvas;
    const size = item.getContentSize();
    const tl = item.imageToViewerElementCoordinates(new OpenSeadragon.Point(0, 0));
    const br = item.imageToViewerElementCoordinates(
        new OpenSeadragon.Point(size.x, size.y));
    return {
        host: rect(host), osd: rect(drawer), fabric: rect(m.canvas.lowerCanvasEl),
        upper: rect(m.canvas.upperCanvasEl),
        // The drawing canvas's backing store in CSS pixels. When this is not
        // the element's size the browser stretches the frame to fit.
        osdBacking: [drawer.width / window.devicePixelRatio,
                     drawer.height / window.devicePixelRatio],
        image: [hostRect.left + tl.x, hostRect.top + tl.y,
                hostRect.left + br.x, hostRect.top + br.y],
        zoom: viewer.viewport.getZoom(true),
        homeZoom: viewer.viewport.getHomeZoom(),
        // Each image point, as OpenSeadragon places it and as fabric draws it,
        // both in page coordinates.
        points: points.map(([x, y]) => {
            const p = item.imageToViewerElementCoordinates(new OpenSeadragon.Point(x, y));
            return {osd: [hostRect.left + p.x, hostRect.top + p.y],
                    fabric: [fabricRect.left + x * vpt[0] + vpt[4],
                             fabricRect.top + y * vpt[3] + vpt[5]]};
        }),
        polygon: (() => {
            const poly = m.canvas.getObjects().find(o => o.type === 'polygon');
            if (!poly) return null;
            const b = poly.getBoundingRect(true, true);
            return [b.left, b.top, b.width, b.height, poly.strokeWidth || 0];
        })(),
    };
}"""


@pytest.mark.playwright
class TestDeepZoomLayout(BasePlaywrightTest):

    def _settled(self, page, timeout=30_000):
        """Viewer open, region restored, and the view at rest."""
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                const m = c && c.annotationManager;
                if (!(m && m.deepZoom && m.deepZoom.viewer && m.deepZoom.contentSize
                      && m.image && m.getAnnotationCount() >= 1)) return false;
                const v = m.deepZoom.viewer.viewport;
                const b = v.getBounds(true);
                const key = [v.getZoom(true), b.x, b.y, m.canvas.getHeight(),
                             m.canvas.viewportTransform[5]].join('|');
                if (window.__dzKey === key) {
                    window.__dzStable = (window.__dzStable || 0) + 1;
                } else {
                    window.__dzKey = key;
                    window.__dzStable = 0;
                }
                return window.__dzStable >= 4;
            }""", arg=SCHEMA, timeout=timeout)
        page.evaluate("window.__dzKey = null; window.__dzStable = 0;")

    def _measure(self, page, points=()):
        return page.evaluate(MEASURE, [SCHEMA, [list(p) for p in points]])

    def _pixel(self, page, x, y):
        """The slide pixel on screen at page (x, y), with the shapes hidden."""
        from PIL import Image
        page.evaluate("""(schema) => {
            const c = document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`);
            c.querySelector('.canvas-container').style.visibility = 'hidden';
        }""", SCHEMA)
        try:
            shot = Image.open(BytesIO(page.screenshot())).convert("RGB")
        finally:
            page.evaluate("""(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                c.querySelector('.canvas-container').style.visibility = '';
            }""", SCHEMA)
        return shot.getpixel((int(round(x)), int(round(y))))

    def _assert_layers_agree(self, m):
        for key in ("osd", "fabric", "upper"):
            assert m[key] == pytest.approx(m["host"], abs=1.0), (key, m)
        assert m["osdBacking"] == pytest.approx(m["host"][2:], abs=1.0), m

    def _assert_points_agree(self, m):
        for p in m["points"]:
            assert p["fabric"] == pytest.approx(p["osd"], abs=1.0), p

    def _assert_whole_slide_visible(self, m):
        left, top, width, height = m["host"]
        x0, y0, x1, y1 = m["image"]
        assert x0 >= left - 1 and y0 >= top - 1, m
        assert x1 <= left + width + 1 and y1 <= top + height + 1, m
        # Fitted, not shrunk: the slide meets the box on one axis.
        assert (x1 - x0 >= width - 2) or (y1 - y0 >= height - 2), m

    def _assert_square_under_shape(self, page, m):
        """The square's centre, located through fabric's transform, is dark
        on screen, and a point just above the square is not."""
        cx, cy = m["points"][0]["fabric"]
        above_x, above_y = m["points"][1]["fabric"]
        dark = self._pixel(page, cx, cy)
        assert max(dark) < 80, (dark, m)
        light = self._pixel(page, above_x, above_y)
        assert min(light) > 200, (light, m)

    def _open(self, page, server, width=1280, height=900):
        page.set_viewport_size({"width": width, "height": height})
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self._settled(page)

    # Image points: the square's centre, a point 60 px above its top edge, and
    # the polygon's four vertices.
    POINTS = [((SQUARE[0] + SQUARE[2]) / 2, (SQUARE[1] + SQUARE[3]) / 2),
              ((SQUARE[0] + SQUARE[2]) / 2, SQUARE[1] - 60),
              (SQUARE[0], SQUARE[1]), (SQUARE[2], SQUARE[1]),
              (SQUARE[2], SQUARE[3]), (SQUARE[0], SQUARE[3])]

    @pytest.mark.parametrize("width", [1280, 390])
    def test_home_view_layers_and_shapes_line_up(self, page, layout_server, width):
        errors = []
        page.on("console", lambda msg: errors.append(msg.text)
                if msg.type == "error" else None)
        self._open(page, layout_server, width=width)
        m = self._measure(page, self.POINTS)

        self._assert_layers_agree(m)
        self._assert_whole_slide_visible(m)
        self._assert_points_agree(m)
        self._assert_square_under_shape(page, m)

        # The restored polygon is on the square, in image pixels.
        left, top, w, h, stroke = m["polygon"]
        tol = stroke + 1
        assert left == pytest.approx(SQUARE[0], abs=tol), m["polygon"]
        assert top == pytest.approx(SQUARE[1], abs=tol), m["polygon"]
        assert w == pytest.approx(SQUARE[2] - SQUARE[0], abs=2 * tol), m["polygon"]
        assert h == pytest.approx(SQUARE[3] - SQUARE[1], abs=2 * tol), m["polygon"]
        assert not [e for e in errors if "favicon" not in e], errors

    def test_shapes_stay_on_the_slide_after_zoom_and_pan(self, page, layout_server):
        self._open(page, layout_server)
        container = page.locator(
            f'.image-annotation-container[data-schema="{SCHEMA}"]')
        for _ in range(3):
            container.locator('.zoom-btn[data-action="zoom-in"]').click()
        self._settled(page)

        # Pan with a real drag. With no tool armed the overlay yields the
        # pointer to OpenSeadragon.
        page.evaluate("""(schema) => document.querySelector(
            `.image-annotation-container[data-schema="${schema}"]`)
            .annotationManager.setTool(null)""", SCHEMA)
        host = self._measure(page)["host"]
        cx, cy = host[0] + host[2] / 2, host[1] + host[3] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx - 120, cy - 120, steps=8)
        page.mouse.move(cx - 240, cy - 240, steps=8)
        page.mouse.up()
        self._settled(page)

        m = self._measure(page, self.POINTS)
        assert m["zoom"] > m["homeZoom"] * 1.5, m
        self._assert_layers_agree(m)
        self._assert_points_agree(m)
        sx, sy = m["points"][0]["fabric"]
        assert host[0] < sx < host[0] + host[2] and host[1] < sy < host[1] + host[3], \
            ("the pan did not bring the square into view", m)
        self._assert_square_under_shape(page, m)

        # A navigated view survives a resize; only the home view re-fits.
        page.set_viewport_size({"width": 1000, "height": 900})
        self._settled(page)
        after = self._measure(page, self.POINTS)
        self._assert_layers_agree(after)
        self._assert_points_agree(after)
        assert after["zoom"] > after["homeZoom"] * 1.3, after

    def test_home_view_refits_when_the_window_resizes(self, page, layout_server):
        self._open(page, layout_server)
        page.set_viewport_size({"width": 700, "height": 900})
        self._settled(page)
        m = self._measure(page, self.POINTS)
        self._assert_layers_agree(m)
        self._assert_whole_slide_visible(m)
        self._assert_points_agree(m)
        self._assert_square_under_shape(page, m)
