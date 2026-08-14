"""
The 3D annotation surface, in a real browser with a real WebGL context.

Everything below needs a GPU context that jsdom does not have, which is why the
pure arithmetic lives in `pc-wire.js`, `pc-calibration.js` and the manager's
static helpers and is tested by Jest instead. What is left here is exactly the
part that cannot be faked: does three.js build a renderer, does the converted
cloud reach the scene graph, does dragging on the canvas produce a box in
metres, and does the box land on the object in the camera panel.

Chromium runs headless with SwiftShader (`--disable-gpu` in the shared
conftest), so WebGL is genuinely present rather than stubbed.

**Assertions read the scene graph and the stored annotation, never a
screenshot.** The three.js colour-management bug in Wave 8.2 rendered every box
in the wrong colour and was invisible in a screenshot; `getHexString()` caught
it immediately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

EXAMPLE = Path("examples/spatial/kitti-cuboids").resolve()
MEDIA = EXAMPLE / "media"

SCHEMES = [{
    "annotation_type": "spatial_annotation",
    "name": "objects",
    "description": "Box the vehicles",
    "source_field": "point_cloud",
    "calibration_field": "calibration",
    "tools": ["cuboid_3d", "point_3d"],
    "labels": [
        {"name": "car", "color": "#FF6B6B", "key_value": "1"},
        {"name": "truck", "color": "#4ECDC4", "key_value": "2"},
    ],
    "color_mode": "height",
    "point_size": 2.0,
}]


def scene_items():
    """The example's own scenes, so the cloud and the image really match."""
    return [
        {"id": "scene_0001",
         "point_cloud": "clouds/scene_0001.bin",
         "calibration": {"file": "calib/scene_0001.txt",
                         "images": {"P2": "images/scene_0001.png"}}},
        {"id": "scene_0002",
         "point_cloud": "clouds/scene_0002.bin",
         "calibration": {"file": "calib/scene_0002.txt",
                         "images": {"P2": "images/scene_0002.png"}}},
    ]


@pytest.fixture
def spatial_server(make_server):
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


def wait_for_manager(page):
    """Wait until the schema's inline bootstrap has constructed the manager."""
    page.wait_for_selector(".pointcloud-annotation-container", timeout=30000)
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.pointcloud-annotation-container');
            return c && c.annotationManager;
        }""", timeout=30000)


def open_viewer(test, page, server):
    """Log in, load /annotate, and wait for the cloud to be in the scene."""
    test.register_and_login(page, server)
    page.goto(f"{server.base_url}/annotate")
    wait_for_manager(page)
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.pointcloud-annotation-container');
            return c.annotationManager.cloud;
        }""", timeout=30000)


def manager_eval(page, expression):
    return page.evaluate(
        "() => { const m = document.querySelector("
        "'.pointcloud-annotation-container').annotationManager; return ("
        + expression + "); }")


class TestTheViewerActuallyRuns(BasePlaywrightTest):
    def test_three_js_builds_a_real_renderer(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        assert manager_eval(page, "!!m.renderer && !!m.renderer.getContext()")
        # A software rasteriser still reports a real context; a stub would not.
        assert manager_eval(
            page, "m.renderer.getContext().getParameter("
                  "m.renderer.getContext().VERSION)").lower().startswith("webgl")

    def test_the_converted_cloud_reaches_the_scene_graph(self, spatial_server,
                                                         page):
        open_viewer(self, page, spatial_server)
        count = manager_eval(
            page, "m.cloud.geometry.getAttribute('position').count")
        assert count > 5000, "the whole scan should have been parsed"
        assert manager_eval(page, "m.scene.children.includes(m.cloud)")

    def test_the_status_line_describes_what_is_shown(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        status = page.text_content(".pc-status")
        assert "point" in status.lower()

    def test_the_ground_is_estimated_from_the_cloud_not_assumed_zero(
            self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        ground = manager_eval(page, "m.groundZ")
        # The synthetic sensor sits 1.73 m above the road, as a real one does.
        # Assuming z = 0 would float every box above the scene.
        assert -2.2 < ground < -1.2, f"ground estimated at {ground}"


class TestDrawingABox(BasePlaywrightTest):
    def arm_and_drag(self, page, x0, y0, x1, y1):
        """Pick the box tool and a class, then drag across the viewport."""
        page.click('.pointcloud-annotation-container [data-tool="cuboid_3d"]')
        page.click('.pointcloud-annotation-container .label-btn[data-label="car"]')
        box = page.query_selector(".pc-canvas").bounding_box()
        page.mouse.move(box["x"] + x0, box["y"] + y0)
        page.mouse.down()
        # Intermediate moves: a single jump can be coalesced away, and the
        # preview path only runs on mousemove.
        for i in range(1, 5):
            page.mouse.move(box["x"] + x0 + (x1 - x0) * i / 4,
                            box["y"] + y0 + (y1 - y0) * i / 4)
        page.mouse.up()

    def test_a_drag_creates_a_box_in_metres(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)

        stored = json.loads(page.input_value("#input-objects"))
        assert len(stored) == 1
        box = stored[0]
        assert box["type"] == "cuboid_3d"
        assert box["label"] == "car"
        assert box["color"] == "#FF6B6B"

        centre = box["coordinates"]["center"]
        size = box["coordinates"]["size"]
        assert all(isinstance(v, (int, float)) for v in centre + size)
        # Metres in the sensor frame, not normalized fractions. A [0, 1] value
        # here would mean the 2D contract had leaked into the 3D one.
        assert all(s > 0.1 for s in size), size
        assert max(abs(v) for v in centre) > 1.0, centre
        assert len(box["coordinates"]["rotation"]) == 4

    def test_the_box_rests_on_the_ground_it_was_drawn_on(self, spatial_server,
                                                         page):
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)

        ground = manager_eval(page, "m.groundZ")
        box = json.loads(page.input_value("#input-objects"))[0]["coordinates"]
        bottom = box["center"][2] - box["size"][2] / 2
        assert abs(bottom - ground) < 0.02, (
            f"box base at {bottom}, ground at {ground} — a floating box is the "
            f"symptom of drawing on the z = 0 plane instead of the road")

    def test_a_stray_click_creates_nothing(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.click('.pointcloud-annotation-container [data-tool="cuboid_3d"]')
        page.click('.pointcloud-annotation-container .label-btn[data-label="car"]')
        box = page.query_selector(".pc-canvas").bounding_box()
        page.mouse.click(box["x"] + 400, box["y"] + 320)
        assert page.input_value("#input-objects") in ("", "[]")

    def test_the_wireframe_matches_its_label_colour(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)
        # The Wave 8.2 bug: THREE.Color treats float args as LINEAR sRGB since
        # r155, so #ff6b6b rendered as #ffadad -- close enough to look
        # deliberate. A screenshot did not reveal it; this does.
        assert manager_eval(page, "m.meshes[0].material.color.getHexString()") \
            == "ff6b6b"

    def test_rotating_the_selection_changes_yaw_not_size(self, spatial_server,
                                                         page):
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)
        before = json.loads(page.input_value("#input-objects"))[0]["coordinates"]

        page.keyboard.press("q")
        after = json.loads(page.input_value("#input-objects"))[0]["coordinates"]

        assert after["rotation"] != before["rotation"]
        assert after["size"] == before["size"]
        assert after["center"] == before["center"]

    def test_delete_removes_the_selection(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)
        assert len(json.loads(page.input_value("#input-objects"))) == 1

        page.keyboard.press("Delete")
        assert json.loads(page.input_value("#input-objects")) == []

    def test_shortcuts_do_not_fire_inside_a_text_field(self, spatial_server,
                                                       page):
        # The image canvas shipped this bug: typing "bad boxes here" in a
        # free-text question beside the canvas produced "badboxesee".
        open_viewer(self, page, spatial_server)
        self.arm_and_drag(page, 380, 300, 500, 380)
        before = page.input_value("#input-objects")

        page.evaluate("""() => {
            const el = document.createElement('textarea');
            el.id = 'probe';
            document.querySelector('.pointcloud-annotation-container')
                .appendChild(el);
            el.focus();
        }""")
        page.keyboard.type("q e delete")
        assert page.input_value("#input-objects") == before
        assert page.input_value("#probe") == "q e delete"


class TestCameraVerificationPanels(BasePlaywrightTest):
    def test_a_panel_appears_with_the_camera_image(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.wait_for_selector(".pc-camera-image", timeout=15000)
        assert page.evaluate(
            "() => { const i = document.querySelector('.pc-camera-image');"
            " return i.complete && i.naturalWidth; }") == 1242

    def test_a_box_is_drawn_onto_the_photograph(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.wait_for_selector(".pc-camera-image", timeout=15000)

        # Place a box exactly where the example's car is, in metres, through
        # the sanctioned programmatic entry point -- so this test is about the
        # projection rather than about where a drag happens to land.
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.addAnnotation({type: 'cuboid_3d', label: 'car', color: '#FF6B6B',
                coordinates: {center: [14.0, 1.2, -0.98],
                              size: [4.3, 1.8, 1.5],
                              rotation: [0, 0, 0, 1]}});
        }""")

        painted = page.evaluate("""() => {
            const c = document.querySelector('.pc-camera-overlay');
            const ctx = c.getContext('2d');
            const d = ctx.getImageData(0, 0, c.width, c.height).data;
            let lit = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) lit++;
            return {lit: lit, w: c.width, h: c.height};
        }""")
        assert painted["w"] > 0 and painted["h"] > 0
        assert painted["lit"] > 50, "no wireframe was drawn on the camera image"

    def test_hiding_a_class_clears_it_from_the_panel_too(self, spatial_server,
                                                         page):
        open_viewer(self, page, spatial_server)
        page.wait_for_selector(".pc-camera-image", timeout=15000)
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.addAnnotation({type: 'cuboid_3d', label: 'car', color: '#FF6B6B',
                coordinates: {center: [14.0, 1.2, -0.98],
                              size: [4.3, 1.8, 1.5], rotation: [0, 0, 0, 1]}});
        }""")

        def lit_pixels():
            return page.evaluate("""() => {
                const c = document.querySelector('.pc-camera-overlay');
                const d = c.getContext('2d').getImageData(
                    0, 0, c.width, c.height).data;
                let n = 0;
                for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
                return n;
            }""")

        assert lit_pixels() > 50
        # The verification panel contradicting the viewport would be worse than
        # not having it.
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.applyLabelVisibility(new Set(['car']));
        }""")
        assert lit_pixels() == 0

    def test_a_box_behind_the_camera_is_not_drawn(self, spatial_server, page):
        # Without near-plane culling this projects to a plausible wireframe
        # mirrored through the principal point.
        open_viewer(self, page, spatial_server)
        page.wait_for_selector(".pc-camera-image", timeout=15000)
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.addAnnotation({type: 'cuboid_3d', label: 'car', color: '#FF6B6B',
                coordinates: {center: [-20.0, 0.0, -1.0],
                              size: [4.3, 1.8, 1.5], rotation: [0, 0, 0, 1]}});
        }""")
        lit = page.evaluate("""() => {
            const c = document.querySelector('.pc-camera-overlay');
            const d = c.getContext('2d').getImageData(
                0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
            return n;
        }""")
        assert lit == 0


class TestPersistence(BasePlaywrightTest):
    def test_a_box_survives_navigating_away_and_back(self, spatial_server,
                                                     page):
        """
        Next then Previous, never a refresh: browsers cache form state across
        refresh and produce false positives (invariant 2).
        """
        open_viewer(self, page, spatial_server)
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.addAnnotation({type: 'cuboid_3d', label: 'truck',
                color: '#4ECDC4',
                coordinates: {center: [23.0, -4.6, -0.38],
                              size: [7.0, 2.5, 2.7], rotation: [0, 0, 0, 1]}});
        }""")
        page.wait_for_timeout(1500)       # the save debounce

        page.click("#next-btn")
        page.wait_for_timeout(1500)
        page.click("#prev-btn")
        wait_for_manager(page)

        restored = json.loads(page.input_value("#input-objects") or "[]")
        assert len(restored) == 1, "the box did not come back"
        assert restored[0]["label"] == "truck"
        assert restored[0]["coordinates"]["size"] == [7.0, 2.5, 2.7]

        # Visual state, not just the hidden input: the mesh has to be rebuilt.
        assert manager_eval(page, "m.meshes.length") == 1
        assert manager_eval(page, "m.meshes[0].material.color.getHexString()") \
            == "4ecdc4"

    def test_switching_items_does_not_leak_annotations(self, spatial_server,
                                                       page):
        # Three separate cross-instance corruption bugs came out of the image
        # manager's clearAnnotations. Nothing here is a scene-graph child that
        # a generic clear would catch, so this is checked rather than assumed.
        open_viewer(self, page, spatial_server)
        page.evaluate("""() => {
            const m = document.querySelector(
                '.pointcloud-annotation-container').annotationManager;
            m.addAnnotation({type: 'point_3d', label: 'car', color: '#FF6B6B',
                             coordinates: [5, 1, -1]});
        }""")
        page.wait_for_timeout(1500)

        page.click("#next-btn")
        wait_for_manager(page)

        assert json.loads(page.input_value("#input-objects") or "[]") == []
        assert manager_eval(page, "m.selectedIndex") == -1
