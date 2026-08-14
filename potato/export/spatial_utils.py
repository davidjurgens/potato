"""
Coordinate contract for 3D spatial annotations (client <-> exporter).

## Why this is a second contract rather than more cases in the first one

``cv_utils.normalize_annotation_object(obj, img_w, img_h)`` exists to turn
**normalized [0, 1] image coordinates into absolute pixels**. Every one of its
assumptions fails for a 3D box:

* there is no image to normalize against, and no meaningful extent to normalize
  by — a lidar sweep is unbounded in a way a photograph is not;
* the units are **metres in a sensor frame**, not pixels;
* the annotation carries an **orientation**, which no 2D primitive does.

Forcing 3D through that signature would mean passing dummy image dimensions and
a function whose name and docstring lie about what it does. So spatial
annotations get their own pair, mirroring the 2D one exactly in role:

    normalize_spatial_object()  parse what the client wrote
    to_client_spatial_object()  build what the client expects

One contract per coordinate space. The 2D contract comment at
``cv_utils.py:729`` points here, and this points back, so whoever finds one
finds the other.

## The client shape

Written by ``PointCloudAnnotationManager._serializeAnnotations()`` in
``potato/static/pointcloud/pc-viewer.js``:

    {"type": "cuboid_3d",   "label", "color", "track_id"?,
     "coordinates": {"center": [x, y, z],
                     "size":   [l, w, h],
                     "rotation": [qx, qy, qz, qw]}}
    {"type": "point_3d",    "label", "color", "coordinates": [x, y, z]}
    {"type": "polyline_3d", "label", "color", "coordinates": [[x, y, z], ...]}
    {"type": "segment_3d",  "label", "color", "indices": [i, ...]}

**Nothing here is normalized.** Coordinates are absolute, in the sensor frame,
in metres.

## Why rotation is a quaternion

KITTI stores a single yaw angle, and matching it would be simpler. nuScenes
stores quaternions, and any dataset with pitch or roll — drone, handheld,
indoor scan, anything not a car on a flat road — needs them. Storing yaw alone
would make those datasets unrepresentable, and the loss would be **silent**: a
tilted box would be written back flat with no warning.

So the storage format carries the full rotation, and the KITTI reader/writer
converts at its own boundary, where a format's limitation belongs. That
conversion is lossy in one direction and :func:`quaternion_to_yaw` says so.

## Why segment_3d stores indices

Per-point labels over a million-point cloud cannot round-trip as a coordinate
list — it would be larger than the cloud. Indices are stable because the served
cloud is a fixed decimation of the source (see ``potato/media/pointcloud.py``),
and the decimation is part of the cache key, so a given item always yields the
same points in the same order.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Annotation types this contract understands. Imported by the schema so the
#: valid-tool list exists in exactly one place (invariant 9: VALID_TOOLS was
#: duplicated across two modules and drifted).
SPATIAL_TYPES = ("cuboid_3d", "point_3d", "polyline_3d", "segment_3d")

#: Identity rotation, in the (x, y, z, w) order three.js uses.
IDENTITY_QUATERNION = (0.0, 0.0, 0.0, 1.0)


def _floats(raw: Any, count: int) -> Optional[List[float]]:
    """``count`` finite floats out of a sequence, or None."""
    if not isinstance(raw, (list, tuple)) or len(raw) < count:
        return None
    out: List[float] = []
    for value in raw[:count]:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        out.append(f)
    return out


def normalize_quaternion(raw: Any) -> Tuple[float, float, float, float]:
    """
    A unit quaternion (x, y, z, w), falling back to identity.

    Normalizing on read rather than trusting the input matters because a
    non-unit quaternion silently **scales** the box when it is converted to a
    rotation matrix — the annotation renders at the wrong size rather than
    failing, which is the hardest kind of wrong to notice.
    """
    values = _floats(raw, 4)
    if values is None:
        return IDENTITY_QUATERNION
    norm = math.sqrt(sum(v * v for v in values))
    if norm < 1e-12:
        return IDENTITY_QUATERNION
    return tuple(v / norm for v in values)  # type: ignore[return-value]


def yaw_to_quaternion(yaw: float) -> Tuple[float, float, float, float]:
    """Rotation about +Z by ``yaw`` radians, as (x, y, z, w)."""
    half = float(yaw) / 2.0
    return (0.0, 0.0, math.sin(half), math.cos(half))


def quaternion_to_yaw(quat: Sequence[float]) -> float:
    """
    The Z rotation of a quaternion, in radians.

    **Lossy by construction.** Pitch and roll are discarded; a box tilted out of
    the horizontal plane comes back flat. Only formats that cannot express a
    full rotation (KITTI) should call this, and their exporters are responsible
    for saying so.
    """
    x, y, z, w = normalize_quaternion(quat)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def normalize_spatial_object(obj: dict) -> Optional[dict]:
    """
    Parse one stored spatial annotation into a canonical dict.

    Counterpart to ``cv_utils.normalize_annotation_object``, for the sensor
    coordinate space. Unlike that function there is no unit conversion to do —
    the client already writes absolute metres — so the work here is validation
    and defaulting.

    Returns None when the object is not a usable spatial annotation, so callers
    can filter rather than branch on every field.

    Returns::

        {"type", "label", "color",
         "center": [x, y, z] | None,
         "size": [l, w, h] | None,
         "rotation": (qx, qy, qz, qw),
         "points": [[x, y, z], ...] | None,
         "indices": [int, ...] | None,
         "track_id": str | None,
         "warnings": [str]}
    """
    if not isinstance(obj, dict):
        return None

    obj_type = obj.get("type", "")
    if obj_type not in SPATIAL_TYPES:
        return None

    warnings: List[str] = []
    result: Dict[str, Any] = {
        "type": obj_type,
        "label": obj.get("label", ""),
        "color": obj.get("color", ""),
        "center": None,
        "size": None,
        "rotation": IDENTITY_QUATERNION,
        "points": None,
        "indices": None,
        "track_id": obj.get("track_id"),
        "warnings": warnings,
    }
    coords = obj.get("coordinates")

    if obj_type == "cuboid_3d":
        if not isinstance(coords, dict):
            return None
        center = _floats(coords.get("center"), 3)
        size = _floats(coords.get("size"), 3)
        if center is None or size is None:
            return None
        if any(s <= 0 for s in size):
            # A zero or negative extent is a degenerate box. Kept rather than
            # dropped, with a warning, because dropping it silently changes the
            # annotation count and every index after it.
            warnings.append(
                f"cuboid has a non-positive size {size}; it will not render")
        result["center"] = center
        result["size"] = [abs(s) for s in size]
        result["rotation"] = normalize_quaternion(coords.get("rotation"))

    elif obj_type == "point_3d":
        point = _floats(coords, 3)
        if point is None:
            return None
        result["center"] = point
        result["points"] = [point]

    elif obj_type == "polyline_3d":
        if not isinstance(coords, (list, tuple)):
            return None
        points = [p for p in (_floats(c, 3) for c in coords) if p is not None]
        if len(points) < 2:
            return None
        result["points"] = points

    elif obj_type == "segment_3d":
        raw = obj.get("indices")
        if not isinstance(raw, (list, tuple)):
            return None
        indices: List[int] = []
        for value in raw:
            try:
                i = int(value)
            except (TypeError, ValueError):
                continue
            if i >= 0:
                indices.append(i)
        if not indices:
            return None
        result["indices"] = indices

    return result


def to_client_spatial_object(obj_type: str, label: str, color: str = "", *,
                             center: Optional[Sequence[float]] = None,
                             size: Optional[Sequence[float]] = None,
                             rotation: Optional[Sequence[float]] = None,
                             yaw: Optional[float] = None,
                             points: Optional[Sequence[Sequence[float]]] = None,
                             indices: Optional[Sequence[int]] = None,
                             track_id: Optional[str] = None
                             ) -> Optional[dict]:
    """
    Build one spatial annotation in the shape the browser expects.

    Exact inverse of :func:`normalize_spatial_object`, and the only function
    that should synthesize spatial annotations for the client — the same rule
    that ``to_client_object`` carries for 2D, and for the same reason: every
    importer that hand-built the client shape got it subtly wrong.

    ``yaw`` is accepted as an alternative to ``rotation`` so KITTI's importer
    does not have to build a quaternion itself. Passing both is an error rather
    than a silent precedence rule, because a caller that supplies both almost
    certainly believes one of them is being used and cannot tell which.
    """
    if obj_type not in SPATIAL_TYPES:
        return None
    if rotation is not None and yaw is not None:
        raise ValueError(
            "pass either rotation= or yaw=, not both: they describe the same "
            "field and there is no way for the caller to tell which won")

    obj: Dict[str, Any] = {"type": obj_type, "label": label, "color": color}
    if track_id is not None:
        obj["track_id"] = track_id

    if obj_type == "cuboid_3d":
        c = _floats(list(center or []), 3)
        s = _floats(list(size or []), 3)
        if c is None or s is None:
            return None
        if yaw is not None:
            quat = yaw_to_quaternion(yaw)
        else:
            quat = normalize_quaternion(list(rotation or IDENTITY_QUATERNION))
        obj["coordinates"] = {
            "center": c,
            "size": [abs(v) for v in s],
            "rotation": list(quat),
        }
        return obj

    if obj_type == "point_3d":
        c = _floats(list(center or []), 3)
        if c is None and points:
            c = _floats(list(points[0]), 3)
        if c is None:
            return None
        obj["coordinates"] = c
        return obj

    if obj_type == "polyline_3d":
        cleaned = [p for p in (_floats(list(p), 3) for p in (points or []))
                   if p is not None]
        if len(cleaned) < 2:
            return None
        obj["coordinates"] = cleaned
        return obj

    if obj_type == "segment_3d":
        cleaned_idx = [int(i) for i in (indices or []) if int(i) >= 0]
        if not cleaned_idx:
            return None
        obj["indices"] = cleaned_idx
        return obj

    return None


# ---------------------------------------------------------------------------
# Geometry helpers used by exporters and by agreement
# ---------------------------------------------------------------------------

def rotation_matrix(rotation: Sequence[float]) -> Tuple[Tuple[float, ...], ...]:
    """
    The 3x3 rotation matrix of a quaternion, row-major.

    Shared rather than inlined because :func:`cuboid_corners` and the camera
    calibration in ``potato/media/calibration.py`` both need it, and a rotation
    matrix written out twice is a sign error waiting to happen: the wrong sign
    on one off-diagonal term still produces a valid-looking box, just mirrored,
    which reads as an annotator mistake rather than a bug.
    """
    qx, qy, qz, qw = normalize_quaternion(rotation)
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    return (
        (1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)),
        (2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)),
        (2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)),
    )


def quaternion_from_matrix(m: Sequence[Sequence[float]]
                           ) -> Tuple[float, float, float, float]:
    """
    The unit quaternion (x, y, z, w) of a 3x3 rotation matrix.

    The inverse of :func:`rotation_matrix`, needed wherever a rotation arrives
    as a frame change rather than as an angle -- importing a box whose
    orientation comes from composing two calibration transforms, for instance.

    Uses the largest-diagonal branch rather than the single ``w`` formula,
    which divides by a quantity approaching zero for rotations near 180 degrees
    and loses most of its precision well before that.
    """
    m00, m01, m02 = (float(v) for v in m[0][:3])
    m10, m11, m12 = (float(v) for v in m[1][:3])
    m20, m21, m22 = (float(v) for v in m[2][:3])
    trace = m00 + m11 + m22

    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        quat = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        quat = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        quat = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        quat = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)

    return normalize_quaternion(list(quat))


def cuboid_corners(center: Sequence[float], size: Sequence[float],
                   rotation: Sequence[float]) -> List[List[float]]:
    """
    The eight corners of an oriented box, in world coordinates.

    Order is the one KITTI and nuScenes visualisations both use: the four
    corners of the -Z face first (in +X, +Y winding), then the +Z face. Callers
    that draw edges depend on this order, so it is fixed rather than incidental.
    """
    cx, cy, cz = (float(v) for v in center[:3])
    lx, ly, lz = (abs(float(v)) / 2.0 for v in size[:3])
    m = rotation_matrix(rotation)

    corners = []
    for sz in (-lz, lz):
        for sx, sy in ((-lx, -ly), (lx, -ly), (lx, ly), (-lx, ly)):
            corners.append([
                cx + m[0][0] * sx + m[0][1] * sy + m[0][2] * sz,
                cy + m[1][0] * sx + m[1][1] * sy + m[1][2] * sz,
                cz + m[2][0] * sx + m[2][1] * sy + m[2][2] * sz,
            ])
    return corners


def axis_aligned_bounds(obj: dict) -> Optional[List[List[float]]]:
    """
    ``[[minx, miny, minz], [maxx, maxy, maxz]]`` for a normalized object.

    Used as a cheap pre-filter before any exact 3D IoU: two boxes whose
    axis-aligned bounds do not overlap cannot intersect, and rejecting those
    pairs first is what keeps agreement over a large scene affordable.
    """
    if obj.get("type") == "cuboid_3d" and obj.get("center") and obj.get("size"):
        corners = cuboid_corners(obj["center"], obj["size"], obj["rotation"])
    elif obj.get("points"):
        corners = obj["points"]
    else:
        return None
    lo = [min(c[i] for c in corners) for i in range(3)]
    hi = [max(c[i] for c in corners) for i in range(3)]
    return [lo, hi]
