"""
Painting points (segment_3d) in a real browser: brush, repaint, erase, lasso,
hidden classes, and a painted scan surviving Next and Previous.

The arithmetic is covered by tests/jest/pc-paint.test.js and the viewer's data
path by tests/jest/pc-viewer-paint.test.js. What is left here needs WebGL: the
mouse reaching the points through the real camera, and the cloud's colour
buffer taking the label's colour.
"""

from __future__ import annotations

import json

import pytest

from tests.playwright.test_base import BasePlaywrightTest
from tests.playwright.test_spatial_annotation import (
    MEDIA, manager_eval, open_viewer, scene_items, wait_for_manager)

pytestmark = pytest.mark.playwright

SCHEMES = [{
    "annotation_type": "spatial_annotation",
    "name": "objects",
    "description": "Label every point",
    "source_field": "point_cloud",
    "tools": ["segment_3d"],
    "labels": [
        {"name": "car", "color": "#FF6B6B", "key_value": "1"},
        {"name": "road", "color": "#4ECDC4", "key_value": "2"},
    ],
    "brush_size": 12,
}]


@pytest.fixture
def paint_server(make_server):
    if not MEDIA.is_dir():
        pytest.skip("run examples/spatial/kitti-cuboids/generate_scene.py first")
    return make_server(
        SCHEMES,
        items=scene_items(),
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "point_cloud"},
        },
    )


def stored(page):
    return json.loads(page.input_value("#input-objects") or "[]")


def segments(page):
    return {s["label"]: s["indices"] for s in stored(page) if s["type"] == "segment_3d"}


def target(page):
    """Page coordinates of the cloud point nearest the canvas centre."""
    return page.evaluate("""() => {
        const m = document.querySelector('.pointcloud-annotation-container').annotationManager;
        const r = m.canvas.getBoundingClientRect();
        const p = m.parsed.positions;
        let best = null, bestD = Infinity;
        for (let i = 0; i < m.parsed.count; i++) {
            const v = new THREE.Vector3(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]).project(m.camera);
            if (v.z > 1) continue;
            const x = (v.x + 1) / 2 * r.width, y = (1 - v.y) / 2 * r.height;
            const d = Math.hypot(x - r.width / 2, y - r.height / 2);
            if (d < bestD) { bestD = d; best = [r.left + x, r.top + y]; }
        }
        return best;
    }""")


def drag(page, x0, y0, x1, y1, steps=6):
    page.mouse.move(x0, y0)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
    page.mouse.up()


def arm(page, label):
    page.click('.pointcloud-annotation-container [data-tool="segment_3d"]')
    page.click(f'.pointcloud-annotation-container .label-btn[data-label="{label}"]')


def colour_of(page, source_index):
    """The colour buffer's value for a source point, and its label's colour."""
    return page.evaluate(f"""() => {{
        const m = document.querySelector('.pointcloud-annotation-container').annotationManager;
        const slot = m.parsed.indices
            ? Array.from(m.parsed.indices).indexOf({source_index}) : {source_index};
        const a = m.cloud.geometry.getAttribute('color').array;
        return [a[slot * 3], a[slot * 3 + 1], a[slot * 3 + 2]].map((v) => v.toFixed(4));
    }}""")


def label_rgb(page, hex_colour):
    return page.evaluate(f"""() => {{
        const c = new THREE.Color().setRGB(
            ...['{hex_colour}'.slice(1, 3), '{hex_colour}'.slice(3, 5), '{hex_colour}'.slice(5, 7)]
                .map((h) => parseInt(h, 16) / 255), THREE.SRGBColorSpace);
        return [c.r, c.g, c.b].map((v) => v.toFixed(4));
    }}""")


class TestPainting(BasePlaywrightTest):
    def test_a_painting_scheme_loads_every_point(self, paint_server, page):
        open_viewer(self, page, paint_server)
        # No octree unless the scheme asks: unloaded nodes cannot be painted.
        assert manager_eval(page, "m.lodIndex") is None
        assert manager_eval(page, "m.parsed.count") == manager_eval(
            page, "m.parsed.header.original_count || m.parsed.header.count")

    def test_the_controls_follow_the_tool(self, paint_server, page):
        open_viewer(self, page, paint_server)
        assert not page.is_visible(".pc-paint")
        arm(page, "car")
        assert page.is_visible(".pc-paint")
        assert page.input_value(".pc-brush-slider") == "12"
        page.click("body")
        page.keyboard.press("=")
        assert page.input_value(".pc-brush-slider") == "14"
        assert page.inner_text(".pc-brush-value") == "14 px"

    def test_brush_repaint_and_erase(self, paint_server, page):
        open_viewer(self, page, paint_server)
        x, y = target(page)
        arm(page, "car")
        drag(page, x - 30, y, x + 30, y)
        car = segments(page)["car"]
        assert car and car == sorted(car) and all(isinstance(i, int) for i in car)
        assert colour_of(page, car[0]) == label_rgb(page, "#FF6B6B")

        # Repaint the middle with road: those points leave car.
        page.click('.pointcloud-annotation-container .label-btn[data-label="road"]')
        drag(page, x - 5, y, x + 5, y)
        after = segments(page)
        assert after["road"]
        assert not set(after["road"]) & set(after.get("car", []))
        assert set(after["road"]) | set(after.get("car", [])) >= set(car)

        # Shift+drag over everything unlabels it and restores the cloud colour.
        page.keyboard.down("Shift")
        drag(page, x - 50, y, x + 50, y)
        page.keyboard.up("Shift")
        assert segments(page) == {}
        assert colour_of(page, car[0]) != label_rgb(page, "#FF6B6B")

    def test_a_hidden_class_is_not_overwritten(self, paint_server, page):
        open_viewer(self, page, paint_server)
        x, y = target(page)
        arm(page, "car")
        drag(page, x - 20, y, x + 20, y)
        car = segments(page)["car"]

        page.click('.label-btn[data-label="car"] .label-visibility-toggle')
        assert manager_eval(page, "m.cloud.geometry.index !== null")
        page.click('.pointcloud-annotation-container .label-btn[data-label="road"]')
        drag(page, x - 40, y, x + 40, y)
        assert segments(page)["car"] == car

    def test_a_lasso_paints_what_it_encloses(self, paint_server, page):
        open_viewer(self, page, paint_server)
        x, y = target(page)
        arm(page, "road")
        page.click('[data-paint-mode="lasso"]')
        page.mouse.move(x - 25, y - 25)
        page.mouse.down()
        for px, py in [(x + 25, y - 25), (x + 25, y + 25), (x - 25, y + 25)]:
            page.mouse.move(px, py, steps=4)
        assert segments(page) == {}                  # nothing until release
        page.mouse.up()
        assert segments(page)["road"]

    def test_a_painted_scan_survives_next_and_previous(self, paint_server, page):
        open_viewer(self, page, paint_server)
        x, y = target(page)
        arm(page, "car")
        drag(page, x - 30, y, x + 30, y)
        car = segments(page)["car"]
        page.wait_for_timeout(1500)                  # the save debounce

        page.click("#next-btn")
        wait_for_manager(page)
        assert stored(page) == []
        page.click("#prev-btn")
        wait_for_manager(page)
        page.wait_for_function(
            "() => document.querySelector('.pointcloud-annotation-container')"
            ".annotationManager.hasCloud()", timeout=30000)
        assert segments(page)["car"] == car
        # Visual state: the restored cloud shows the points in the label colour.
        assert colour_of(page, car[0]) == label_rgb(page, "#FF6B6B")

    def test_alt_drag_orbits_without_painting(self, paint_server, page):
        open_viewer(self, page, paint_server)
        x, y = target(page)
        arm(page, "car")
        theta = manager_eval(page, "m._orbit.theta")
        page.keyboard.down("Alt")
        drag(page, x - 40, y, x + 40, y)
        page.keyboard.up("Alt")
        assert manager_eval(page, "m._orbit.theta") != theta
        assert segments(page) == {}

    def test_the_controls_fit_a_phone_width(self, paint_server, page):
        page.set_viewport_size({"width": 360, "height": 740})
        open_viewer(self, page, paint_server)
        arm(page, "car")
        widths = page.evaluate("""() => ({
            page: document.documentElement.scrollWidth,
            right: Math.max(...Array.from(document.querySelectorAll('.pc-paint > *'))
                .map((e) => e.getBoundingClientRect().right)),
        })""")
        assert widths["page"] <= 360, widths
        assert widths["right"] <= 360, widths
