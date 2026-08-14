"""
Camera calibration and 3D->2D projection.

Every fixture here is either a real KITTI calibration (the numbers below are
from the KITTI object-detection devkit's own sample) or built from first
principles inside the test. The alternative -- asserting against whatever this
module happens to produce -- would have let the Wave 8.1 LAS bug through again,
where the fixture builder shared the reader's error and the two agreed with
each other.

The assertions are therefore mostly *geometric*: a point on the ground projects
below the horizon, a point to the left of the sensor projects to the left of
the principal point, a point behind the camera projects nowhere. Those hold for
any correct implementation and fail for the plausible wrong ones.
"""

import math

import pytest

from potato.media.calibration import (
    NEAR_PLANE,
    Calibration,
    CalibrationError,
    Camera,
    clip_bbox_to_image,
    compose_rt,
    invert_rt,
    parse_calibration,
    parse_kitti_calib,
    project_cuboid,
    project_point,
    project_segment,
    to_camera_frame,
)

# A real KITTI object-detection calibration. P2 is the left colour camera,
# which is the one every KITTI benchmark uses; its fourth column is the
# rectified stereo baseline and is deliberately non-zero.
KITTI_CALIB = """P0: 7.215377e+02 0.000000e+00 6.095593e+02 0.000000e+00 0.000000e+00 7.215377e+02 1.728540e+02 0.000000e+00 0.000000e+00 0.000000e+00 1.000000e+00 0.000000e+00
P1: 7.215377e+02 0.000000e+00 6.095593e+02 -3.875744e+02 0.000000e+00 7.215377e+02 1.728540e+02 0.000000e+00 0.000000e+00 0.000000e+00 1.000000e+00 0.000000e+00
P2: 7.215377e+02 0.000000e+00 6.095593e+02 4.485728e+01 0.000000e+00 7.215377e+02 1.728540e+02 2.163791e-01 0.000000e+00 0.000000e+00 1.000000e+00 2.745884e-03
P3: 7.215377e+02 0.000000e+00 6.095593e+02 -3.395242e+02 0.000000e+00 7.215377e+02 1.728540e+02 2.199936e+00 0.000000e+00 0.000000e+00 1.000000e+00 2.729905e-03
R0_rect: 9.999239e-01 9.837760e-03 -7.445048e-03 -9.869795e-03 9.999421e-01 -4.278459e-03 7.402527e-03 4.351614e-03 9.999631e-01
Tr_velo_to_cam: 7.533745e-03 -9.999714e-01 -6.166020e-04 -4.069766e-03 1.480249e-02 7.280733e-04 -9.998902e-01 -7.631618e-02 9.998621e-01 7.523790e-03 1.480755e-02 -2.717806e-01
Tr_imu_to_velo: 9.999976e-01 7.553071e-04 -2.035826e-03 -8.086759e-01 -7.854027e-04 9.998898e-01 -1.482298e-02 3.195559e-01 2.024406e-03 1.482454e-02 9.998881e-01 -7.997231e-01
"""

#: KITTI's image_2 is 1242 x 375 and its principal point is (609.6, 172.9).
KITTI_WIDTH, KITTI_HEIGHT = 1242, 375
PRINCIPAL_U, PRINCIPAL_V = 609.5593, 172.8540


def kitti_camera(name="P2"):
    return parse_kitti_calib(KITTI_CALIB, cameras=(name,)).cameras[0]


def simple_camera(**kwargs):
    """
    An ideal camera at the origin looking down +Z, in its own frame.

    Focal length 100, principal point (50, 50), so the arithmetic is checkable
    by hand: a point at (1, 0, 1) lands at u = 150.
    """
    defaults = dict(
        name="test",
        k=(100.0, 0.0, 50.0, 0.0, 100.0, 50.0, 0.0, 0.0, 1.0),
        rt=(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        width=100, height=100,
    )
    defaults.update(kwargs)
    return Camera(**defaults)


class TestIdealCamera:
    """Arithmetic simple enough to verify without a calculator."""

    def test_a_point_on_the_axis_hits_the_principal_point(self):
        assert project_point(simple_camera(), (0, 0, 5)) == (50.0, 50.0)

    def test_offset_scales_with_focal_length_over_depth(self):
        # x = 1 m at z = 1 m, f = 100 px  ->  100 px right of centre.
        assert project_point(simple_camera(), (1, 0, 1)) == (150.0, 50.0)
        # Twice as far away is half the offset. If this fails, the divide by
        # depth is missing and the projection is orthographic.
        assert project_point(simple_camera(), (1, 0, 2)) == (100.0, 50.0)

    def test_a_point_behind_the_camera_projects_to_nothing(self):
        # THE bug this module exists to prevent: negative depth divides to a
        # plausible pixel mirrored through the principal point. A naive
        # implementation returns (-50, 50) here, which is a real coordinate.
        assert project_point(simple_camera(), (1, 0, -1)) is None

    def test_a_point_on_the_image_plane_projects_to_nothing(self):
        assert project_point(simple_camera(), (1, 0, 0)) is None

    def test_the_near_plane_is_not_zero(self):
        # A point a nanometre in front of the lens projects to a coordinate in
        # the billions, which stretches any bbox computed from it.
        assert project_point(simple_camera(), (1, 0, 1e-9)) is None
        assert project_point(simple_camera(), (1, 0, NEAR_PLANE * 2)) is not None

    def test_extrinsics_translate_the_point(self):
        # Camera one metre to the right of the sensor: a point on the sensor
        # axis is one metre to its left.
        cam = simple_camera(rt=(1, 0, 0, -1, 0, 1, 0, 0, 0, 0, 1, 0))
        assert project_point(cam, (0, 0, 1)) == (-50.0, 50.0)


class TestNearPlaneClipping:
    def test_a_segment_wholly_behind_the_camera_is_dropped(self):
        assert project_segment(simple_camera(), (0, 0, -1), (1, 0, -2)) is None

    def test_a_segment_wholly_in_front_is_unchanged(self):
        seg = project_segment(simple_camera(), (0, 0, 1), (1, 0, 1))
        assert seg == ((50.0, 50.0), (150.0, 50.0))

    def test_a_straddling_segment_is_cut_at_the_near_plane(self):
        # From 1 m in front to 1 m behind, offset 1 m in x throughout. The
        # visible half must end near the far edge of the frustum, not wrap
        # around to a negative coordinate.
        seg = project_segment(simple_camera(), (1, 0, 1), (1, 0, -1))
        assert seg is not None
        (u0, _v0), (u1, _v1) = seg
        assert u0 == pytest.approx(150.0)
        # At the near plane, x/z = 1/0.05 = 20, so u = 50 + 2000.
        assert u1 == pytest.approx(50.0 + 100.0 / NEAR_PLANE)
        assert u1 > 0, "the clipped end must stay on the same side of centre"

    def test_clipping_is_symmetric_in_argument_order(self):
        cam = simple_camera()
        forward = project_segment(cam, (1, 0, 1), (1, 0, -1))
        backward = project_segment(cam, (1, 0, -1), (1, 0, 1))
        assert forward[0] == pytest.approx(backward[1])
        assert forward[1] == pytest.approx(backward[0])


class TestKITTICalibration:
    def test_the_intrinsics_are_read_from_p2(self):
        cam = kitti_camera()
        assert cam.k[0] == pytest.approx(721.5377)
        assert cam.k[2] == pytest.approx(PRINCIPAL_U)
        assert cam.k[5] == pytest.approx(PRINCIPAL_V)

    def test_the_stereo_baseline_is_recovered_not_discarded(self):
        # P2's fourth column encodes a ~6 cm offset from the reference camera.
        # An implementation that assumes t = 0 puts every box off by that much
        # -- small enough to look like annotator sloppiness.
        cam = kitti_camera("P2")
        reference = kitti_camera("P0")
        assert cam.rt[3] != pytest.approx(reference.rt[3], abs=1e-4)
        # t = K^-1 @ P[:, 3], with the FULL inverse. Dividing P[0, 3] by fx --
        # the obvious shortcut, and my own first guess at this number -- gives
        # 44.857 / 721.538 = 0.0622 m, because it ignores K's third column.
        # The principal-point term contributes -cx/fx * P[2, 3], about
        # -2.3 mm, so the true offset is 0.0598 m. Small, systematic, and
        # exactly the kind of error that reads as sloppy annotation.
        expected = (44.85728 - PRINCIPAL_U * 2.745884e-03) / 721.5377
        assert expected == pytest.approx(0.0598, abs=1e-4)
        assert abs(cam.rt[3] - reference.rt[3]) == pytest.approx(expected,
                                                                 abs=1e-6)

    def test_the_right_camera_has_the_full_baseline(self):
        # P3 is the right colour camera, ~54 cm across the roof rack.
        left = kitti_camera("P2")
        right = kitti_camera("P3")
        assert abs(right.rt[3] - left.rt[3]) == pytest.approx(0.53, abs=0.02)

    def test_a_point_ahead_at_ground_level_lands_below_the_horizon(self):
        # Velodyne frame: +x forward, +y left, +z up, sensor ~1.7 m up.
        cam = kitti_camera()
        u, v = project_point(cam, (10.0, 0.0, -1.6))
        assert 0 < u < KITTI_WIDTH and 0 < v < KITTI_HEIGHT
        assert u == pytest.approx(PRINCIPAL_U, abs=15), "should be near centre"
        assert v > PRINCIPAL_V, "the road is below the horizon"

    def test_distance_moves_a_ground_point_toward_the_horizon(self):
        cam = kitti_camera()
        _u_near, v_near = project_point(cam, (8.0, 0.0, -1.6))
        _u_far, v_far = project_point(cam, (40.0, 0.0, -1.6))
        assert v_far < v_near, "further away is higher in the image"
        assert v_far > PRINCIPAL_V, "but never above the horizon"

    def test_positive_y_is_to_the_left_of_the_image(self):
        # The handedness check. Getting this backwards mirrors every box, which
        # looks correct until an object is off-centre.
        cam = kitti_camera()
        u_left, _ = project_point(cam, (12.0, 4.0, -1.5))
        u_right, _ = project_point(cam, (12.0, -4.0, -1.5))
        assert u_left < PRINCIPAL_U < u_right

    def test_a_point_behind_the_lidar_is_not_visible(self):
        assert project_point(kitti_camera(), (-8.0, 0.0, -1.5)) is None

    def test_a_car_sized_box_projects_to_a_car_sized_bbox(self):
        # 1.8 m wide at 10 m with f = 721 px is about 130 px; the box is 4 m
        # long so its projection spans somewhat more.
        cam = kitti_camera()
        result = project_cuboid(cam, [10.0, 0.0, -0.9], [4.0, 1.8, 1.5],
                                [0, 0, 0, 1])
        assert result["visible"] and len(result["edges"]) == 12
        x0, y0, x1, y1 = result["bbox"]
        assert 130 < (x1 - x0) < 260
        assert 100 < (y1 - y0) < 200
        assert 0 < x0 and x1 < KITTI_WIDTH

    def test_missing_projection_rows_are_reported_not_guessed(self):
        with pytest.raises(CalibrationError, match="P2"):
            parse_kitti_calib(KITTI_CALIB, cameras=("P9",))

    def test_a_file_that_is_not_kitti_says_so(self):
        with pytest.raises(CalibrationError, match="KITTI"):
            parse_kitti_calib("width: 100\nheight: 200\n")

    def test_a_missing_velo_transform_warns_rather_than_silently_guessing(self):
        text = "\n".join(line for line in KITTI_CALIB.splitlines()
                         if not line.startswith("Tr_velo_to_cam"))
        calibration = parse_kitti_calib(text)
        assert any("Tr_velo_to_cam" in w for w in calibration.warnings)


class TestMatrixHelpers:
    def test_compose_applies_the_right_hand_transform_first(self):
        # Translate by +1 x, then rotate 90 degrees about z. Applying them the
        # other way round gives (0, 1, 0) instead, and both look plausible.
        translate = (1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0)
        rotate = (0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0)
        composed = compose_rt(rotate, translate)
        cam = simple_camera(rt=composed)
        point = to_camera_frame(cam, (0, 0, 0))
        assert point == pytest.approx((0.0, 1.0, 0.0))

    def test_invert_round_trips_a_rigid_transform(self):
        angle = 0.7
        rt = (math.cos(angle), -math.sin(angle), 0, 3.0,
              math.sin(angle), math.cos(angle), 0, -1.0,
              0, 0, 1, 0.5)
        cam = simple_camera(rt=compose_rt(invert_rt(rt), rt))
        for probe in ((1, 2, 3), (-4, 0.5, 2)):
            assert to_camera_frame(cam, probe) == pytest.approx(probe)

    def test_inverting_a_scaled_matrix_is_refused(self):
        # R^T is only the inverse of an orthonormal R. Applying it to a scaled
        # matrix returns something that is not a pose, and the error would show
        # up as boxes drifting with distance.
        scaled = (2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0)
        with pytest.raises(CalibrationError, match="rigid"):
            invert_rt(scaled)

    def test_a_singular_intrinsic_matrix_is_refused(self):
        with pytest.raises(CalibrationError, match="singular"):
            parse_kitti_calib("P2: 0 0 0 0 0 0 0 0 0 0 0 0")


class TestNativeShapes:
    def test_fx_fy_cx_cy(self):
        calibration = parse_calibration({
            "cameras": [{"name": "front",
                         "intrinsics": {"fx": 100, "fy": 100,
                                        "cx": 50, "cy": 50}}]})
        assert project_point(calibration.cameras[0], (1, 0, 1)) == (150.0, 50.0)

    def test_a_three_by_three_matrix(self):
        calibration = parse_calibration({
            "cameras": [{"intrinsics": [[100, 0, 50], [0, 100, 50], [0, 0, 1]]}]})
        assert project_point(calibration.cameras[0], (0, 1, 1)) == (50.0, 150.0)

    def test_quaternion_extrinsics(self):
        # A 90-degree yaw about z: the sensor's +x axis becomes the camera's
        # +y axis.
        half = math.sqrt(0.5)
        calibration = parse_calibration({"cameras": [{
            "intrinsics": {"fx": 1, "fy": 1, "cx": 0, "cy": 0},
            "extrinsics": {"rotation": [0, 0, half, half],
                           "translation": [0, 0, 0]}}]})
        moved = to_camera_frame(calibration.cameras[0], (1, 0, 0))
        assert moved == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)

    def test_nuscenes_style_top_level_rotation(self):
        calibration = parse_calibration({"cameras": [{
            "channel": "CAM_FRONT",
            "camera_intrinsic": [[100, 0, 50], [0, 100, 50], [0, 0, 1]],
            "rotation": [0, 0, 0, 1], "translation": [0, 0, 0]}]})
        assert calibration.cameras[0].name == "CAM_FRONT"
        assert project_point(calibration.cameras[0], (0, 0, 1)) == (50.0, 50.0)

    def test_a_four_by_four_extrinsic_drops_the_homogeneous_row(self):
        calibration = parse_calibration({"cameras": [{
            "intrinsics": {"fx": 100, "fy": 100, "cx": 50, "cy": 50},
            "extrinsics": [[1, 0, 0, 2], [0, 1, 0, 0], [0, 0, 1, 0],
                           [0, 0, 0, 1]]}]})
        assert project_point(calibration.cameras[0], (0, 0, 1)) == (250.0, 50.0)

    def test_missing_intrinsics_names_the_camera(self):
        with pytest.raises(CalibrationError, match="intrinsics"):
            parse_calibration({"cameras": [{"name": "front"}]})

    def test_nothing_at_all_is_an_error_not_an_empty_rig(self):
        with pytest.raises(CalibrationError):
            parse_calibration(None)
        with pytest.raises(CalibrationError, match="empty"):
            parse_calibration({"cameras": []})

    def test_inline_kitti_rows(self):
        rows = {}
        for line in KITTI_CALIB.splitlines():
            key, _, rest = line.partition(":")
            rows[key] = [float(v) for v in rest.split()]
        calibration = parse_calibration(rows)
        assert calibration.cameras[0].k[0] == pytest.approx(721.5377)


class TestDistortion:
    def test_zero_distortion_changes_nothing(self):
        plain = simple_camera()
        zeroed = simple_camera(distortion=(0.0, 0.0, 0.0, 0.0, 0.0))
        assert project_point(plain, (1, 1, 2)) == project_point(zeroed, (1, 1, 2))

    def test_barrel_distortion_pulls_points_toward_the_centre(self):
        # Negative k1 is barrel: off-axis points move inward. A point on the
        # axis is unaffected, which is what makes this a distortion rather than
        # a shift.
        distorted = simple_camera(distortion=(-0.2, 0.0, 0.0, 0.0, 0.0))
        u_plain, _ = project_point(simple_camera(), (1, 0, 1))
        u_dist, _ = project_point(distorted, (1, 0, 1))
        assert u_dist < u_plain
        assert project_point(distorted, (0, 0, 1)) == (50.0, 50.0)


class TestBboxClipping:
    def test_a_box_reaching_past_the_edge_is_trimmed(self):
        assert clip_bbox_to_image([-20, -5, 100, 90], 640, 480) == \
            [0.0, 0.0, 100.0, 90.0]

    def test_a_box_entirely_outside_is_dropped(self):
        assert clip_bbox_to_image([700, 10, 900, 90], 640, 480) is None

    def test_unknown_image_size_passes_the_box_through(self):
        # Better an unclipped box than a dropped one: we do not know the frame.
        assert clip_bbox_to_image([1, 2, 3, 4], None, None) == [1, 2, 3, 4]


class TestSerialization:
    def test_to_dict_round_trips_through_parse(self):
        original = kitti_camera()
        rebuilt = parse_calibration(
            {"cameras": [{"name": original.name,
                          "intrinsics": list(original.k),
                          "extrinsics": list(original.rt)}]}).cameras[0]
        assert rebuilt.k == pytest.approx(original.k)
        assert rebuilt.rt == pytest.approx(original.rt)
        # The whole point: the client gets the same projection the server has.
        probe = (12.0, 1.0, -1.2)
        assert project_point(rebuilt, probe) == \
            pytest.approx(project_point(original, probe))

    def test_camera_lookup_by_name(self):
        rig = Calibration(cameras=[simple_camera(name="a"),
                                   simple_camera(name="b")])
        assert rig.camera("b").name == "b"
        assert rig.camera("missing") is None
