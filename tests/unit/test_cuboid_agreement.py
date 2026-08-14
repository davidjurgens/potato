"""
Agreement over oriented 3D boxes.

Ground truths here are **derived, not recorded**: the expected IoU of two
2 m cubes rotated 45° apart is `2s²(√2−1)` from the octagon formula, not
whatever this implementation printed the first time. A test that records its
subject's output only pins the behaviour in place, including the bugs.

Also checked are the invariances, which are the cheapest way to catch a whole
class of error at once: IoU is symmetric, unchanged by translating both boxes,
unchanged by rotating both boxes, and unchanged by scaling both boxes. A wrong
rotation matrix, a dropped translation, or a mis-scaled tolerance breaks at
least one of them.
"""

from __future__ import annotations

import math

import pytest

from potato.export.spatial_utils import (normalize_spatial_object,
                                         rotation_matrix,
                                         to_client_spatial_object,
                                         yaw_to_quaternion)
from potato.server_utils.iaa.geometry import (cuboid_intersection_volume,
                                              iou_cuboid_3d, match_instances,
                                              similarity, spatial_similarity)


def box(center, size, rotation=None, yaw=None, label="car"):
    """A canonical spatial object, built through the real contract."""
    return normalize_spatial_object(to_client_spatial_object(
        "cuboid_3d", label, center=center, size=size,
        rotation=rotation, yaw=yaw))


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def rotate_point(point, quat):
    m = rotation_matrix(quat)
    return [sum(m[r][c] * point[c] for c in range(3)) for r in range(3)]


class TestKnownVolumes:
    def test_a_box_agrees_perfectly_with_itself(self):
        # The failure this must never regress to: two identical boxes share
        # every face, and a face counted twice makes the shared volume equal
        # the union, the union zero, and the IoU of a box with ITSELF zero --
        # perfect agreement reported as total disagreement.
        a = box([3.0, -1.0, 0.5], [4.2, 1.8, 1.5], yaw=0.4)
        assert iou_cuboid_3d(a, a) == pytest.approx(1.0)

    def test_disjoint_boxes_share_nothing(self):
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([10, 0, 0], [2, 2, 2])) == 0.0

    def test_boxes_touching_at_a_face_share_no_volume(self):
        # Adjacent, not overlapping. A tolerance that is too generous turns
        # every neighbouring parked car into a partial match.
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([2, 0, 0], [2, 2, 2])) == 0.0

    def test_half_overlap_along_one_axis(self):
        # Intersection 1x2x2 = 4; union 8 + 8 - 4 = 12.
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([1, 0, 0], [2, 2, 2])) == pytest.approx(4 / 12)

    def test_one_box_entirely_inside_another(self):
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([0, 0, 0], [1, 1, 1])) == pytest.approx(1 / 8)

    def test_forty_five_degree_yaw_gives_the_octagon_area(self):
        # Two squares of side s sharing a centre and rotated 45 degrees apart
        # intersect in a regular octagon of area 2s²(√2 − 1). For s = 2 that
        # is 8(√2 − 1); times the shared height of 2.
        side = 2.0
        octagon = 2 * side * side * (math.sqrt(2) - 1)
        shared = octagon * 2
        expected = shared / (8 + 8 - shared)
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([0, 0, 0], [2, 2, 2], yaw=math.pi / 4)) \
            == pytest.approx(expected)

    def test_a_quarter_turn_of_a_square_footprint_changes_nothing(self):
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([0, 0, 0], [2, 2, 2], yaw=math.pi / 2)) \
            == pytest.approx(1.0)

    def test_a_quarter_turn_of_an_oblong_footprint_leaves_a_square(self):
        # A 4 x 2 footprint turned 90 degrees meets the original in the
        # 2 x 2 square at their shared centre.
        shared = 2 * 2 * 2.0
        volume = 4 * 2 * 2.0
        expected = shared / (volume + volume - shared)
        assert iou_cuboid_3d(box([0, 0, 0], [4, 2, 2]),
                             box([0, 0, 0], [4, 2, 2], yaw=math.pi / 2)) \
            == pytest.approx(expected)

    def test_vertically_separated_boxes_do_not_overlap(self):
        # Bird's-eye-view IoU alone would call these a perfect match: they
        # occupy exactly the same ground footprint, one above the other.
        assert iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                             box([0, 0, 5], [2, 2, 2])) == 0.0

    def test_the_intersection_volume_is_reported_in_cubic_metres(self):
        assert cuboid_intersection_volume(
            box([0, 0, 0], [2, 2, 2]),
            box([1, 0, 0], [2, 2, 2])) == pytest.approx(4.0)


class TestOutOfPlaneRotation:
    """
    The reason this is exact rather than bird's-eye-view times height.

    BEV x height is exact when both boxes are level and silently wrong when
    either is not -- and the storage contract carries full quaternions
    precisely so that drone, handheld and indoor-scan data are representable.
    """

    def test_a_pitched_box_does_not_fully_contain_its_level_twin(self):
        pitch = [math.sin(math.pi / 8), 0.0, 0.0, math.cos(math.pi / 8)]
        level = box([0, 0, 0], [4, 2, 2])
        tilted = box([0, 0, 0], [4, 2, 2], rotation=pitch)
        overlap = iou_cuboid_3d(level, tilted)
        assert 0.0 < overlap < 1.0, (
            "a 45-degree pitch must reduce the shared volume; scoring 1.0 is "
            "the signature of projecting to the ground plane and multiplying "
            "by height, which cannot see pitch at all")

    def test_pitch_and_yaw_of_the_same_angle_agree_by_symmetry(self):
        # A 4x2x2 box pitched 45 degrees about X and a 2x2x2 box yawed 45
        # degrees about Z both reduce to the same square-cross-section
        # problem, so the two IoUs must match exactly.
        pitch = [math.sin(math.pi / 8), 0.0, 0.0, math.cos(math.pi / 8)]
        pitched = iou_cuboid_3d(box([0, 0, 0], [4, 2, 2]),
                                box([0, 0, 0], [4, 2, 2], rotation=pitch))
        yawed = iou_cuboid_3d(box([0, 0, 0], [2, 2, 2]),
                              box([0, 0, 0], [2, 2, 2], yaw=math.pi / 4))
        assert pitched == pytest.approx(yawed)

    def test_a_three_axis_tumble_is_still_finite_and_bounded(self):
        tumble = [0.2, 0.3, 0.4, 0.8386]
        value = iou_cuboid_3d(box([0, 0, 0], [3, 2, 1]),
                              box([0.2, 0.1, 0], [3, 2, 1], rotation=tumble))
        assert 0.0 < value < 1.0
        assert math.isfinite(value)


class TestInvariances:
    PAIRS = [
        (([0, 0, 0], [2, 2, 2], None), ([1, 0.5, 0], [2, 3, 1.5], 0.3)),
        (([4, -2, 1], [4.2, 1.8, 1.5], 0.1), ([4.6, -1.7, 1.1], [4, 2, 1.6], -0.4)),
        (([0, 0, 0], [1, 5, 1], 1.2), ([0, 0, 0], [5, 1, 1], -0.9)),
    ]

    @pytest.mark.parametrize("first,second", PAIRS)
    def test_symmetry(self, first, second):
        a = box(first[0], first[1], yaw=first[2])
        b = box(second[0], second[1], yaw=second[2])
        assert iou_cuboid_3d(a, b) == pytest.approx(iou_cuboid_3d(b, a))

    @pytest.mark.parametrize("first,second", PAIRS)
    def test_translating_both_boxes_changes_nothing(self, first, second):
        shift = [17.0, -8.5, 3.25]
        a = box(first[0], first[1], yaw=first[2])
        b = box(second[0], second[1], yaw=second[2])
        moved_a = box([first[0][i] + shift[i] for i in range(3)], first[1],
                      yaw=first[2])
        moved_b = box([second[0][i] + shift[i] for i in range(3)], second[1],
                      yaw=second[2])
        assert iou_cuboid_3d(moved_a, moved_b) == \
            pytest.approx(iou_cuboid_3d(a, b), abs=1e-9)

    @pytest.mark.parametrize("first,second", PAIRS)
    def test_rotating_both_boxes_changes_nothing(self, first, second):
        # The strongest single check on the rotation maths: an error in the
        # matrix moves both boxes consistently only if it is a real rotation.
        turn = [0.3, -0.2, 0.5, 0.7874]
        norm = math.sqrt(sum(v * v for v in turn))
        turn = [v / norm for v in turn]

        a = box(first[0], first[1], yaw=first[2])
        b = box(second[0], second[1], yaw=second[2])
        rot_a = box(rotate_point(first[0], turn), first[1],
                    rotation=quat_mul(turn, list(yaw_to_quaternion(first[2] or 0))))
        rot_b = box(rotate_point(second[0], turn), second[1],
                    rotation=quat_mul(turn, list(yaw_to_quaternion(second[2] or 0))))
        assert iou_cuboid_3d(rot_a, rot_b) == \
            pytest.approx(iou_cuboid_3d(a, b), abs=1e-7)

    @pytest.mark.parametrize("first,second", PAIRS)
    def test_scaling_both_boxes_changes_nothing(self, first, second):
        # A property check, not a regression guard for anything observed: the
        # current absolute-vs-relative choice of tolerance was measured and
        # makes no difference across nine orders of magnitude of box size.
        # It is here so that a future scale-dependent constant cannot creep in
        # unnoticed.
        k = 0.05
        a = box(first[0], first[1], yaw=first[2])
        b = box(second[0], second[1], yaw=second[2])
        small_a = box([v * k for v in first[0]], [v * k for v in first[1]],
                      yaw=first[2])
        small_b = box([v * k for v in second[0]], [v * k for v in second[1]],
                      yaw=second[2])
        assert iou_cuboid_3d(small_a, small_b) == \
            pytest.approx(iou_cuboid_3d(a, b), abs=1e-6)


class TestDegenerateInput:
    def test_a_zero_size_box_shares_nothing(self):
        # The contract keeps degenerate boxes (with a warning) rather than
        # dropping them, because dropping shifts every index after it -- so
        # they reach here and must not divide by zero.
        flat = normalize_spatial_object({
            "type": "cuboid_3d", "label": "car",
            "coordinates": {"center": [0, 0, 0], "size": [2, 2, 0],
                            "rotation": [0, 0, 0, 1]}})
        assert iou_cuboid_3d(flat, box([0, 0, 0], [2, 2, 2])) == 0.0
        assert iou_cuboid_3d(flat, flat) == 0.0

    def test_missing_geometry_is_not_an_exception(self):
        assert iou_cuboid_3d({}, box([0, 0, 0], [1, 1, 1])) == 0.0
        assert iou_cuboid_3d(None, None) == 0.0


class TestOtherSpatialTypes:
    def test_points_agree_within_a_tolerance_and_decay_beyond_it(self):
        near = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [1, 1, 1]})
        same = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [1, 1, 1]})
        close = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [1.1, 1, 1]})
        far = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [9, 9, 9]})

        assert spatial_similarity(near, same) == pytest.approx(1.0)
        assert 0.9 < spatial_similarity(near, close) < 1.0
        assert spatial_similarity(near, far) == 0.0

    def test_polylines_are_compared_in_three_dimensions(self):
        # Two paths tracing the same ground track at different heights are NOT
        # the same annotation. Comparing them in 2D -- the default for the
        # boundary measure, since it exists for image polygons -- would score
        # them a perfect 1.0.
        ground = normalize_spatial_object({
            "type": "polyline_3d", "label": "kerb",
            "coordinates": [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]]})
        overhead = normalize_spatial_object({
            "type": "polyline_3d", "label": "kerb",
            "coordinates": [[0, 0, 6], [1, 0, 6], [2, 0, 6], [3, 0, 6]]})

        assert spatial_similarity(ground, ground) == pytest.approx(1.0)
        assert spatial_similarity(ground, overhead) == 0.0

    def test_segments_use_jaccard_over_point_indices(self):
        def seg(indices):
            return normalize_spatial_object({
                "type": "segment_3d", "label": "road", "indices": indices})

        assert spatial_similarity(seg([1, 2, 3]), seg([1, 2, 3])) == 1.0
        # {1,2} shared of {1,2,3,4} union.
        assert spatial_similarity(seg([1, 2, 3]), seg([1, 2, 4])) == \
            pytest.approx(2 / 4)
        assert spatial_similarity(seg([1, 2]), seg([8, 9])) == 0.0

    def test_different_types_never_match(self):
        cuboid = box([0, 0, 0], [2, 2, 2])
        point = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [0, 0, 0]})
        assert spatial_similarity(cuboid, point) == 0.0


class TestDispatchAndMatching:
    def test_similarity_routes_spatial_objects_to_the_spatial_measures(self):
        # Before this dispatch existed, a cuboid fell through to the 2D bbox
        # default, which reads a "bbox" key a spatial object does not have --
        # so every pair of 3D boxes scored 0.0. Not an error: a confident
        # report that no two annotators ever agree.
        a = box([2, 0, 0], [4, 2, 2])
        assert similarity(a, a) == pytest.approx(1.0)
        assert similarity(a, box([20, 0, 0], [4, 2, 2])) == 0.0

    def test_instance_matching_works_over_cuboids(self):
        """
        The three questions -- detection, localization, classification -- all
        run off `match_instances`, so cuboids reaching it is what makes 3D
        agreement work at all.
        """
        first = [box([0, 0, 0], [4, 2, 2], label="car"),
                 box([20, 0, 0], [4, 2, 2], label="truck")]
        second = [box([0.3, 0.1, 0], [4, 2, 2], label="car"),
                  box([60, 0, 0], [4, 2, 2], label="car")]

        matches, only_first, only_second = match_instances(first, second,
                                                           threshold=0.3)
        assert [(i, j) for i, j, _ in matches] == [(0, 0)]
        # The truck at 20 m and the car at 60 m are detection disagreements,
        # which is exactly what the unmatched lists are for.
        assert only_first == [1]
        assert only_second == [1]
