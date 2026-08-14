"""
The geometry primitives added in Wave 1: polyline and ellipse.

Every type must survive ``normalize_annotation_object`` -> ``to_client_object``
byte-identically, because those two are the single source of truth for the
client/exporter contract. Two export bugs previously survived a full test suite
because the fixtures hand-built a shape the client never writes; these tests
start from the client shape and insist on getting it back.
"""

from __future__ import annotations

import math

import pytest

from potato.export.cv_utils import (
    ELLIPSE_POLYGON_VERTICES,
    ellipse_to_polygon,
    normalize_annotation_object,
    to_client_object,
)

W, H = 640, 480


def polyline(*pairs, label="lane"):
    return {"type": "polyline", "label": label, "color": "#f00",
            "coordinates": [{"x": x, "y": y} for x, y in pairs]}


def ellipse(cx, cy, rx, ry, angle=0.0, label="cell"):
    return {"type": "ellipse", "label": label, "color": "#0f0",
            "coordinates": {"cx": cx, "cy": cy, "rx": rx, "ry": ry,
                            "angle": angle}}


# ---------------------------------------------------------------------------
# Polyline
# ---------------------------------------------------------------------------

class TestPolyline:
    def test_normalizes_to_absolute_pixels(self):
        c = normalize_annotation_object(
            polyline((0.1, 0.2), (0.5, 0.25), (0.9, 0.3)), W, H)
        assert c["points"] == [[64.0, 96.0], [320.0, 120.0], [576.0, 144.0]]

    def test_has_no_area(self):
        """An open path encloses nothing; claiming area would invent a region."""
        c = normalize_annotation_object(
            polyline((0.1, 0.1), (0.9, 0.1), (0.9, 0.9)), W, H)
        assert c["area"] == 0.0
        assert c["closed"] is False

    def test_bbox_is_the_extent_of_the_vertices(self):
        c = normalize_annotation_object(
            polyline((0.1, 0.2), (0.5, 0.25), (0.9, 0.3)), W, H)
        assert c["bbox"] == [64.0, 96.0, 512.0, 48.0]

    def test_round_trips_exactly(self):
        original = polyline((0.1, 0.2), (0.5, 0.25), (0.9, 0.3))
        c = normalize_annotation_object(original, W, H)
        back = to_client_object("polyline", "lane", "#f00",
                                img_w=W, img_h=H, points=c["points"])
        assert back["coordinates"] == original["coordinates"]
        assert back["closed"] is False

    def test_a_single_point_is_not_a_polyline(self):
        assert normalize_annotation_object(polyline((0.5, 0.5)), W, H) is None
        assert to_client_object("polyline", "lane", img_w=W, img_h=H,
                                points=[[10, 10]]) is None

    def test_polygon_of_the_same_points_does_claim_area(self):
        """Control: the difference between the two types is real, not cosmetic."""
        pts = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9)]
        line = normalize_annotation_object(polyline(*pts), W, H)
        poly = normalize_annotation_object(
            {"type": "polygon", "label": "x",
             "coordinates": [{"x": x, "y": y} for x, y in pts]}, W, H)
        assert line["area"] == 0.0
        assert poly["area"] > 0.0
        assert line["bbox"] == poly["bbox"]


# ---------------------------------------------------------------------------
# Ellipse
# ---------------------------------------------------------------------------

class TestEllipse:
    def test_area_is_pi_r_r(self):
        c = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        assert c["area"] == pytest.approx(math.pi * 64 * 24)

    def test_bbox_of_an_unrotated_ellipse(self):
        c = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        assert c["bbox"] == pytest.approx([256.0, 216.0, 128.0, 48.0])

    def test_rotating_ninety_degrees_swaps_the_bbox(self):
        """
        The tight box of a rotated ellipse is not the rotated corner box.
        Half-extents are sqrt((rx cos)^2 + (ry sin)^2) and its transpose.
        """
        flat = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        turned = normalize_annotation_object(
            ellipse(0.5, 0.5, 0.1, 0.05, angle=90), W, H)
        assert turned["bbox"][2] == pytest.approx(flat["bbox"][3])
        assert turned["bbox"][3] == pytest.approx(flat["bbox"][2])

    def test_forty_five_degrees_is_not_the_corner_box(self):
        """A naive implementation returns the axis-aligned box unchanged."""
        flat = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.02), W, H)
        turned = normalize_annotation_object(
            ellipse(0.5, 0.5, 0.1, 0.02, angle=45), W, H)
        assert turned["bbox"][2] != pytest.approx(flat["bbox"][2])
        # ...and it must be smaller than the diagonal of the flat box.
        assert turned["bbox"][2] < flat["bbox"][2]

    def test_round_trips_exactly(self):
        original = ellipse(0.5, 0.4, 0.1, 0.05, angle=30)
        c = normalize_annotation_object(original, W, H)
        back = to_client_object("ellipse", "cell", "#0f0",
                                img_w=W, img_h=H, ellipse=c["ellipse"])
        assert back["coordinates"] == pytest.approx(original["coordinates"])

    def test_carries_a_polygon_approximation_for_downstream_consumers(self):
        c = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        assert len(c["points"]) == ELLIPSE_POLYGON_VERTICES
        # Every vertex lies on the ellipse: (x/rx)^2 + (y/ry)^2 == 1
        for x, y in c["points"]:
            dx, dy = (x - 320.0) / 64.0, (y - 240.0) / 24.0
            assert dx * dx + dy * dy == pytest.approx(1.0, abs=1e-9)

    def test_degenerate_radii_are_rejected(self):
        assert normalize_annotation_object(ellipse(0.5, 0.5, 0, 0.05), W, H) is None
        assert to_client_object("ellipse", "c", img_w=W, img_h=H,
                                ellipse={"cx": 1, "cy": 1, "rx": 0, "ry": 5}) is None

    def test_polygon_approximation_area_matches_the_analytic_area(self):
        """
        An inscribed n-gon always UNDER-estimates: its exact area is
        0.5 n rx ry sin(2 pi / n), which for n=36 is 99.49% of pi rx ry.

        Both facts are asserted — the bound, and the direction — because an
        approximation that started over-estimating would mean the vertices had
        drifted off the curve.
        """
        from potato.export.cv_utils import polygon_area

        n = ELLIPSE_POLYGON_VERTICES
        pts = ellipse_to_polygon(0, 0, 100, 50)
        exact = math.pi * 100 * 50
        expected = 0.5 * n * 100 * 50 * math.sin(2 * math.pi / n)

        assert polygon_area(pts) == pytest.approx(expected, rel=1e-9)
        assert polygon_area(pts) < exact
        assert polygon_area(pts) == pytest.approx(exact, rel=0.006)

    def test_a_circle_is_just_an_ellipse(self):
        c = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.1), W, H)
        assert c["ellipse"]["rx"] == pytest.approx(64.0)
        assert c["ellipse"]["ry"] == pytest.approx(48.0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestToolsAreRegistered:
    def test_both_types_are_valid_tools(self):
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS

        assert "polyline" in VALID_TOOLS
        assert "ellipse" in VALID_TOOLS

    def test_config_validation_shares_one_list(self):
        """Invariant 9: never a second copy of the valid-values list."""
        from potato.server_utils.schemas.image_annotation import VALID_TOOLS
        from potato.server_utils import config_module

        source = (config_module.__file__ and
                  open(config_module.__file__).read())
        assert "from potato.server_utils.schemas.image_annotation import VALID_TOOLS" in source
        assert '"polyline"' not in source.split("valid_tools")[0][-2000:]
        assert "polyline" in VALID_TOOLS

    def test_every_profile_binds_the_new_tools(self):
        from potato.server_utils.schemas.image_annotation import KEYBINDING_PROFILES

        for profile, mapping in KEYBINDING_PROFILES.items():
            assert "polyline" in mapping, profile
            assert "ellipse" in mapping, profile

    def test_a_config_using_them_validates(self):
        from potato.server_utils.schemas.image_annotation import (
            generate_image_annotation_layout,
        )

        html, keys = generate_image_annotation_layout({
            "annotation_type": "image_annotation",
            "name": "shapes",
            "description": "Shapes",
            "tools": ["polyline", "ellipse"],
            "labels": ["lane", "cell"],
        })
        assert 'data-tool="polyline"' in html
        assert 'data-tool="ellipse"' in html


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

class TestAgreementUnderstandsThem:
    def test_identical_polylines_agree(self):
        from potato.server_utils.iaa import geometry

        a = normalize_annotation_object(polyline((0.1, 0.1), (0.9, 0.9)), W, H)
        assert geometry.similarity(a, dict(a)) == pytest.approx(1.0)

    def test_distant_polylines_disagree(self):
        from potato.server_utils.iaa import geometry

        a = normalize_annotation_object(polyline((0.1, 0.1), (0.2, 0.2)), W, H)
        b = normalize_annotation_object(polyline((0.8, 0.8), (0.9, 0.9)), W, H)
        assert geometry.similarity(a, b) < 0.5

    def test_identical_ellipses_agree(self):
        from potato.server_utils.iaa import geometry

        a = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        assert geometry.similarity(a, dict(a)) == pytest.approx(1.0, abs=1e-6)

    def test_disjoint_ellipses_disagree(self):
        from potato.server_utils.iaa import geometry

        a = normalize_annotation_object(ellipse(0.2, 0.2, 0.05, 0.05), W, H)
        b = normalize_annotation_object(ellipse(0.8, 0.8, 0.05, 0.05), W, H)
        assert geometry.similarity(a, b) == pytest.approx(0.0)

    def test_an_ellipse_never_matches_a_polyline(self):
        """Different types are a real disagreement about representation."""
        from potato.server_utils.iaa import geometry

        a = normalize_annotation_object(ellipse(0.5, 0.5, 0.1, 0.05), W, H)
        b = normalize_annotation_object(polyline((0.4, 0.5), (0.6, 0.5)), W, H)
        assert geometry.similarity(a, b) == 0.0

    def test_display_summary_names_them(self):
        import json

        from potato.server_utils import annotation_values

        scheme = {"annotation_type": "image_annotation"}
        blob = json.dumps([polyline((0.1, 0.1), (0.2, 0.2)),
                           ellipse(0.5, 0.5, 0.1, 0.05)])
        summary = annotation_values.display_summary(scheme, blob)
        assert "1 ellipse" in summary
        assert "1 polyline" in summary
