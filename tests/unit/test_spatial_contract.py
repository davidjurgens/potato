"""
The 3D coordinate contract.

Structured like `test_coco_roundtrip.py`'s contract tests, and for the same
reason: every exporter bug this project has had came from someone hand-building
the shape the client is *believed* to write. The round-trip tests here assert
that ``to_client_spatial_object`` and ``normalize_spatial_object`` are exact
inverses, so an importer that goes through the builder cannot drift from what
the viewer actually reads.
"""

from __future__ import annotations

import math

import pytest

from potato.export.spatial_utils import (
    IDENTITY_QUATERNION,
    SPATIAL_TYPES,
    axis_aligned_bounds,
    cuboid_corners,
    normalize_quaternion,
    normalize_spatial_object,
    quaternion_to_yaw,
    to_client_spatial_object,
    yaw_to_quaternion,
)


class TestRoundTrip:
    def test_cuboid(self):
        built = to_client_spatial_object(
            "cuboid_3d", "car", "#ff0000",
            center=[1.0, 2.0, 3.0], size=[4.0, 1.8, 1.5],
            rotation=[0.0, 0.0, 0.3826834, 0.9238795], track_id="t7")
        back = normalize_spatial_object(built)

        assert back["type"] == "cuboid_3d"
        assert back["label"] == "car"
        assert back["center"] == [1.0, 2.0, 3.0]
        assert back["size"] == [4.0, 1.8, 1.5]
        assert back["track_id"] == "t7"
        assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in
                   zip(back["rotation"], [0.0, 0.0, 0.3826834, 0.9238795]))

    def test_point(self):
        built = to_client_spatial_object("point_3d", "pole",
                                         center=[5.0, -1.0, 0.25])
        assert built["coordinates"] == [5.0, -1.0, 0.25]
        assert normalize_spatial_object(built)["center"] == [5.0, -1.0, 0.25]

    def test_polyline(self):
        pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 1.0, 0.5]]
        built = to_client_spatial_object("polyline_3d", "lane", points=pts)
        assert normalize_spatial_object(built)["points"] == pts

    def test_segment(self):
        built = to_client_spatial_object("segment_3d", "ground",
                                         indices=[0, 5, 9])
        # Indices, not coordinates: per-point labels over a million points
        # cannot round-trip as a coordinate list.
        assert built["indices"] == [0, 5, 9]
        assert normalize_spatial_object(built)["indices"] == [0, 5, 9]

    def test_nothing_is_normalized_to_zero_one(self):
        # The single most likely mistake when copying the 2D contract: 3D is
        # absolute metres in a sensor frame and must pass through untouched.
        built = to_client_spatial_object(
            "cuboid_3d", "car", center=[123.5, -47.25, 2.0], size=[4.0, 2.0, 1.5])
        assert built["coordinates"]["center"] == [123.5, -47.25, 2.0]


class TestQuaternions:
    def test_a_non_unit_quaternion_is_normalized_on_read(self):
        # A non-unit quaternion SCALES the box when converted to a matrix, so
        # the annotation renders at the wrong size rather than failing.
        quat = normalize_quaternion([0.0, 0.0, 2.0, 2.0])
        assert math.isclose(sum(v * v for v in quat), 1.0, abs_tol=1e-9)

    @pytest.mark.parametrize("bad", [None, [], [1, 2], "x", [0, 0, 0, 0],
                                     [float("nan"), 0, 0, 1]])
    def test_unusable_rotations_fall_back_to_identity(self, bad):
        assert normalize_quaternion(bad) == IDENTITY_QUATERNION

    @pytest.mark.parametrize("yaw", [0.0, 0.5, -1.25, math.pi / 2, 3.0])
    def test_yaw_round_trips_through_a_quaternion(self, yaw):
        assert math.isclose(quaternion_to_yaw(yaw_to_quaternion(yaw)), yaw,
                            abs_tol=1e-9)

    def test_quaternion_to_yaw_is_lossy_and_that_is_the_point(self):
        # A box tilted out of the horizontal plane comes back flat. KITTI can
        # only store yaw, so its exporter must be the place that admits this —
        # not the storage format, which keeps the full rotation.
        pitched = [0.3826834, 0.0, 0.0, 0.9238795]        # 45 deg about X
        assert math.isclose(quaternion_to_yaw(pitched), 0.0, abs_tol=1e-9)

    def test_yaw_and_rotation_together_is_an_error(self):
        # Silently preferring one would leave a caller convinced the other was
        # applied, with no way to tell from the output.
        with pytest.raises(ValueError, match="not both"):
            to_client_spatial_object("cuboid_3d", "car", center=[0, 0, 0],
                                     size=[1, 1, 1], rotation=[0, 0, 0, 1],
                                     yaw=1.0)

    def test_yaw_builds_the_same_object_as_its_quaternion(self):
        a = to_client_spatial_object("cuboid_3d", "car", center=[0, 0, 0],
                                     size=[1, 1, 1], yaw=0.75)
        b = to_client_spatial_object("cuboid_3d", "car", center=[0, 0, 0],
                                     size=[1, 1, 1],
                                     rotation=list(yaw_to_quaternion(0.75)))
        assert a == b


class TestRejection:
    @pytest.mark.parametrize("obj", [
        None, "cuboid", 42, {},
        {"type": "bbox", "coordinates": {"x": 0}},          # a 2D type
        {"type": "cuboid_3d"},                              # no coordinates
        {"type": "cuboid_3d", "coordinates": {"center": [1, 2, 3]}},  # no size
        {"type": "cuboid_3d", "coordinates": {"size": [1, 2, 3]}},    # no centre
        {"type": "point_3d", "coordinates": [1, 2]},        # 2D point
        {"type": "polyline_3d", "coordinates": [[0, 0, 0]]},  # one vertex
        {"type": "segment_3d", "indices": []},
        {"type": "segment_3d", "indices": "0,1,2"},
    ])
    def test_unusable_objects_are_none_not_exceptions(self, obj):
        # Callers filter on None. Raising would make one malformed annotation
        # take down a whole export.
        assert normalize_spatial_object(obj) is None

    def test_a_2d_annotation_is_not_claimed(self):
        # The two contracts must not both accept the same object, or which one
        # ran becomes a matter of call order.
        assert normalize_spatial_object(
            {"type": "polygon", "coordinates": [{"x": 0.1, "y": 0.2}]}) is None

    def test_a_degenerate_cuboid_is_kept_with_a_warning(self):
        # Dropping it would shift the index of every annotation after it, and
        # an index is the identity in the client's handle list.
        obj = normalize_spatial_object({
            "type": "cuboid_3d",
            "coordinates": {"center": [0, 0, 0], "size": [0, 1, 1]}})
        assert obj is not None
        assert obj["size"] == [0.0, 1.0, 1.0]
        assert any("non-positive" in w for w in obj["warnings"])

    def test_negative_sizes_are_absolute(self):
        obj = normalize_spatial_object({
            "type": "cuboid_3d",
            "coordinates": {"center": [0, 0, 0], "size": [-4, 2, -1]}})
        assert obj["size"] == [4.0, 2.0, 1.0]

    def test_a_bad_polyline_vertex_is_dropped_not_fatal(self):
        obj = normalize_spatial_object({
            "type": "polyline_3d",
            "coordinates": [[0, 0, 0], "nope", [1, 1, 1], [2, 2]]})
        assert obj["points"] == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]

    def test_builder_refuses_unknown_types(self):
        assert to_client_spatial_object("cuboid_4d", "x") is None
        assert set(SPATIAL_TYPES) == {"cuboid_3d", "point_3d", "polyline_3d",
                                      "segment_3d"}


class TestCorners:
    def test_an_unrotated_box(self):
        corners = cuboid_corners([0, 0, 0], [2, 4, 6], IDENTITY_QUATERNION)
        assert len(corners) == 8
        xs = sorted({round(c[0], 6) for c in corners})
        ys = sorted({round(c[1], 6) for c in corners})
        zs = sorted({round(c[2], 6) for c in corners})
        assert xs == [-1.0, 1.0]
        assert ys == [-2.0, 2.0]
        assert zs == [-3.0, 3.0]

    def test_the_first_four_corners_are_the_low_z_face(self):
        # Fixed rather than incidental: anything drawing the twelve edges
        # depends on this ordering.
        corners = cuboid_corners([0, 0, 0], [2, 2, 2], IDENTITY_QUATERNION)
        assert all(math.isclose(c[2], -1.0) for c in corners[:4])
        assert all(math.isclose(c[2], 1.0) for c in corners[4:])

    def test_a_ninety_degree_yaw_swaps_the_footprint(self):
        corners = cuboid_corners([0, 0, 0], [4, 2, 1],
                                 yaw_to_quaternion(math.pi / 2))
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        assert math.isclose(max(xs), 1.0, abs_tol=1e-6)
        assert math.isclose(max(ys), 2.0, abs_tol=1e-6)

    def test_translation_moves_every_corner(self):
        corners = cuboid_corners([10, 20, 30], [2, 2, 2], IDENTITY_QUATERNION)
        assert all(9.0 <= c[0] <= 11.0 for c in corners)
        assert all(19.0 <= c[1] <= 21.0 for c in corners)


class TestBounds:
    def test_a_rotated_box_bounds_its_corners_not_its_size(self):
        # A 45-degree yaw makes the axis-aligned extent larger than the box.
        # Using size/2 as the bound would under-report and let a genuinely
        # overlapping pair be rejected by the pre-filter.
        obj = normalize_spatial_object(to_client_spatial_object(
            "cuboid_3d", "car", center=[0, 0, 0], size=[4, 4, 2],
            yaw=math.pi / 4))
        lo, hi = axis_aligned_bounds(obj)
        assert hi[0] > 2.0
        assert math.isclose(hi[0], 2 * math.sqrt(2), abs_tol=1e-6)

    def test_a_polyline_bounds_its_vertices(self):
        obj = normalize_spatial_object(to_client_spatial_object(
            "polyline_3d", "lane",
            points=[[0, 0, 0], [10, -5, 2], [3, 3, 3]]))
        assert axis_aligned_bounds(obj) == [[0.0, -5.0, 0.0], [10.0, 3.0, 3.0]]

    def test_a_segment_has_no_bounds_of_its_own(self):
        # It refers to points in the cloud; the cloud has the coordinates.
        obj = normalize_spatial_object(
            to_client_spatial_object("segment_3d", "ground", indices=[1, 2]))
        assert axis_aligned_bounds(obj) is None
