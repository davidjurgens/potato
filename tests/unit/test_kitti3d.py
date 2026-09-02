"""
KITTI 3D labels <-> the spatial coordinate contract.

**The ground truth here is the KITTI devkit's own ``computeBox3D``**, not this
module's inverse. That distinction is the whole point of the file.

A round-trip test on a coordinate conversion is nearly worthless on its own: if
the forward and inverse share an assumption, they agree with each other and the
test passes on geometry that is completely wrong. That is exactly what happened
while writing this module -- reading KITTI's length as running along camera +Z
(the natural guess, since +Z is "forward") produced every box rotated 90
degrees, and the round trip closed to seven decimal places on it. The devkit's
corner formula, transcribed below from the MATLAB, is an independent witness
and caught it immediately.

It is also the second time this project has hit that failure mode: the Wave 8.1
LAS reader had its offset field four bytes early, and the fixture builder shared
the error.
"""

from __future__ import annotations

import math

import pytest

from potato.export.kitti3d import (TILT_TOLERANCE, cuboid_to_kitti,
                                   format_kitti_3d_line, kitti_to_cuboid,
                                   parse_kitti_3d_line)
from potato.export.spatial_utils import (cuboid_corners, normalize_spatial_object,
                                         quaternion_from_matrix, rotation_matrix,
                                         yaw_to_quaternion)
from potato.media.calibration import invert_rt, parse_kitti_calib
from tests.unit.test_calibration import KITTI_CALIB

REFERENCE_RT = parse_kitti_calib(KITTI_CALIB).reference_rt

#: An identity rig — lidar and camera in the same frame — so the conversions
#: can also be checked without the real rig's 0.85 degree mounting tilt
#: confusing which discrepancy is which.
IDENTITY_RT = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def devkit_corners(h, w, length, x, y, z, ry):
    """
    ``computeBox3D`` from the KITTI object devkit, transcribed from the MATLAB.

    Note ``x_corners`` uses ``l`` and ``z_corners`` uses ``w``: in the box's own
    frame, LENGTH runs along X and WIDTH along Z. That is the fact the module
    under test has to get right, so it is written out here rather than imported
    from anything that shares an assumption with it.
    """
    r = [[math.cos(ry), 0.0, math.sin(ry)],
         [0.0, 1.0, 0.0],
         [-math.sin(ry), 0.0, math.cos(ry)]]
    xs = [length / 2, length / 2, -length / 2, -length / 2,
          length / 2, length / 2, -length / 2, -length / 2]
    ys = [0, 0, 0, 0, -h, -h, -h, -h]
    zs = [w / 2, -w / 2, -w / 2, w / 2, w / 2, -w / 2, -w / 2, w / 2]

    out = []
    for i in range(8):
        local = [xs[i], ys[i], zs[i]]
        out.append([sum(r[row][col] * local[col] for col in range(3))
                    + [x, y, z][row] for row in range(3)])
    return out


def to_sensor(rt, point):
    inverse = invert_rt(rt)
    x, y, z = point
    return [inverse[0] * x + inverse[1] * y + inverse[2] * z + inverse[3],
            inverse[4] * x + inverse[5] * y + inverse[6] * z + inverse[7],
            inverse[8] * x + inverse[9] * y + inverse[10] * z + inverse[11]]


#: Real-looking KITTI label lines, covering each class and a spread of angles
#: including both wraparound edges.
LINES = [
    "Car 0.00 0 -1.57 599.41 156.40 629.75 189.25 1.48 1.56 3.62 1.84 1.47 8.41 -1.56",
    "Pedestrian 0.00 0 0.20 100.00 100.00 200.00 300.00 1.74 0.60 0.80 -4.20 1.60 12.30 0.42",
    "Van 0.00 2 2.90 300.00 150.00 480.00 280.00 2.20 1.90 5.10 3.30 1.55 24.90 3.05",
    "Cyclist 0.00 1 -2.10 700.00 160.00 760.00 240.00 1.70 0.55 1.75 6.10 1.50 18.20 -2.20",
    "Truck 0.00 0 1.10 10.00 10.00 90.00 90.00 3.10 2.60 9.20 -8.80 1.40 33.10 1.30",
    "Car 0.00 0 3.14 400.00 170.00 460.00 210.00 1.50 1.62 4.00 0.10 1.60 40.00 3.1415",
]


class TestAgainstTheDevkit:
    """The independent witness. Everything else is bookkeeping."""

    @pytest.mark.parametrize("line", LINES, ids=lambda s: s.split()[0] + s[-6:])
    @pytest.mark.parametrize("rt,rig", [(REFERENCE_RT, "kitti"),
                                        (IDENTITY_RT, "identity")])
    def test_the_converted_box_has_the_devkits_corners(self, line, rt, rig):
        label, dimensions, location, ry = parse_kitti_3d_line(line)

        expected = sorted(tuple(round(v, 6) for v in to_sensor(rt, corner))
                          for corner in devkit_corners(*dimensions, *location, ry))

        obj = kitti_to_cuboid(label, dimensions, location, ry, rt)
        coords = obj["coordinates"]
        actual = sorted(tuple(round(v, 6) for v in corner) for corner in
                        cuboid_corners(coords["center"], coords["size"],
                                       coords["rotation"]))

        for want, got in zip(expected, actual):
            for axis in range(3):
                assert got[axis] == pytest.approx(want[axis], abs=1e-5), (
                    f"{rig}: corner mismatch on axis {axis}. A 90-degree "
                    f"rotation here means length was read along the wrong "
                    f"local axis, and the round trip would not have noticed.")

    def test_a_box_pointing_along_the_camera_axis_is_not_square_on(self):
        """
        A sanity check on the *meaning*, independent of any matrix.

        A car with ry = -pi/2 on the standard rig is driving away from the ego
        vehicle, so its LENGTH must run roughly along the sensor's forward axis
        (+X) and its width across it. The 90-degree error made length run
        across, which is a car parked sideways in the middle of the road --
        wrong in a way that is obvious once stated and invisible in a round
        trip.
        """
        obj = kitti_to_cuboid("Car", [1.5, 1.6, 4.0], [0.0, 1.6, 20.0],
                              -math.pi / 2, REFERENCE_RT)
        corners = cuboid_corners(obj["coordinates"]["center"],
                                 obj["coordinates"]["size"],
                                 obj["coordinates"]["rotation"])
        span_x = max(c[0] for c in corners) - min(c[0] for c in corners)
        span_y = max(c[1] for c in corners) - min(c[1] for c in corners)
        assert span_x > 3.5, "the car's 4 m length should run fore-and-aft"
        assert span_y < 2.0, "its 1.6 m width should run across the road"


class TestRoundTrip:
    """
    Necessary but not sufficient — see the module docstring.

    These would all pass on the 90-degree-wrong conversion, which is why they
    come after the devkit comparison rather than instead of it.
    """

    @pytest.mark.parametrize("line", LINES, ids=lambda s: s.split()[0] + s[-6:])
    def test_the_fields_come_back_unchanged(self, line):
        label, dimensions, location, ry = parse_kitti_3d_line(line)
        obj = normalize_spatial_object(
            kitti_to_cuboid(label, dimensions, location, ry, REFERENCE_RT))
        back = cuboid_to_kitti(obj, REFERENCE_RT)

        assert back["dimensions"] == pytest.approx(dimensions, abs=1e-6)
        # Relative, because the tolerance has to scale with the coordinate: an
        # object at 40 m accumulates ~1e-6 of absolute error through the
        # several matrix products, which is 2.6e-8 relative -- float64 noise,
        # not a conversion mistake. A tighter absolute bound would fail on
        # distant objects only, which reads as a distance-dependent bug.
        assert back["location"] == pytest.approx(location, rel=1e-7, abs=1e-6)
        # atan2 wraps, so compare the angle rather than the number.
        assert math.cos(back["rotation_y"] - ry) == pytest.approx(1.0, abs=1e-9)

    def test_the_rigs_own_mounting_tilt_survives_the_import(self):
        """
        The reason the import carries the full rotation rather than a yaw.

        The standard KITTI camera sits about 0.85 degrees off the lidar, so a
        box that is level in the camera frame is genuinely tilted in the sensor
        frame. Storing only a yaw would flatten it -- discarding real geometry
        in the one direction that has no need to lose anything.
        """
        obj = kitti_to_cuboid("Car", [1.5, 1.6, 4.0], [0.0, 1.6, 20.0], 0.0,
                              REFERENCE_RT)
        m = rotation_matrix(obj["coordinates"]["rotation"])
        # Column 2 is the box's own up-axis. For a pure yaw it would be exactly
        # the sensor's +Z; here it is off by the rig's mounting angle.
        up = (m[0][2], m[1][2], m[2][2])
        off_vertical = math.acos(max(-1.0, min(1.0, up[2])))
        assert 0.005 < off_vertical < 0.05, (
            f"expected the rig's own ~0.85 degree mounting tilt, got "
            f"{off_vertical} radians; exactly 0 means the import flattened the "
            f"rotation to a yaw")


class TestLoss:
    """
    All measured against the REAL rig.

    An identity rig is the wrong fixture here: it makes the sensor frame a
    camera frame, where +Z is forward rather than up, so a box built with a
    yaw about "sensor Z" is not a level box at all and every expectation about
    tilt comes out nonsense. Using it cost two wrong test failures before the
    fixture, rather than the code, turned out to be the problem.
    """

    def test_a_box_that_came_from_kitti_loses_nothing_going_back(self):
        # The property that makes `tilt` trustworthy: exactly the rotations
        # KITTI can express report no loss.
        obj = normalize_spatial_object(kitti_to_cuboid(
            "Car", [1.5, 1.6, 4.0], [0.0, 1.6, 20.0], 0.7, REFERENCE_RT))
        assert cuboid_to_kitti(obj, REFERENCE_RT)["tilt"] == pytest.approx(
            0.0, abs=1e-3)

    def test_a_sensor_level_box_loses_the_rigs_mounting_angle(self):
        # A box the annotator drew level in the lidar frame is NOT level in the
        # camera frame, so KITTI cannot express it exactly. 0.85 degrees is
        # small, honest, and below the reporting threshold.
        obj = normalize_spatial_object({
            "type": "cuboid_3d", "label": "Car",
            "coordinates": {"center": [10, 0, -1], "size": [4, 2, 1.5],
                            "rotation": list(yaw_to_quaternion(0.9))}})
        tilt = cuboid_to_kitti(obj, REFERENCE_RT)["tilt"]
        assert tilt == pytest.approx(0.0149, abs=2e-3)
        assert tilt < TILT_TOLERANCE, (
            "the rig's own mounting angle must not trip the loss warning, or "
            "every export of every dataset reports a problem")

    def test_roll_that_kitti_cannot_carry_is_reported(self):
        # 30 degrees of roll about the sensor's forward axis. KITTI has no
        # field for it, so the export flattens the box -- and says how much.
        roll = [math.sin(math.pi / 12), 0.0, 0.0, math.cos(math.pi / 12)]
        obj = normalize_spatial_object({
            "type": "cuboid_3d", "label": "Car",
            "coordinates": {"center": [10, 0, -1], "size": [4, 2, 1.5],
                            "rotation": roll}})
        result = cuboid_to_kitti(obj, REFERENCE_RT)
        # Not exactly pi/6: the rig's own 0.85 degrees composes with the roll
        # rather than adding to it.
        assert result["tilt"] == pytest.approx(math.pi / 6, abs=0.02)
        assert result["tilt"] > TILT_TOLERANCE, (
            "30 degrees must exceed the reporting threshold, or an exporter "
            "would write flat boxes and say nothing")

    def test_more_roll_means_more_reported_loss(self):
        def tilt_for(angle):
            quat = [math.sin(angle / 2), 0.0, 0.0, math.cos(angle / 2)]
            obj = normalize_spatial_object({
                "type": "cuboid_3d", "label": "Car",
                "coordinates": {"center": [10, 0, -1], "size": [4, 2, 1.5],
                                "rotation": quat}})
            return cuboid_to_kitti(obj, REFERENCE_RT)["tilt"]

        values = [tilt_for(a) for a in (0.1, 0.3, 0.6, 1.0)]
        assert values == sorted(values)


class TestParsing:
    def test_a_two_dimensional_line_has_no_3d_block(self):
        assert parse_kitti_3d_line("Car 0.00 0 -1.5 1 2 3 4") is None

    def test_dont_care_sentinels_are_not_a_detection(self):
        # KITTI's own DontCare rows carry -1 dimensions and -1000 location.
        # Read as real, they place a zero-sized object at the camera origin,
        # which downstream 3D tooling scores as a false positive.
        line = ("DontCare -1 -1 -10 500 160 590 190 "
                "-1 -1 -1 -1000 -1000 -1000 -10")
        assert parse_kitti_3d_line(line) is None

    def test_a_sentinel_location_with_real_dimensions_is_still_refused(self):
        # Not hypothetical: some 2D-only exporters (this repository's own
        # kitti_exporter among them) write real class dimensions alongside the
        # -1000 "no 3D information" location. Only the location check catches
        # those -- the dimensions look perfectly valid.
        line = ("Car 0.00 0 -10 500 160 590 190 "
                "1.50 1.60 4.00 -1000 -1000 -1000 -10")
        assert parse_kitti_3d_line(line) is None

    def test_a_non_numeric_3d_block_is_refused(self):
        line = "Car 0 0 0 1 2 3 4 h w l x y z ry"
        assert parse_kitti_3d_line(line) is None

    def test_a_zero_height_object_is_refused(self):
        line = "Car 0.00 0 0 1 2 3 4 0.00 1.60 4.00 1.0 1.5 20.0 0.0"
        assert parse_kitti_3d_line(line) is None

    def test_a_written_line_parses_back(self):
        label, dimensions, location, ry = parse_kitti_3d_line(LINES[0])
        obj = normalize_spatial_object(
            kitti_to_cuboid(label, dimensions, location, ry, REFERENCE_RT))
        line = format_kitti_3d_line(
            label, cuboid_to_kitti(obj, REFERENCE_RT),
            bbox=[599.41, 156.40, 629.75, 189.25])

        assert len(line.split()) == 15, "KITTI lines have exactly 15 fields"
        again = parse_kitti_3d_line(line)
        assert again[0] == label
        assert again[1] == pytest.approx(dimensions, abs=0.01)
        assert again[2] == pytest.approx(location, abs=0.01)

    def test_the_2d_columns_are_corners_not_a_width_and_height(self):
        # The 2D half of the format made this exact mistake once already: a box
        # read as x, y, w, h starts in the right place and extends to roughly
        # double the correct size, which is plausible enough to survive review.
        obj = normalize_spatial_object(kitti_to_cuboid(
            "Car", [1.5, 1.6, 4.0], [0.0, 1.6, 20.0], 0.0, REFERENCE_RT))
        line = format_kitti_3d_line("Car", cuboid_to_kitti(obj, REFERENCE_RT),
                                    bbox=[100.0, 50.0, 180.0, 130.0])
        fields = line.split()
        assert fields[6] == "180.00" and fields[7] == "130.00"


class TestDegenerate:
    def test_a_non_cuboid_is_refused(self):
        point = normalize_spatial_object(
            {"type": "point_3d", "label": "a", "coordinates": [1, 2, 3]})
        assert cuboid_to_kitti(point, IDENTITY_RT) is None
        assert cuboid_to_kitti(None, IDENTITY_RT) is None

    def test_a_zero_dimension_box_is_refused_in_both_directions(self):
        assert kitti_to_cuboid("Car", [0, 1, 2], [0, 0, 5], 0.0,
                               IDENTITY_RT) is None
        flat = normalize_spatial_object({
            "type": "cuboid_3d", "label": "Car",
            "coordinates": {"center": [1, 2, 3], "size": [4, 2, 0],
                            "rotation": [0, 0, 0, 1]}})
        assert cuboid_to_kitti(flat, IDENTITY_RT) is None


class TestQuaternionFromMatrix:
    """The helper the import needs, since its rotation arrives as a frame."""

    ANGLES = [0.0, 0.3, math.pi / 2, 2.5, math.pi - 1e-6, -1.9]

    @pytest.mark.parametrize("angle", ANGLES)
    @pytest.mark.parametrize("axis", [(1, 0, 0), (0, 1, 0), (0, 0, 1),
                                      (0.577, 0.577, 0.577)])
    def test_it_inverts_rotation_matrix(self, angle, axis):
        half = angle / 2
        norm = math.sqrt(sum(v * v for v in axis))
        quat = [axis[0] / norm * math.sin(half), axis[1] / norm * math.sin(half),
                axis[2] / norm * math.sin(half), math.cos(half)]
        recovered = quaternion_from_matrix(rotation_matrix(quat))

        # q and -q are the same rotation, so compare the matrices, not the
        # four numbers.
        original = rotation_matrix(quat)
        again = rotation_matrix(list(recovered))
        for r in range(3):
            for c in range(3):
                assert again[r][c] == pytest.approx(original[r][c], abs=1e-9)

    def test_a_half_turn_does_not_lose_precision(self):
        # The single-branch `w = sqrt(1 + trace) / 2` formula divides by a
        # quantity approaching zero here and returns garbage.
        for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            quat = [axis[0], axis[1], axis[2], 0.0]
            recovered = quaternion_from_matrix(rotation_matrix(quat))
            assert sum(v * v for v in recovered) == pytest.approx(1.0, abs=1e-12)
            original = rotation_matrix(quat)
            again = rotation_matrix(list(recovered))
            for r in range(3):
                for c in range(3):
                    assert again[r][c] == pytest.approx(original[r][c], abs=1e-9)
