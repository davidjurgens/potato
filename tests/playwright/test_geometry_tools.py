"""
Every Wave 1 geometry tool, drawn with a real mouse, checked for where it went.

Polyline, ellipse, keypoint_set and cuboid_2d had no browser coverage at all —
their round trip was pinned by Jest against hand-built objects, which is how
two export bugs once hid behind a passing suite.

**These assert coordinates, not just existence.** The nine canvas tests that
came before assert that a shape was drawn and that it survives navigation, and
none check where it landed — so a harness defect that put every box 29 px left
of the request went unnoticed until someone drew a box in a real browser and
looked at the number. Type-and-count assertions cannot see that.

Each tool is drawn at known image fractions and the stored normalized
coordinates are compared against them, with a tolerance of one image pixel
(~0.004 on the fixture) for rounding through the canvas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.playwright.test_base import BasePlaywrightTest

pytestmark = pytest.mark.playwright

MEDIA = Path("examples/image/geometry-primitives/media").resolve()

#: One image pixel on the 320x240 fitted picture, plus a little slack.
TOL = 0.006

SCHEMES = [{
    "annotation_type": "image_annotation",
    "name": "shapes",
    "description": "Outline each structure with the matching tool.",
    "source_field": "image_url",
    "tools": ["bbox", "polygon", "polyline", "ellipse",
              "keypoint_set", "cuboid_2d", "landmark"],
    "skeletons": {
        "simple_pose": {
            "names": ["head", "neck", "left_hand", "right_hand"],
            "edges": [[0, 1], [1, 2], [1, 3]],
        },
    },
    "labels": [
        {"name": "lane", "color": "#E74C3C"},
        {"name": "cell", "color": "#27AE60"},
        {"name": "vehicle", "color": "#2980B9"},
    ],
}]


@pytest.fixture
def geometry_server(make_server):
    if not (MEDIA / "street.jpg").is_file():
        pytest.skip("examples/image/geometry-primitives media is missing")
    return make_server(
        SCHEMES,
        items=[{"id": f"geo_{i}", "image_url": "/media/street.jpg"}
               for i in range(1, 4)],
        extra_config={
            "media_directory": str(MEDIA),
            "item_properties": {"id_key": "id", "text_key": "image_url"},
        },
    )


class TestGeometryTools(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, "shapes")

    def _only(self, page, kind):
        stored = self.read_annotation_data(page, "shapes")
        matching = [a for a in stored if a.get("type") == kind]
        assert len(matching) == 1, (
            f"expected exactly one {kind}, got {[a.get('type') for a in stored]}")
        return matching[0]

    # ---- one test per primitive, each checking position ----

    def test_polyline_keeps_its_vertices_and_stays_open(self, page, geometry_server):
        self._open(page, geometry_server)
        asked = [(0.10, 0.20), (0.30, 0.35), (0.50, 0.30)]
        self.click_points_on_image(page, "shapes", "polyline", asked,
                                   label="lane", complete=True)

        shape = self._only(page, "polyline")
        assert shape["label"] == "lane"
        assert shape["closed"] is False, (
            "a polyline that reports closed would export as a region the "
            "annotator never claimed")
        got = shape["coordinates"]
        assert len(got) == len(asked)
        for (fx, fy), point in zip(asked, got):
            assert abs(point["x"] - fx) < TOL, f"x: asked {fx}, got {point['x']}"
            assert abs(point["y"] - fy) < TOL, f"y: asked {fy}, got {point['y']}"

    def test_ellipse_is_stored_as_centre_and_radii(self, page, geometry_server):
        self._open(page, geometry_server)
        self.drag_shape_on_image(page, "shapes", "ellipse",
                                 0.60, 0.10, 0.80, 0.40, label="cell")

        got = self._only(page, "ellipse")["coordinates"]
        assert abs(got["cx"] - 0.70) < TOL
        assert abs(got["cy"] - 0.25) < TOL
        assert abs(got["rx"] - 0.10) < TOL, "rx is half the dragged width"
        assert abs(got["ry"] - 0.15) < TOL, "ry is half the dragged height"
        assert got["angle"] == 0

    def test_keypoint_set_commits_at_the_skeletons_length(self, page, geometry_server):
        """
        Four joints are declared, so the fourth click finishes it — no
        double-click. If that ever regresses, this asks for four points and
        gets a half-built skeleton.
        """
        self._open(page, geometry_server)
        asked = [(0.20, 0.55), (0.20, 0.65), (0.12, 0.75), (0.28, 0.75)]
        self.click_points_on_image(page, "shapes", "keypoint_set", asked,
                                   label="cell")

        shape = self._only(page, "keypoint_set")
        assert shape["skeleton"] == "simple_pose"
        got = shape["coordinates"]
        assert len(got) == 4
        for (fx, fy), point in zip(asked, got):
            assert abs(point["x"] - fx) < TOL
            assert abs(point["y"] - fy) < TOL
            assert point["v"] == 2, "clicked joints are COCO visibility 2"

    def test_cuboid_takes_a_front_face_then_a_depth_click(self, page, geometry_server):
        self._open(page, geometry_server)
        self.drag_shape_on_image(page, "shapes", "cuboid_2d",
                                 0.55, 0.55, 0.75, 0.80, label="vehicle")
        # The second click sets the depth offset from the front face's origin.
        # `arm=False` because re-selecting the tool would discard the face.
        self.click_points_on_image(page, "shapes", "cuboid_2d", [(0.80, 0.50)],
                                   arm=False)

        got = self._only(page, "cuboid_2d")["coordinates"]
        front, back = got["front"], got["back"]
        assert len(front) == 4 and len(back) == 4

        assert abs(front[0]["x"] - 0.55) < TOL
        assert abs(front[0]["y"] - 0.55) < TOL
        assert abs(front[2]["x"] - 0.75) < TOL
        assert abs(front[2]["y"] - 0.80) < TOL

        # Back face is the front face translated by (click - front origin).
        dx, dy = 0.80 - 0.55, 0.50 - 0.55
        for near, far in zip(front, back):
            assert abs((far["x"] - near["x"]) - dx) < TOL
            assert abs((far["y"] - near["y"]) - dy) < TOL

    def test_polygon_encloses_what_was_clicked(self, page, geometry_server):
        self._open(page, geometry_server)
        asked = [(0.30, 0.30), (0.50, 0.30), (0.40, 0.50)]
        self.click_points_on_image(page, "shapes", "polygon", asked,
                                   label="vehicle", complete=True)

        shape = self._only(page, "polygon")
        got = shape["coordinates"]
        assert len(got) == 3
        for (fx, fy), point in zip(asked, got):
            assert abs(point["x"] - fx) < TOL
            assert abs(point["y"] - fy) < TOL

    # ---- the whole set together ----

    def test_every_primitive_coexists_in_one_answer(self, page, geometry_server):
        """
        They share one serialized blob, so a type that serializes but does not
        deserialize corrupts the others rather than failing alone.
        """
        self._open(page, geometry_server)
        self.click_points_on_image(page, "shapes", "polyline",
                                   [(0.10, 0.20), (0.30, 0.35)],
                                   label="lane", complete=True)
        self.drag_shape_on_image(page, "shapes", "ellipse",
                                 0.60, 0.10, 0.80, 0.40, label="cell")
        self.click_points_on_image(page, "shapes", "keypoint_set",
                                   [(0.20, 0.55), (0.20, 0.65),
                                    (0.12, 0.75), (0.28, 0.75)], label="cell")
        self.drag_shape_on_image(page, "shapes", "cuboid_2d",
                                 0.55, 0.55, 0.75, 0.80, label="vehicle")
        self.click_points_on_image(page, "shapes", "cuboid_2d", [(0.80, 0.50)],
                                   arm=False)

        stored = self.read_annotation_data(page, "shapes")
        assert sorted(a["type"] for a in stored) == [
            "cuboid_2d", "ellipse", "keypoint_set", "polyline"]

    def test_the_set_survives_navigating_away_and_back(self, page, geometry_server):
        """
        Next then Previous, never a refresh: browsers restore form state across
        a refresh, so a refresh-based check passes even when the server stored
        nothing.
        """
        self._open(page, geometry_server)
        self.click_points_on_image(page, "shapes", "polyline",
                                   [(0.10, 0.20), (0.30, 0.35)],
                                   label="lane", complete=True)
        self.drag_shape_on_image(page, "shapes", "ellipse",
                                 0.60, 0.10, 0.80, 0.40, label="cell")

        before = self.read_annotation_data(page, "shapes")
        restored = self.assert_persists_across_navigation(
            page, "shapes", expected_types=["ellipse", "polyline"])

        # And the geometry itself came back, not just the right number of rows.
        by_type = {a["type"]: a for a in restored}
        original = {a["type"]: a for a in before}
        assert by_type["ellipse"]["coordinates"] == original["ellipse"]["coordinates"]
        assert by_type["polyline"]["coordinates"] == original["polyline"]["coordinates"]
