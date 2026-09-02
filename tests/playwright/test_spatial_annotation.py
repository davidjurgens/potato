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
        # `hasCloud()`, not `.cloud`: under level-of-detail loading the points
        # live in one THREE.Points per octree node and `.cloud` stays null.
        # Gating on the field rather than the fact is what made every test in
        # this file time out the day LOD was switched on.
        """() => {
            const c = document.querySelector('.pointcloud-annotation-container');
            return c.annotationManager.hasCloud();
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
            page,
            "m.cloudObjects().reduce((n, o) => "
            "n + o.geometry.getAttribute('position').count, 0)")
        assert count > 5000, "the whole scan should have been parsed"
        assert manager_eval(
            page, "m.cloudObjects().every(o => m.scene.children.includes(o))")

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


# ---------------------------------------------------------------------------
# Level of detail
# ---------------------------------------------------------------------------

def _schemes_with(**overrides):
    scheme = dict(SCHEMES[0])
    scheme.update(overrides)
    return [scheme]


@pytest.fixture
def single_buffer_server(make_server):
    """A viewer with `lod: false`, so the one-buffer path stays exercised."""
    if not MEDIA.is_dir():
        pytest.skip("run examples/spatial/kitti-cuboids/generate_scene.py first")
    return make_server(
        _schemes_with(lod=False),
        items=scene_items(),
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "point_cloud"},
        },
    )


class TestLevelOfDetail(BasePlaywrightTest):
    """
    The octree path, driven end to end.

    These assert against the scene graph and the network, never a screenshot:
    a half-loaded octree and a fully loaded one look similar in a still frame
    and differ entirely in what the annotator can actually see.
    """

    def test_the_cloud_arrives_as_several_nodes(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        assert manager_eval(page, "!!m.lodIndex"), "LOD should be the default"
        assert manager_eval(page, "m.lodNodes.size") > 1, (
            "the example scene should subdivide into more than a root node")
        assert manager_eval(page, "m.cloudObjects().length") == manager_eval(
            page, "m.lodNodes.size")

    def test_the_manifest_describes_the_whole_scan(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        total = manager_eval(page, "m.lodIndex.totalCount")
        loaded = manager_eval(page, "m.loadedPointCount()")
        assert total > 0
        assert loaded > 0
        assert loaded <= total

    def test_the_status_line_reports_loaded_not_selected(self, spatial_server,
                                                         page):
        # A node that has been requested but has not arrived is not on screen.
        # Counting it would tell the annotator they are looking at detail they
        # are not.
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(500)
        status = page.text_content(".pc-status")
        assert "point" in status.lower()
        loaded = manager_eval(page, "m.loadedPointCount()")
        assert f"{loaded:,}" in status

    def test_nodes_carry_source_indices(self, spatial_server, page):
        # Without this a segment_3d annotation means "the i-th point currently
        # loaded", which changes meaning as the camera moves.
        open_viewer(self, page, spatial_server)
        assert manager_eval(
            page, "Array.from(m.lodParsed.values()).every(p => !!p.indices)")
        assert manager_eval(
            page,
            "Math.max(...Array.from(m.lodParsed.values())"
            ".map(p => Math.max(...Array.from(p.indices))))") > 0

    def test_lowering_the_detail_threshold_fetches_more_nodes(
            self, spatial_server, page):
        """
        The traversal-to-network loop, driven deterministically.

        Zooming and asserting "more nodes appeared" would be a vacuous test on
        the bundled scene, which is small enough that every node clears the
        threshold at the starting camera. Moving the threshold instead proves
        the same mechanism — select, fetch, add to the scene — on any scene.
        """
        open_viewer(self, page, spatial_server)

        # Threshold so high nothing can clear it, and the camera pulled far
        # enough back that it is not inside any node's bounding sphere — a node
        # containing the camera loads regardless of the threshold, deliberately,
        # because that is the case where you have zoomed right into it.
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m.lodNodes.forEach((_o, k) => m._disposeNode(k));
                m._orbit.radius = 5000;
                m._applyCamera();
                m.config.minScreenSize = 1e9;
                m._updateLod();
            }""")
        page.wait_for_timeout(400)
        coarse = manager_eval(page, "m.lodNodes.size")
        assert coarse == 1, "only the root should clear an impossible threshold"

        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m.config.minScreenSize = 1;
                m._updateLod();
            }""")
        page.wait_for_timeout(1500)

        fine = manager_eval(page, "m.lodNodes.size")
        assert fine > coarse, "lowering the threshold must fetch more nodes"
        assert manager_eval(page, "m.loadedPointCount()") > 0

    def test_evicted_nodes_release_their_geometry(self, spatial_server, page):
        # A viewer that only ever adds buffers runs a scene out of GPU memory
        # on a large scan, and the symptom is a browser tab dying rather than
        # anything that points at the cause.
        open_viewer(self, page, spatial_server)
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m.config.maxLoadedNodes = 1;
                m.config.minScreenSize = 1e9;
                m._updateLod();
            }""")
        page.wait_for_timeout(500)
        assert manager_eval(page, "m.lodNodes.size") <= 2
        assert manager_eval(page, "m.lodParsed.size") == manager_eval(
            page, "m.lodNodes.size"), (
            "parsed buffers must be released with their scene objects")

    def test_a_box_fits_against_every_loaded_buffer(self, spatial_server, page):
        # The regression this guards: fitting to the coarse root sample alone
        # gives a shorter box the closer you zoom in, which reads as the fit
        # being unreliable rather than as a bug.
        open_viewer(self, page, spatial_server)
        chunks = manager_eval(page, "m._loadedPositions().length")
        assert chunks > 1

    def test_drawing_still_works_with_the_single_buffer_path(
            self, single_buffer_server, page):
        """`lod: false` must keep working — it is the fallback we document."""
        open_viewer(self, page, single_buffer_server)
        assert manager_eval(page, "!m.lodIndex")
        assert manager_eval(page, "!!m.cloud")
        assert manager_eval(page, "m.cloudObjects().length") == 1
        assert manager_eval(page, "m.loadedPointCount()") > 1000


class TestSlabViews(BasePlaywrightTest):
    """
    The orthographic slab panels.

    A perspective view compresses the extent along the view axis, so a box
    placed by eye is short in depth and the error is invisible from the camera
    that drew it. These check the panels exist, follow the selection, and edit
    the annotation the drag was aimed at.
    """

    def _draw_a_box(self, page):
        page.keyboard.press("c")
        canvas = page.locator(".pc-canvas")
        box = canvas.bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.42,
                        box["y"] + box["height"] * 0.62)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.58,
                        box["y"] + box["height"] * 0.74, steps=8)
        page.mouse.up()
        page.wait_for_timeout(250)

    def test_three_panels_are_built(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        assert page.locator(".pc-slab").count() == 3
        planes = page.eval_on_selector_all(
            ".pc-slab", "els => els.map(e => e.dataset.plane)")
        assert planes == ["top", "front", "side"]

    def test_each_canvas_is_actually_painted(self, spatial_server, page):
        # A blank canvas and a correctly drawn one are the same size and the
        # same colour to every selector-based check, so this reads pixels.
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(600)
        painted = page.evaluate(
            """() => {
                const c = document.querySelector('.pc-slab-canvas');
                const ctx = c.getContext('2d');
                const data = ctx.getImageData(0, 0, c.width, c.height).data;
                const first = [data[0], data[1], data[2]];
                for (let i = 4; i < data.length; i += 4) {
                    if (data[i] !== first[0] || data[i + 1] !== first[1]
                        || data[i + 2] !== first[2]) return true;
                }
                return false;
            }""")
        assert painted, "the top slab should contain points, not just its fill"

    def test_the_caption_reports_the_slab_thickness(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(400)
        caption = page.text_content(".pc-slab figcaption")
        assert "slab" in caption
        assert "m" in caption

    def test_the_wheel_changes_the_thickness(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        before = manager_eval(page, "m.config.slabThickness")
        canvas = page.locator(".pc-slab-canvas").first
        # The panels sit below a 500px viewport, so without this the pointer
        # lands outside the window and the wheel goes nowhere -- a test that
        # fails for a reason that has nothing to do with the feature.
        canvas.scroll_into_view_if_needed()
        box = canvas.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2)
        page.mouse.wheel(0, 240)
        page.wait_for_timeout(200)
        assert manager_eval(page, "m.config.slabThickness") > before

    def test_the_slab_follows_the_selection(self, spatial_server, page):
        # Centring anywhere but the selected box puts its own returns outside
        # the slab, which is the one thing that must not happen while editing.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        assert manager_eval(page, "m.selectedIndex") >= 0

        focus = page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                return m._slabView('top').center;
            }""")
        centre = manager_eval(page, "m.annotations[m.selectedIndex]"
                                    ".coordinates.center")
        assert focus == pytest.approx(centre, abs=1e-6)

    def test_dragging_an_edge_resizes_the_stored_annotation(self, spatial_server,
                                                            page):
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        before = manager_eval(
            page, "m.annotations[m.selectedIndex].coordinates.size.slice()")

        # Grab the box's left edge in the top panel and pull it outward. The
        # panel has to be on screen first: bounding rects are viewport-relative
        # and a pointer aimed below the fold hits nothing.
        page.locator('.pc-slab[data-plane="top"] .pc-slab-canvas'
                     ).scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        moved = page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                const view = m._slabView('top');
                const sel = m.annotations[m.selectedIndex];
                const env = window.PointCloudMPR.boxEnvelope(
                    view, sel.coordinates);
                const p = window.PointCloudMPR.worldToPanel(
                    view, [env.uMin, sel.coordinates.center[1],
                           sel.coordinates.center[2]]);
                const canvas = document.querySelector(
                    '.pc-slab[data-plane="top"] .pc-slab-canvas');
                const rect = canvas.getBoundingClientRect();
                return {x: rect.left + p.x, y: rect.top + p.y};
            }""")

        page.mouse.move(moved["x"], moved["y"])
        page.mouse.down()
        page.mouse.move(moved["x"] - 25, moved["y"], steps=6)
        page.mouse.up()
        page.wait_for_timeout(250)

        after = manager_eval(
            page, "m.annotations[m.selectedIndex].coordinates.size.slice()")
        assert after[0] > before[0] + 0.1, "dragging the edge should widen it"
        # Height is not in this plane and must be untouched.
        assert after[2] == pytest.approx(before[2], abs=1e-6)

    def test_the_edit_reaches_the_hidden_input(self, spatial_server, page):
        # The panel could redraw convincingly while writing nothing: every
        # subsystem downstream reads the input, not the canvas.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                const view = m._slabView('top');
                const sel = m.annotations[m.selectedIndex];
                const world = sel.coordinates.center.slice();
                world[0] += 3;
                sel.coordinates = window.PointCloudMPR.applyDrag(
                    view, sel.coordinates, 'move', world, [0, 0, 0]);
                m._updateAnnotationData();
            }""")
        stored = json.loads(page.input_value("input.annotation-data-input"))
        assert stored, "the slab edit must reach the hidden input"

    def test_an_undo_steps_back_past_the_whole_drag(self, spatial_server, page):
        # One history entry per drag, not per mousemove: otherwise undo walks
        # back through sixty intermediate sizes.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        before = manager_eval(page, "m.history.length")
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m._slabDrag = {plane: 'top', handle: 'move', offset: [0, 0, 0]};
                const canvas = document.querySelector('.pc-slab-canvas');
                canvas.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
            }""")
        after = manager_eval(page, "m.history.length")
        assert after == before + 1

    def test_switching_items_clears_the_in_flight_drag(self, spatial_server,
                                                       page):
        # Left set across an instance switch, the next mousemove over a panel
        # would resize whatever ended up at the old selected index.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m._slabDrag = {plane: 'top', handle: 'u-min', offset: [0, 0, 0]};
                m.clearAnnotations();
            }""")
        assert manager_eval(page, "m._slabDrag") is None


class TestSlabKeyboardAccess(BasePlaywrightTest):
    """
    The slab panels, driven entirely from the keyboard.

    These panels exist because a perspective view compresses the extent along
    the view axis, so a box placed by eye comes out short in depth. That makes
    "adjust it in the 3D view instead" not an equivalent alternative for a
    keyboard user — it is exactly the imprecision the panels remove. Until this
    landed there was no keyboard path to them at all (WCAG 2.1.1).

    The arithmetic is tested in Jest; what a real browser adds is that the
    events actually reach the handler — that focus lands on the canvas, that
    the page does not scroll instead, and that nothing between here and the
    manager swallows the key.
    """

    def _draw_a_box(self, page, x0=0.42, y0=0.62, x1=0.58, y1=0.74):
        page.keyboard.press("c")
        canvas = page.locator(".pc-canvas")
        box = canvas.bounding_box()
        page.mouse.move(box["x"] + box["width"] * x0,
                        box["y"] + box["height"] * y0)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * x1,
                        box["y"] + box["height"] * y1, steps=8)
        page.mouse.up()
        page.wait_for_timeout(250)

    def _focus_slab(self, page):
        canvas = page.locator(".pc-slab-canvas").first
        canvas.scroll_into_view_if_needed()
        canvas.focus()
        return canvas

    def test_the_panels_are_reachable_by_tab(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        canvas = self._focus_slab(page)
        # tabIndex 0 is what puts it in the tab order at all; a positive value
        # would also work but reorders the whole page, which is its own bug.
        assert canvas.evaluate("c => c.tabIndex") == 0
        assert page.evaluate(
            "() => document.activeElement.classList.contains('pc-slab-canvas')")

    def test_an_interactive_canvas_is_not_hidden_from_assistive_tech(
            self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(400)
        hidden = page.evaluate(
            """() => [...document.querySelectorAll('.pc-slab-canvas')]
                     .map(c => c.getAttribute('aria-hidden'))""")
        assert hidden == [None, None, None], (
            "the slab canvases take pointer and keyboard input, so "
            "aria-hidden removes the only way a screen-reader user could know "
            "they exist (WCAG 4.1.2)")

    def test_each_panel_is_named_by_its_plane(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(400)
        labels = page.evaluate(
            """() => [...document.querySelectorAll('.pc-slab-canvas')]
                     .map(c => c.getAttribute('aria-label'))""")
        assert len(set(labels)) == 3, labels
        assert all(label and "slab view" in label for label in labels)

    def test_the_keys_are_described_on_the_page(self, spatial_server, page):
        # Visible, not screen-reader-only: a sighted keyboard user needs them
        # too, and "shift grows, alt shrinks" is not guessable from the
        # pointer affordances.
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(400)
        help_id = page.get_attribute(".pc-slab-canvas", "aria-describedby")
        assert help_id
        target = page.locator(f"#{help_id}")
        assert target.is_visible()
        assert "Shift" in target.text_content()

    def test_an_arrow_moves_the_selected_box(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        before = json.loads(page.input_value("#input-objects"))[0]["coordinates"]

        self._focus_slab(page)
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)

        after = json.loads(page.input_value("#input-objects"))[0]["coordinates"]
        assert after["center"] != before["center"]
        assert after["size"] == before["size"]

    def test_shift_and_alt_resize_one_face(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        self._focus_slab(page)
        before = json.loads(page.input_value("#input-objects"))[0]["coordinates"]

        page.keyboard.press("Shift+ArrowRight")
        page.wait_for_timeout(150)
        grown = json.loads(page.input_value("#input-objects"))[0]["coordinates"]
        assert grown["size"][0] > before["size"][0]

        page.keyboard.press("Alt+ArrowRight")
        page.wait_for_timeout(150)
        shrunk = json.loads(page.input_value("#input-objects"))[0]["coordinates"]
        assert shrunk["size"][0] == pytest.approx(before["size"][0], abs=1e-6)

    def test_brackets_change_the_slab_thickness(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self._focus_slab(page)
        before = manager_eval(page, "m.config.slabThickness")
        page.keyboard.press("BracketRight")
        page.wait_for_timeout(150)
        assert manager_eval(page, "m.config.slabThickness") > before

    def test_an_edit_is_announced(self, spatial_server, page):
        # The panels are pixels. Without a live region an edit that only
        # redraws them is completely silent.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        self._focus_slab(page)
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)
        region = page.locator(".pc-announce[aria-live]")
        assert region.count() == 1
        assert region.text_content().strip()

    def test_a_keyboard_edit_is_one_undo_step(self, spatial_server, page):
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        self._focus_slab(page)
        before = manager_eval(page, "m.history.length")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(200)
        assert manager_eval(page, "m.history.length") == before + 2

    def test_an_existing_box_is_reachable_without_a_mouse(self, spatial_server,
                                                          page):
        # selectedIndex used to be set only by drawing a box or clicking one,
        # so every selection-dependent key -- and the whole slab surface --
        # was unreachable for anything the annotator had not just drawn.
        open_viewer(self, page, spatial_server)
        self._draw_a_box(page)
        # The second box goes in through addAnnotation rather than a second
        # drag: what is under test is reaching an annotation you did not just
        # make, and a drag that lands on the first box picks it up instead.
        page.evaluate(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                m.addAnnotation({type: 'cuboid_3d', label: 'truck',
                                 color: '#4ECDC4',
                                 coordinates: {center: [12, 3, -1],
                                               size: [6, 2.4, 2.8],
                                               rotation: [0, 0, 0, 1]}});
            }""")
        assert len(json.loads(page.input_value("#input-objects"))) == 2

        page.locator(".pc-canvas").focus()
        page.keyboard.press("Comma")
        page.wait_for_timeout(150)
        first = manager_eval(page, "m.selectedIndex")
        page.keyboard.press("Period")
        page.wait_for_timeout(150)
        assert manager_eval(page, "m.selectedIndex") != first

    def test_the_status_line_is_not_a_live_region(self, spatial_server, page):
        # Level-of-detail loading rewrites it about eight times a second while
        # the camera moves; an aria-live element that changes that often is a
        # screen reader that never stops talking.
        open_viewer(self, page, spatial_server)
        page.wait_for_timeout(400)
        assert page.get_attribute(".pc-status", "aria-live") is None
        assert page.get_attribute(".pc-status", "role") is None


@pytest.fixture
def lidar_only_server(make_server):
    """
    The same scenes with the calibration stripped out.

    Not a contrived fixture: a lidar-only project is the documented normal
    case, and it is the one where the slab panels' first-load bug is visible.
    With calibration present the camera image finishes loading, the page
    reflows, `.pc-mpr` changes width, and its ResizeObserver redraws the panels
    — so the bug hides behind an accident of this example having a photograph.
    """
    if not MEDIA.is_dir():
        pytest.skip("run examples/spatial/kitti-cuboids/generate_scene.py first")
    schemes = [dict(SCHEMES[0])]
    schemes[0].pop("calibration_field", None)
    return make_server(
        schemes,
        items=[{"id": s["id"], "point_cloud": s["point_cloud"]}
               for s in scene_items()],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "point_cloud"},
        },
    )


class TestSlabPanelsOnFirstLoad(BasePlaywrightTest):
    """
    The slabs must be drawn by the time the cloud is on screen.

    `_buildMprPanels` runs during `init()`, before the first byte of the cloud
    has been fetched, so the panels' first draw is of an empty scene. Nothing
    used to redraw them until the annotator selected something, resized the
    window, or scrolled the wheel over one — three blank rectangles under a
    populated viewport.

    `test_each_canvas_is_actually_painted` does not catch it, and neither did
    the first version of the test below: with calibration in the fixture the
    camera image's reflow fires the ResizeObserver and repaints the panels for
    unrelated reasons. Confirmed by reverting the fix and watching both pass.
    The lidar-only fixture removes that accident.
    """

    def test_the_panels_are_painted_without_relying_on_a_resize(
            self, lidar_only_server, page):
        # ResizeObserver is neutered for this test, which is the whole point:
        # the panels were being repainted only because some later layout change
        # -- a camera image finishing, a font settling -- happened to resize
        # `.pc-mpr`. Depending on that is depending on an accident. Verified to
        # fail when the redraw-on-node-arrival is removed.
        page.add_init_script(
            "window.ResizeObserver = class { observe() {} unobserve() {} "
            "disconnect() {} };")
        open_viewer(self, page, lidar_only_server)
        # Long enough for every octree node to arrive; the assertion is about
        # what is on screen once loading settles, not about timing.
        page.wait_for_function(
            """() => {
                const m = document.querySelector(
                    '.pointcloud-annotation-container').annotationManager;
                return m && m.loadedPointCount() > 0;
            }""", timeout=15000)
        page.wait_for_timeout(500)

        painted = page.evaluate(
            """() => [...document.querySelectorAll('.pc-slab-canvas')].map(c => {
                if (!c.width) return 'unsized';
                const d = c.getContext('2d').getImageData(
                    0, 0, c.width, c.height).data;
                const f = [d[0], d[1], d[2]];
                for (let i = 4; i < d.length; i += 4) {
                    if (d[i] !== f[0] || d[i+1] !== f[1] || d[i+2] !== f[2]) {
                        return true;
                    }
                }
                return false;
            })""")
        assert painted == [True, True, True], (
            f"slab panels {painted} — a panel that is uniformly its own "
            f"background is showing the annotator an empty scene under a "
            f"viewport full of points")

    def test_the_keyboard_focus_ring_is_the_product_ring(self, spatial_server,
                                                         page):
        # Driven with a real Tab, not element.focus(): a scripted focus does
        # not set :focus-visible in Chromium, so a probe that focuses
        # programmatically reads the UA default and says nothing about the
        # rule. This measured `outline-style: none` before it was corrected.
        open_viewer(self, page, spatial_server)
        canvas = page.locator(".pc-slab-canvas").first
        canvas.scroll_into_view_if_needed()
        page.locator(".pc-canvas").focus()
        for _ in range(12):
            page.keyboard.press("Tab")
            if page.evaluate(
                    "() => document.activeElement.classList"
                    ".contains('pc-slab-canvas')"):
                break
        else:
            pytest.fail("Tab never reached a slab canvas")

        ring = page.evaluate(
            """() => {
                const s = getComputedStyle(document.activeElement);
                return [s.outlineStyle, s.outlineWidth, s.outlineColor];
            }""")
        style, width, color = ring
        assert style not in ("none", ""), f"no focus ring at all: {ring}"
        # rgb(110, 86, 207) is --ring / --primary. The panels shipped with a
        # Bootstrap blue that appears nowhere else in the product.
        assert color == "rgb(110, 86, 207)", ring
        assert width == "3px", ring
