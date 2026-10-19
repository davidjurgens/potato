"""
Point-cloud sequences in a real browser: a box drawn with a drag, carried
forward with `f`, rotated on a later frame, its middle keyframe deleted, and
the frame between shown interpolated -- before and after navigating to the
next item and back.

The frames are examples/spatial/lidar-sequence's. Assertions read the stored
value and the scene graph (the mesh material), not screenshots.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest
from tests.playwright.test_spatial_annotation import manager_eval, wait_for_manager

pytestmark = pytest.mark.playwright

EXAMPLE = Path("examples/spatial/lidar-sequence").resolve()
MEDIA = EXAMPLE / "media"
FRAMES = [f"frames/drive_0001/{i:06d}.bin" for i in range(6)]

SCHEMES = [{
    "annotation_type": "spatial_annotation",
    "name": "objects",
    "description": "Track the vehicles",
    "source_field": "point_cloud",
    "tools": ["cuboid_3d"],
    "labels": [{"name": "car", "color": "#FF6B6B", "key_value": "1"}],
    "attributes": [{"name": "occluded", "type": "select",
                    "options": ["none", "partly"], "default": "none"}],
}]


@pytest.fixture
def sequence_server(make_server):
    if not MEDIA.is_dir():
        pytest.skip("run examples/spatial/lidar-sequence/generate_sequence.py first")
    return make_server(
        SCHEMES,
        items=[{"id": "drive_a", "point_cloud": FRAMES, "notes": "a"},
               {"id": "drive_b", "point_cloud": FRAMES, "notes": "b"}],
        extra_config={"media_directory": str(MEDIA),
                      "item_properties": {"id_key": "id", "text_key": "notes"}},
    )


def open_sequence(test, page, server):
    test.register_and_login(page, server)
    page.goto(f"{server.base_url}/annotate")
    wait_for_manager(page)
    page.wait_for_function(
        "() => document.querySelector('.pointcloud-annotation-container')"
        ".annotationManager.hasCloud()", timeout=30000)


def yaw(rotation):
    return math.degrees(2 * math.atan2(rotation[2], rotation[3]))


def stored(page):
    return json.loads(page.input_value("#input-objects") or "[]")


def wait_for_frame(page, index):
    page.wait_for_function(
        f"""() => {{
            const m = document.querySelector('.pointcloud-annotation-container').annotationManager;
            return m.frameIndex === {index} && m.hasCloud();
        }}""", timeout=30000)


class TestSequence(BasePlaywrightTest):
    def draw_car(self, page):
        """Drag a footprint around the car, located through the viewer's camera."""
        page.click('.pointcloud-annotation-container [data-tool="cuboid_3d"]')
        page.click('.pointcloud-annotation-container .label-btn[data-label="car"]')
        corners = page.evaluate("""() => {
            const m = document.querySelector('.pointcloud-annotation-container').annotationManager;
            const r = m.canvas.getBoundingClientRect();
            const p = (x, y) => {
                const v = new THREE.Vector3(x, y, m.groundZ).project(m.camera);
                return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height];
            };
            return [p(7.6, -2.3), p(12.4, 0.2)];
        }""")
        (x0, y0), (x1, y1) = corners
        page.mouse.move(x0, y0)
        page.mouse.down()
        for i in range(1, 5):
            page.mouse.move(x0 + (x1 - x0) * i / 4, y0 + (y1 - y0) * i / 4)
        page.mouse.up()

    def test_the_frame_bar_shows_and_frames_load_their_own_cloud(self, sequence_server, page):
        open_sequence(self, page, sequence_server)
        assert page.is_visible(".pc-frames")
        assert page.inner_text(".pc-frame-label") == "Frame 1 of 6"
        page.click('.pc-frames [data-frame-step="1"]')
        wait_for_frame(page, 1)
        assert manager_eval(page, "m._cloudPath()") == FRAMES[1]
        assert page.get_attribute(".pc-frame-slider", "aria-valuetext") == "Frame 2 of 6"

    def test_a_track_with_an_interpolated_frame_survives_next_and_previous(
            self, sequence_server, page):
        open_sequence(self, page, sequence_server)
        self.draw_car(page)
        [first] = stored(page)
        assert (first["frame"], first["track_id"], first["attributes"]) == \
            (0, "t1", {"occluded": "none"})

        page.click("body")                       # keys belong to the page again
        page.keyboard.press("f")
        wait_for_frame(page, 1)
        page.keyboard.press("f")
        wait_for_frame(page, 2)
        for _ in range(9):                       # 9 x 5 degrees
            page.keyboard.press("q")
        assert [k["frame"] for k in stored(page)] == [0, 1, 2]

        page.keyboard.press("[")                 # frame 1: delete its keyframe
        wait_for_frame(page, 1)
        page.keyboard.press(".")
        page.keyboard.press("Delete")
        assert [k["frame"] for k in stored(page)] == [0, 2]
        assert manager_eval(page, "m.annotations[0].interpolated") is True
        assert manager_eval(page, "m.meshes[0].material.type") == "LineDashedMaterial"
        page.wait_for_timeout(1500)              # the save debounce

        page.click("#next-btn")
        wait_for_manager(page)
        assert stored(page) == []
        page.click("#prev-btn")
        wait_for_manager(page)
        page.wait_for_function(
            "() => document.querySelector('.pointcloud-annotation-container')"
            ".annotationManager.hasCloud()", timeout=30000)

        keyframes = stored(page)
        assert [(k["frame"], k["track_id"]) for k in keyframes] == [(0, "t1"), (2, "t1")]
        assert yaw(keyframes[1]["coordinates"]["rotation"]) == pytest.approx(45, abs=0.5)
        page.keyboard.press("]")
        wait_for_frame(page, 1)
        assert manager_eval(page, "m.annotations[0].interpolated") is True
        assert yaw(manager_eval(page, "m.annotations[0].coordinates.rotation")) == \
            pytest.approx(22.5, abs=0.5)
        assert manager_eval(page, "m.meshes[0].material.type") == "LineDashedMaterial"
