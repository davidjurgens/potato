"""
Image annotation canvas, driven through real mouse events.

A fabric canvas is a single <canvas> element: no shape has a DOM node, so
nothing here can be asserted with an element selector. These tests drag on the
canvas the way an annotator does and then read the hidden input the save path
actually collects — never the manager's in-memory state, which would hide the
serialization bugs that kept the CV exporters broken.

Persistence is checked by navigating away and back, never by refreshing.
Browsers restore form state across a refresh, so a refresh-based test passes
even when the server stored nothing.
"""

import pytest

from tests.playwright.test_base import BasePlaywrightTest


SCHEMA = "objects"

#: A 400x300 four-quadrant PNG in tests/data, served by FlaskTestServer at
#: /test-image/ (the same convention as the existing audio and video fixtures).
#:
#: NOT a data: URI. `sanitize_html` blocks the `data:` scheme outright as an XSS
#: vector, so a data URI is stripped out of the rendered instance text and the
#: manager never finds an image to load.
TEST_IMAGE = "test_image_400x300.png"

IMAGE_SCHEME = {
    "annotation_type": "image_annotation",
    "name": SCHEMA,
    "description": "Mark the objects",
    # Points the manager's URL discovery at the item field holding the image.
    "source_field": "image_url",
    "tools": ["bbox", "polygon", "brush", "eraser"],
    "labels": [
        {"name": "car", "color": "#FF0000"},
        {"name": "road", "color": "#00FF00"},
    ],
}


@pytest.fixture(scope="module")
def image_server():
    """A server whose items carry image URLs, which the default rows do not."""
    from tests.playwright.conftest import _make_server

    items = [
        {"id": f"img_{i}", "image_url": f"/test-image/{TEST_IMAGE}"}
        for i in range(3)
    ]
    # text_key must be the image field: the manager finds its image from the
    # rendered instance text, which is how every image example is wired.
    srv = _make_server(
        [IMAGE_SCHEME],
        items=items,
        extra_config={"item_properties": {"id_key": "id", "text_key": "image_url"}},
    )
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestCanvasDrawing(BasePlaywrightTest):
    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, SCHEMA)

    def test_the_canvas_initializes(self, page, image_server):
        """Without fabric or a loaded image, every later test is meaningless."""
        self._open(page, image_server)
        assert page.locator(f"#canvas-{SCHEMA}").is_visible()
        assert self.count_annotations(page, SCHEMA) == 0

    def test_dragging_creates_a_bbox(self, page, image_server):
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.1, 0.1, 0.5, 0.5, label="car")

        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 1
        assert data[0]["type"] == "bbox"
        assert data[0]["label"] == "car"

    def test_the_stored_shape_matches_the_client_contract(self, page, image_server):
        """
        Coordinates must be NORMALIZED under `coordinates`. Every CV exporter
        reads that shape; writing anything else is how bboxes silently exported
        as [0, 0, 0, 0].
        """
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.1, 0.1, 0.5, 0.5, label="car")

        coords = self.read_annotation_data(page, SCHEMA)[0]["coordinates"]
        assert set(coords) >= {"x", "y", "width", "height"}
        for key, value in coords.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} is not normalized"
        assert coords["width"] > 0 and coords["height"] > 0

    def test_drawing_twice_creates_two_annotations(self, page, image_server):
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.05, 0.05, 0.3, 0.3, label="car")
        self.draw_bbox_on_image(page, SCHEMA, 0.5, 0.5, 0.8, 0.8, label="road")

        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 2
        assert sorted(a["label"] for a in data) == ["car", "road"]

    def test_painting_creates_a_mask(self, page, image_server):
        """
        Masks are not fabric objects and ride the same blob as the shapes, as
        absolute RLE rather than normalized coordinates.
        """
        self._open(page, image_server)
        self.paint_stroke_on_image(page, SCHEMA,
                                   [(0.2, 0.2), (0.3, 0.3), (0.4, 0.35), (0.5, 0.4)],
                                   label="road")

        masks = [a for a in self.read_annotation_data(page, SCHEMA)
                 if a["type"] == "mask"]
        assert len(masks) == 1
        assert masks[0]["label"] == "road"
        assert masks[0]["rle"]["counts"], "mask has an empty RLE"
        assert len(masks[0]["rle"]["size"]) == 2

    def test_shapes_and_masks_share_one_blob(self, page, image_server):
        """They used to live in separate inputs, and only one was ever saved."""
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.05, 0.05, 0.3, 0.3, label="car")
        self.paint_stroke_on_image(page, SCHEMA, [(0.6, 0.6), (0.7, 0.7)], label="road")

        types = sorted(a["type"] for a in self.read_annotation_data(page, SCHEMA))
        assert types == ["bbox", "mask"]


@pytest.mark.playwright
class TestBoxesStayOnTheImage(BasePlaywrightTest):
    """
    The canvas is bigger than the bitmap and the image is centred in it, so
    there is a dead margin on every side. A drag that STARTED in that margin
    was stored unclamped -- {"x": -0.046, "y": -0.0007} for a 640x420 image on
    an 831x600 canvas -- and the region_caption panel read it back as
    "Region 1 (referent) - at -5%, 0%". A drag that stayed entirely in the
    margin was already discarded, so the rule existed and applied to only half
    the cases.
    """

    def _open(self, page, server):
        self.register_and_login(page, server)
        self.image_manager_ready(page, SCHEMA)

    def _drag_from_canvas_origin(self, page, tool="bbox"):
        """Start the drag at the canvas corner, which is outside the image."""
        rect = self.image_rect(page, SCHEMA)
        assert rect["left"] > 4 or rect["top"] > 4, (
            "this image fills its canvas, so there is no margin to test with")
        self.arm(page, SCHEMA, tool, "car")
        return self.draw_bbox(
            page, SCHEMA,
            2, 2,
            rect["left"] + rect["width"] * 0.5,
            rect["top"] + rect["height"] * 0.5,
            armed=True) if tool == "bbox" else None

    def test_a_drag_starting_in_the_margin_is_clamped_into_the_image(
            self, page, image_server):
        self._open(page, image_server)
        self._drag_from_canvas_origin(page)

        data = self.read_annotation_data(page, SCHEMA)
        assert len(data) == 1, "the box was discarded rather than clamped"
        coords = data[0]["coordinates"]
        assert coords["x"] >= 0, coords
        assert coords["y"] >= 0, coords
        assert coords["x"] + coords["width"] <= 1.0001, coords
        assert coords["y"] + coords["height"] <= 1.0001, coords

    def test_the_clamped_box_is_still_worth_keeping(self, page, image_server):
        # Clamping must not collapse the box: the annotator dragged across half
        # the picture and should get half the picture.
        self._open(page, image_server)
        self._drag_from_canvas_origin(page)

        coords = self.read_annotation_data(page, SCHEMA)[0]["coordinates"]
        assert coords["width"] > 0.2, coords
        assert coords["height"] > 0.2, coords

    def test_a_drag_running_off_the_far_edge_stops_at_the_edge(
            self, page, image_server):
        self._open(page, image_server)
        rect = self.image_rect(page, SCHEMA)
        canvas = page.locator(f"#canvas-{SCHEMA}").bounding_box()
        self.arm(page, SCHEMA, "bbox", "car")
        self.draw_bbox(
            page, SCHEMA,
            rect["left"] + rect["width"] * 0.5,
            rect["top"] + rect["height"] * 0.5,
            canvas["width"] - 2, canvas["height"] - 2,
            armed=True)

        coords = self.read_annotation_data(page, SCHEMA)[0]["coordinates"]
        assert coords["x"] + coords["width"] <= 1.0001, coords
        assert coords["y"] + coords["height"] <= 1.0001, coords

    def test_a_drag_wholly_inside_the_image_is_not_moved(self, page, image_server):
        """
        The clamp must be a no-op away from the edges.

        Asserted as "still strictly inside", not "landed at exactly 0.2": where
        a drag lands depends on the canvas layout at the moment of the drag,
        and pinning the exact fraction made this test order-dependent -- it
        passed after its siblings and failed alone.
        """
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.25, 0.25, 0.6, 0.6, label="car")

        coords = self.read_annotation_data(page, SCHEMA)[0]["coordinates"]
        assert 0 < coords["x"] < 1, coords
        assert 0 < coords["y"] < 1, coords
        assert coords["x"] + coords["width"] < 1, coords
        assert coords["y"] + coords["height"] < 1, coords


class TestCanvasPersistence(BasePlaywrightTest):
    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        self.image_manager_ready(page, SCHEMA)

    def test_a_bbox_survives_navigating_away_and_back(self, page, image_server):
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.1, 0.1, 0.5, 0.5, label="car")

        restored = self.assert_persists_across_navigation(
            page, SCHEMA, expected_types=["bbox"])
        assert restored[0]["label"] == "car"

    def test_a_mask_survives_navigating_away_and_back(self, page, image_server):
        """
        The harder half: masks are rebuilt from RLE rather than restored as
        fabric objects, and were silently lost on navigation for a long time.
        """
        self._open(page, image_server)
        self.paint_stroke_on_image(page, SCHEMA,
                                   [(0.2, 0.2), (0.3, 0.3), (0.4, 0.35)], label="road")

        restored = self.assert_persists_across_navigation(
            page, SCHEMA, expected_types=["mask"])
        assert restored[0]["rle"]["counts"]

    def test_annotations_do_not_leak_onto_the_next_image(self, page, image_server):
        """
        Instance switching clears the canvas. Masks live outside it, so they
        used to survive the clear and be re-serialized onto the NEXT image --
        attributing one annotator's work to a picture they never saw.
        """
        self._open(page, image_server)
        self.draw_bbox_on_image(page, SCHEMA, 0.1, 0.1, 0.4, 0.4, label="car")
        self.paint_stroke_on_image(page, SCHEMA, [(0.2, 0.2), (0.35, 0.3)], label="road")
        self.wait_for_debounce(page)

        self.click_next(page)
        self.image_manager_ready(page, SCHEMA)

        assert self.read_annotation_data(page, SCHEMA) == [], (
            "the previous image's annotations followed us to the next one")
