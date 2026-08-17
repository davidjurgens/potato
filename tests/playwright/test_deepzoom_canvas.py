"""
Annotating a tiled image: OpenSeadragon under, fabric over.

This is the only place the feature can actually be checked. The transform that
keeps annotations glued to the image is computed from OpenSeadragon's live
viewport, so it does not exist outside a browser, and the failure it guards
against — shapes that look right at the zoom level they were drawn at and drift
at every other — is invisible to anything that inspects stored coordinates
alone.

So the load-bearing test here is `test_a_box_drawn_zoomed_in_stores_the_same_
coordinates`: draw at one magnification, verify at another. Every plausible
transform bug fails it and nothing else catches them.
"""

import json
import os

import pytest
import yaml

from tests.playwright.test_base import BasePlaywrightTest

SCHEMA = "regions"


@pytest.fixture(scope="module")
def deepzoom_server():
    """A project whose image is served through the tile routes."""
    pytest.importorskip("PIL", reason="deep zoom needs Pillow to build tiles")

    from PIL import Image, ImageDraw

    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("playwright_deepzoom")
    media = os.path.join(test_dir, "media", "scans")
    os.makedirs(media, exist_ok=True)

    # Four quadrants, so a coordinate error of more than a quarter of the image
    # is visible in the stored values rather than only in a screenshot.
    image = Image.new("RGB", (1600, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 800, 600], fill="#c0392b")
    draw.rectangle([800, 0, 1600, 600], fill="#27ae60")
    draw.rectangle([0, 600, 800, 1200], fill="#2980b9")
    draw.rectangle([800, 600, 1600, 1200], fill="#f39c12")
    image.save(os.path.join(media, "slide.png"))

    items = [{"id": f"scan_{i}", "image": "scans/slide.png"} for i in range(3)]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "Deep zoom",
        "task_dir": test_dir,
        "media_directory": os.path.join(test_dir, "media"),
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "output_annotation_format": "json",
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Mark the regions",
            "source_field": "image",
            "viewer": "deepzoom",
            "tools": ["bbox", "brush", "eraser"],
            "labels": [{"name": "tissue", "color": "#FF0000"},
                       {"name": "background", "color": "#00FF00"}],
        }],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    srv = FlaskTestServer(port=find_free_port(), debug=False,
                          config_file=config_path)
    if not srv.start():
        raise RuntimeError("Failed to start the deep-zoom Playwright server")
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestDeepZoomCanvas(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.viewer_ready(page)
        return page

    def viewer_ready(self, page, timeout=30_000):
        """
        Wait until OpenSeadragon has opened AND its opening animation settled.

        The second half is not fussiness. `goHome` is an animation, so for the
        first few hundred milliseconds the image occupies almost no screen
        area; a drag computed from that rect is a few pixels long, and the
        manager's twitch-guard correctly discards it. The symptom is a test
        that draws nothing and reports no error.
        """
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`);
                const m = c && c.annotationManager;
                if (!(m && m.deepZoom && m.deepZoom.viewer
                      && m.deepZoom.contentSize && m.image)) return false;
                // "Settled" means the transform has stopped changing, not that
                // it has passed some threshold: a magnitude test can be
                // satisfied part-way through the spring, which is how this
                // check passed while the image was still moving.
                const zoom = m.canvas.getZoom();
                if (!(zoom > 0)) return false;
                const key = `${zoom}|${m.canvas.viewportTransform[4]}`;
                if (window.__dzLast === key) {
                    window.__dzStable = (window.__dzStable || 0) + 1;
                } else {
                    window.__dzLast = key;
                    window.__dzStable = 0;
                }
                return window.__dzStable >= 3;
            }""",
            arg=SCHEMA, timeout=timeout)
        # The polls above are ~50 ms apart, so three identical reads means the
        # spring has been at rest for ~150 ms.
        page.evaluate("window.__dzLast = null; window.__dzStable = 0;")

    # -- the viewer itself ---------------------------------------------------

    def test_the_library_and_the_host_are_both_on_the_page(self, page, deepzoom_server):
        self._open(page, deepzoom_server)
        assert page.locator(".deepzoom-host").count() == 1
        assert page.evaluate("typeof OpenSeadragon") == "function"

    def test_the_placeholder_carries_the_sources_natural_size(self, page,
                                                              deepzoom_server):
        """
        Every coordinate calculation reads this. If it were the *displayed*
        size, normalization would divide by the wrong number and every stored
        shape would be off by the zoom factor.
        """
        self._open(page, deepzoom_server)
        size = page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                return {w: m.image.width, h: m.image.height,
                        sx: m.image.scaleX, left: m.image.left, top: m.image.top};
            }""", arg=SCHEMA)
        assert (size["w"], size["h"]) == (1600, 1200)
        assert size["sx"] == 1
        assert (size["left"], size["top"]) == (0, 0)

    def test_the_fabric_transform_tracks_openseadragon(self, page, deepzoom_server):
        """
        The sync, checked against OpenSeadragon's own answer rather than
        against a formula — a formula here would be a reimplementation of the
        library's arithmetic and could agree with itself while being wrong.
        """
        self._open(page, deepzoom_server)
        result = page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                const item = m.deepZoom.viewer.world.getItemAt(0);
                const origin = item.imageToViewerElementCoordinates(
                    new OpenSeadragon.Point(0, 0));
                const unit = item.imageToViewerElementCoordinates(
                    new OpenSeadragon.Point(1, 0));
                return {vpt: m.canvas.viewportTransform,
                        scale: unit.x - origin.x, x: origin.x, y: origin.y};
            }""", arg=SCHEMA)
        vpt = result["vpt"]
        assert vpt[0] == pytest.approx(result["scale"], rel=1e-6)
        assert vpt[4] == pytest.approx(result["x"], abs=0.5)
        assert vpt[5] == pytest.approx(result["y"], abs=0.5)

    def test_tiles_are_actually_fetched(self, page, deepzoom_server):
        """
        The descriptor loading is not enough: a viewer can open a valid
        descriptor and then request tiles that 404, which looks like a blank
        image and reports no error.
        """
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        self._open(page, deepzoom_server)
        page.wait_for_timeout(1500)
        tiles = [u for u in requests if "_files/" in u]
        assert tiles, f"no tile requests were made; saw {requests[-5:]}"

    # -- drawing -------------------------------------------------------------

    def test_a_box_stores_normalized_image_coordinates(self, page, deepzoom_server):
        self._open(page, deepzoom_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.1, 0.1, 0.4, 0.4, label="tissue")
        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 1
        box = data[0]["coordinates"]
        assert box["x"] == pytest.approx(0.1, abs=0.03)
        assert box["y"] == pytest.approx(0.1, abs=0.03)
        assert box["width"] == pytest.approx(0.3, abs=0.03)
        assert box["height"] == pytest.approx(0.3, abs=0.03)

    def test_a_box_drawn_zoomed_in_stores_the_same_coordinates(self, page,
                                                               deepzoom_server):
        """
        The load-bearing test. Zoom in, draw over a known image fraction, and
        the stored value must be that fraction — not the fraction of the
        *viewport*, which is what every plausible transform bug produces.
        """
        self._open(page, deepzoom_server)

        page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                m.deepZoom.zoomBy(3);
                m.deepZoom.viewer.viewport.applyConstraints(true);
            }""", arg=SCHEMA)
        page.wait_for_timeout(1200)   # let the spring settle
        page.evaluate(
            """(schema) => document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`)
                .annotationManager.deepZoom.syncTransform()""", arg=SCHEMA)

        zoom = page.evaluate(
            """(schema) => document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`)
                .annotationManager.canvas.getZoom()""", arg=SCHEMA)
        assert zoom > 0.5, "the viewport did not actually zoom in"

        self.draw_bbox_on_image(page, SCHEMA, 0.45, 0.45, 0.55, 0.55,
                                label="tissue")
        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 1
        box = data[0]["coordinates"]
        # A generous tolerance: the point is that the value is ~0.45 and not
        # some viewport-relative number, which any transform bug makes it.
        assert box["x"] == pytest.approx(0.45, abs=0.06), box
        assert box["y"] == pytest.approx(0.45, abs=0.06), box
        assert box["width"] == pytest.approx(0.1, abs=0.05), box

    def test_a_mask_can_be_painted_on_a_tiled_image(self, page, deepzoom_server):
        """
        V7 documents this as unsupported ("Mask annotations are currently not
        supported for tiled images"). It works here because the mask buffer is
        indexed in image pixels, which the placeholder makes true in this mode
        as well.
        """
        self._open(page, deepzoom_server)
        self.paint_stroke_on_image(
            page, SCHEMA,
            [(0.3, 0.3), (0.4, 0.35), (0.5, 0.4)],
            label="tissue", tool="brush")
        painted = page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                return Object.keys(m.masks).length;
            }""", arg=SCHEMA)
        assert painted >= 1, "the brush painted nothing on the tiled image"

    def test_the_mask_is_indexed_at_the_sources_full_resolution(self, page,
                                                               deepzoom_server):
        """
        Not at the displayed size. A mask sized to the viewport would export at
        the wrong resolution and could never be compared with one drawn at a
        different zoom.
        """
        self._open(page, deepzoom_server)
        self.paint_stroke_on_image(page, SCHEMA, [(0.3, 0.3), (0.35, 0.35)],
                                   label="tissue", tool="brush")
        dims = page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                return {w: m.maskImgWidth, h: m.maskImgHeight};
            }""", arg=SCHEMA)
        assert (dims["w"], dims["h"]) == (1600, 1200)

    # -- persistence ---------------------------------------------------------

    def test_a_box_survives_navigating_away_and_back(self, page, deepzoom_server):
        """
        Never a refresh: browsers restore form state across one, so a
        refresh-based test passes even when the server stored nothing.
        """
        self._open(page, deepzoom_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.2, 0.2, 0.5, 0.5, label="tissue")
        self.wait_for_debounce(page)

        self.click_next(page)
        self.viewer_ready(page)
        self.click_prev(page)
        self.viewer_ready(page)

        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 1, f"the box did not come back: {data}"
        assert data[0]["coordinates"]["x"] == pytest.approx(0.2, abs=0.04)

    # -- the two libraries sharing one pointer -------------------------------

    def test_the_overlay_yields_the_pointer_when_no_tool_is_armed(self, page,
                                                                  deepzoom_server):
        """
        Otherwise OpenSeadragon never sees a drag and the image cannot be
        panned at all — which reads as a frozen viewer, not as a mode.
        """
        self._open(page, deepzoom_server)
        page.evaluate(
            """(schema) => document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`)
                .annotationManager.setTool(null)""", arg=SCHEMA)
        assert page.evaluate(
            """(schema) => document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`)
                .annotationManager.canvas.wrapperEl.style.pointerEvents""",
            arg=SCHEMA) == "none"

    def test_the_overlay_takes_the_pointer_for_a_drawing_tool(self, page,
                                                              deepzoom_server):
        self._open(page, deepzoom_server)
        self.select_tool(page, SCHEMA, "bbox")
        assert page.evaluate(
            """(schema) => document.querySelector(
                `.image-annotation-container[data-schema="${schema}"]`)
                .annotationManager.canvas.wrapperEl.style.pointerEvents""",
            arg=SCHEMA) == "auto"
