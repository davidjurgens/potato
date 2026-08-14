"""
KITTI 3D labels: the boundary where the format's limitations are allowed to bite.

``spatial_utils`` stores rotation as a full quaternion so that drone, handheld
and indoor-scan data are representable. KITTI stores a single yaw. That gap has
to be crossed somewhere, and the whole point of the contract decision is that
it is crossed **here** -- in the format-specific code, loudly -- rather than in
the storage format, silently.

## The three conversions, and why each is easy to get wrong

**Frames.** KITTI's 3D fields are in the *rectified reference camera* frame
(+X right, +Y down, +Z forward). Potato's are in the sensor frame the point
cloud is in (+X forward, +Y left, +Z up for velodyne). They are related by
``R0_rect ∘ Tr_velo_to_cam``, which :class:`~potato.media.calibration.Calibration`
exposes as ``reference_rt``. Using a *camera's* ``rt`` instead shifts every box
by that camera's stereo baseline -- a few centimetres, systematic, and easy to
mistake for annotator sloppiness.

**Location is the bottom face, not the centre.** KITTI's ``x y z`` is the
midpoint of the box's *bottom* face. Reading it as the centre puts every object
half its own height underground.

**Dimension order is ``h w l``, and the axes are the devkit's, not the
obvious ones.** The devkit's ``computeBox3D`` lays its corners out with
``x_corners = ±l/2``, ``y_corners = 0..-h`` and ``z_corners = ±w/2``, so in the
box's own frame **length runs along X, height along Y (downward) and width
along Z**. Assuming instead that length runs along camera +Z — which reads as
the natural choice, since +Z is "forward" — produces a box rotated exactly 90°.
A round-trip test cannot catch that, because the inverse conversion makes the
same assumption and the two agree with each other. Only a comparison against
the devkit's own corner formula catches it, and one is in ``test_kitti3d.py``
for that reason.

**Rotation is derived from the calibration, not from a constant.** The relation
``yaw_velo = -ry - π/2`` is correct for the standard KITTI rig and is what most
code hard-codes. It is *not* correct for a rig whose lidar is mounted
differently, and it fails silently when it is wrong. Here the box's own axes are
transformed through the actual matrices, so a non-standard rig converts
correctly and the standard one reproduces the familiar number.

## What is lost, in which direction

Sensor frame → KITTI **discards pitch and roll**: a tilted box comes back flat.
:func:`cuboid_to_kitti` returns the loss in its result rather than warning once
and moving on, so an exporter can report exactly how many boxes were flattened.

KITTI → sensor frame is **lossless**, and not because yaw is a special case of
a quaternion — because the full rotation is carried across. On the standard rig
the camera is mounted about 0.85° off the lidar, so a box that is axis-aligned
in the camera frame is genuinely tilted in the sensor frame. Storing only the
yaw would throw that away in the one direction that does not have to lose
anything, which is precisely what the quaternion in the contract is for.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.export.spatial_utils import (quaternion_from_matrix,
                                         rotation_matrix,
                                         to_client_spatial_object)

logger = logging.getLogger(__name__)

#: Field indices of the 3D block in a KITTI label line.
DIMENSIONS = slice(8, 11)      # h, w, l
LOCATION = slice(11, 14)       # x, y, z of the BOTTOM face centre
ROTATION_Y = 14

#: Above this much pitch or roll (radians, ~2.9 degrees) a box is reported as
#: flattened by the conversion. Below it the tilt is within the noise of how
#: precisely anyone places a box by hand.
TILT_TOLERANCE = 0.05


def _apply_rt(rt: Sequence[float], point: Sequence[float]) -> List[float]:
    x, y, z = (float(v) for v in point[:3])
    return [rt[0] * x + rt[1] * y + rt[2] * z + rt[3],
            rt[4] * x + rt[5] * y + rt[6] * z + rt[7],
            rt[8] * x + rt[9] * y + rt[10] * z + rt[11]]


def _rotate(rt: Sequence[float], vector: Sequence[float]) -> List[float]:
    """Apply only the rotation block — for directions, which have no origin."""
    x, y, z = (float(v) for v in vector[:3])
    return [rt[0] * x + rt[1] * y + rt[2] * z,
            rt[4] * x + rt[5] * y + rt[6] * z,
            rt[8] * x + rt[9] * y + rt[10] * z]


def _axes_from_ry(ry: float, inverse_rt: Sequence[float]):
    """
    The box's three axes in the sensor frame, for a KITTI ``rotation_y``.

    Shared by the import and by the export's loss measurement, so that "what
    KITTI would store" is computed by exactly one piece of code. Two copies
    would agree with each other and disagree with reality, which is the failure
    this module already hit once.
    """
    return (_rotate(inverse_rt, [math.cos(ry), 0.0, -math.sin(ry)]),
            _rotate(inverse_rt, [math.sin(ry), 0.0, math.cos(ry)]),
            _rotate(inverse_rt, [0.0, -1.0, 0.0]))


def _rotation_between(a, b) -> float:
    """
    The angle, in radians, of the rotation taking frame ``a`` to frame ``b``.

    Both are 3x3 given as column triples. ``trace(Aᵀ B) = 1 + 2 cos θ`` for
    rotation matrices, which is the whole identity.
    """
    trace = sum(a[c][r] * b[c][r] for c in range(3) for r in range(3))
    return math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))


def kitti_to_cuboid(label: str, dimensions: Sequence[float],
                    location: Sequence[float], rotation_y: float,
                    reference_rt: Sequence[float], *,
                    color: str = "", track_id: Optional[str] = None
                    ) -> Optional[dict]:
    """
    One KITTI 3D label as a client-contract ``cuboid_3d`` in the sensor frame.

    ``reference_rt`` is the sensor-to-rectified-reference-camera 3x4, i.e.
    ``Calibration.reference_rt``. Lossless in this direction -- see the module
    docstring for why that needs the full rotation and not just the yaw.
    """
    from potato.media.calibration import invert_rt

    try:
        height, width, length = (float(v) for v in dimensions[:3])
        cam_point = [float(v) for v in location[:3]]
        ry = float(rotation_y)
    except (TypeError, ValueError, IndexError):
        return None
    if height <= 0 or width <= 0 or length <= 0:
        return None

    inverse = invert_rt(reference_rt)

    # KITTI's location is the BOTTOM face centre and camera +Y points DOWN, so
    # the centre is half a height in the negative Y direction.
    cam_point[1] -= height / 2.0
    centre = _apply_rt(inverse, cam_point)

    # The box's own axes in camera coordinates.
    #
    # The devkit's computeBox3D builds corners with `x_corners = ±l/2`,
    # `y_corners = 0..-h`, `z_corners = ±w/2` under
    #     R = [ cos ry, 0, sin ry;  0, 1, 0;  -sin ry, 0, cos ry ]
    # so in ITS local frame X is length, Y is height (downward), Z is width.
    # Our size is [length, width, height], so our local Y is width and our
    # local Z is height-upward:
    #
    #     ours X = devkit X,   ours Y = devkit Z,   ours Z = -devkit Y
    #
    # Assuming instead that length runs along camera +Z at ry = 0 -- the
    # natural guess -- yields a box rotated exactly 90 degrees, and the round
    # trip still closes on it because the inverse makes the same assumption.
    # Only a comparison against the devkit's own corner formula catches that,
    # which is what `test_kitti3d.py` does.
    axis_x, axis_y, axis_z = _axes_from_ry(ry, inverse)

    # The FULL rotation, not just its yaw. The camera is mounted at a slight
    # angle to the lidar on a real rig -- about a degree on the standard KITTI
    # setup -- so a box that is axis-aligned in the camera frame is genuinely
    # tilted in the sensor frame. Storing only the yaw would discard that and
    # make this conversion lossy in the direction that does not have to be:
    # carrying rotations a format cannot express is exactly why the contract
    # holds a quaternion.
    rotation = quaternion_from_matrix((
        (axis_x[0], axis_y[0], axis_z[0]),
        (axis_x[1], axis_y[1], axis_z[1]),
        (axis_x[2], axis_y[2], axis_z[2]),
    ))

    return to_client_spatial_object(
        "cuboid_3d", label, color,
        center=centre,
        size=[length, width, height],
        rotation=list(rotation),
        track_id=track_id)


def cuboid_to_kitti(obj: Dict[str, Any], reference_rt: Sequence[float]
                    ) -> Optional[Dict[str, Any]]:
    """
    A normalized spatial object as KITTI's 3D fields.

    Returns ``{"dimensions": [h, w, l], "location": [x, y, z],
    "rotation_y": ry, "alpha": a, "tilt": radians}``, or None for anything that
    is not a usable cuboid.

    ``tilt`` is how much pitch/roll the format could not carry. It is returned
    rather than logged so the caller can report the total honestly instead of
    the file quietly describing flat boxes that were not flat.
    """
    if not obj or obj.get("type") != "cuboid_3d":
        return None
    centre = obj.get("center")
    size = obj.get("size")
    if not centre or not size:
        return None
    length, width, height = (abs(float(v)) for v in size[:3])
    if length <= 0 or width <= 0 or height <= 0:
        return None

    from potato.media.calibration import invert_rt

    m = rotation_matrix(obj.get("rotation") or (0, 0, 0, 1))
    # The box's own +X (length) axis in the sensor frame is column 0.
    forward = (m[0][0], m[1][0], m[2][0])

    forward_cam = _rotate(reference_rt, forward)
    # Exact inverse of the (cos ry, 0, -sin ry) above; see the note there for
    # why this is not the (sin, 0, cos) form.
    rotation_y = math.atan2(-forward_cam[2], forward_cam[0])

    # How much rotation the format is about to throw away: the angle between
    # the box's actual orientation and the one a reader will reconstruct from
    # the single `ry` we are writing.
    #
    # Measured this way rather than as "how far the box's up-axis is from the
    # sensor's vertical", which is only the same thing for a Z-up sensor frame
    # and reports a spurious 90 degrees for any rig whose lidar is mounted
    # differently. This definition is rig-independent and is exactly zero for a
    # box that came from a KITTI file, which is the property that makes it
    # trustworthy.
    fitted = _axes_from_ry(rotation_y, invert_rt(reference_rt))
    actual = ((m[0][0], m[1][0], m[2][0]),
              (m[0][1], m[1][1], m[2][1]),
              (m[0][2], m[1][2], m[2][2]))
    tilt = _rotation_between(fitted, actual)

    cam_centre = _apply_rt(reference_rt, centre)
    # Back to the bottom face: camera +Y is down.
    cam_centre[1] += height / 2.0

    # Alpha is the observation angle: the yaw an observer would perceive,
    # which differs from rotation_y for anything off the optical axis.
    # Omitting it (writing 0, or -10) is common and makes the file unusable
    # for the KITTI benchmark's own orientation metric.
    alpha = rotation_y - math.atan2(cam_centre[0], cam_centre[2])
    alpha = (alpha + math.pi) % (2 * math.pi) - math.pi

    return {
        "dimensions": [height, width, length],
        "location": cam_centre,
        "rotation_y": (rotation_y + math.pi) % (2 * math.pi) - math.pi,
        "alpha": alpha,
        "tilt": tilt,
    }


def parse_kitti_3d_line(line: str) -> Optional[Tuple[str, List[float],
                                                     List[float], float]]:
    """
    ``(label, dimensions, location, rotation_y)`` from a KITTI label line.

    Returns None for a 2D-only line (fewer than 15 fields) or one whose 3D
    block holds the devkit's "unset" sentinels — ``-1`` dimensions and
    ``-1000`` location, which ``DontCare`` rows carry. Treating those as a real
    detection puts a zero-sized object at the camera origin.
    """
    fields = line.split()
    if len(fields) < 15:
        return None
    try:
        dimensions = [float(v) for v in fields[DIMENSIONS]]
        location = [float(v) for v in fields[LOCATION]]
        rotation_y = float(fields[ROTATION_Y])
    except ValueError:
        return None
    if any(v <= 0 for v in dimensions):
        return None
    if all(v <= -999 for v in location):
        return None
    return fields[0], dimensions, location, rotation_y


def format_kitti_3d_line(label: str, fields: Dict[str, Any], *,
                         bbox: Optional[Sequence[float]] = None,
                         truncated: float = 0.0, occluded: int = 0) -> str:
    """
    A full fifteen-field KITTI label line from :func:`cuboid_to_kitti` output.

    ``bbox`` is the 2D box in ``[x1, y1, x2, y2]`` pixels — the projection of
    the cuboid into the camera, which :mod:`potato.media.calibration` computes.
    Without it the 2D columns are written as the devkit's own zeros, which the
    benchmark ignores for 3D evaluation but which no 2D consumer should read as
    a detection.
    """
    box = list(bbox) if bbox else [0.0, 0.0, 0.0, 0.0]
    h, w, length = fields["dimensions"]
    x, y, z = fields["location"]
    return " ".join([
        label,
        f"{truncated:.2f}",
        str(int(occluded)),
        f"{fields['alpha']:.2f}",
        f"{box[0]:.2f}", f"{box[1]:.2f}", f"{box[2]:.2f}", f"{box[3]:.2f}",
        f"{h:.2f}", f"{w:.2f}", f"{length:.2f}",
        f"{x:.2f}", f"{y:.2f}", f"{z:.2f}",
        f"{fields['rotation_y']:.2f}",
    ])
