"""
Camera calibration, and projecting 3D annotations into 2D images.

## Why this exists

Placing an oriented box in a lidar sweep by eye is close to guessing. A car at
40 m is a few dozen returns; whether the box is tight, whether it is the right
length, and whether it is rotated correctly are all far easier to judge in the
camera image that saw the same object. So the annotator **edits in 3D and
verifies in 2D**, and this module is what makes the second half possible: it
turns a cuboid in the sensor frame into pixels in every camera that can see it.

## The one thing that goes silently wrong

A point *behind* the camera has negative depth, and dividing by it produces a
perfectly plausible pixel coordinate -- mirrored through the principal point.
Project a box straddling the image plane without handling this and you get a
box turned inside out across the frame: nonsense that looks like an annotation
mistake rather than a projection bug.

Everything here therefore culls or clips against a near plane:

* :func:`project_point` returns ``None`` behind the camera rather than a
  coordinate;
* :func:`project_segment` clips the segment at the near plane and returns the
  visible part, so a box that is half in front of the camera draws its half
  correctly instead of vanishing or wrapping.

## Coordinate frames

``Camera.rt`` maps the **sensor frame** (the frame the annotations are in --
metres, the same frame ``potato/media/pointcloud.py`` serves points in) to the
**camera frame** (+Z forward, +X right, +Y down, the OpenCV convention every
intrinsic matrix here assumes). Nothing in Potato's storage is in a camera
frame; the conversion happens here and at the format boundaries.

## Accepted input shapes

Deliberately several, because researchers arrive with what their dataset ships:

1. **KITTI** ``calib/xxxxxx.txt`` -- ``P0..P3``, ``R0_rect``,
   ``Tr_velo_to_cam``. The most common lidar calibration on disk.
2. **Native JSON** -- a ``cameras`` list with explicit intrinsics and
   extrinsics. What nuScenes-style and custom rigs map onto.
3. **A bare intrinsics matrix** with no extrinsics, which means "the sensor
   frame is the camera frame". True for RGB-D and monocular depth data.

A format we cannot read raises :class:`CalibrationError` with what was missing,
never a partial calibration -- a calibration that is quietly wrong puts boxes in
the wrong place in the verification view, which is worse than having no
verification view.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.export.spatial_utils import rotation_matrix

logger = logging.getLogger(__name__)

#: Depth below which a point is treated as behind the camera. Not zero: a point
#: at exactly z = 0 projects to infinity, and one at z = 1e-9 projects to a
#: coordinate in the millions, which is worse than dropping it because it
#: stretches any bounding box computed from the projection.
NEAR_PLANE = 0.05

#: Rows of a KITTI calib file that are 3x4 camera projection matrices.
_KITTI_PROJECTIONS = ("P0", "P1", "P2", "P3")

#: Human names for the KITTI cameras, so the verification panel is labelled
#: with something more useful than "P2".
_KITTI_CAMERA_NAMES = {
    "P0": "Left grayscale (cam 0)",
    "P1": "Right grayscale (cam 1)",
    "P2": "Left colour (cam 2)",
    "P3": "Right colour (cam 3)",
}

#: KITTI's own image directory for each camera, used to find the image that
#: goes with a calibration when the item does not name one explicitly.
_KITTI_IMAGE_DIRS = {
    "P0": "image_0", "P1": "image_1", "P2": "image_2", "P3": "image_3",
}


class CalibrationError(Exception):
    """A calibration could not be read. The message says what was missing."""


@dataclass
class Camera:
    """
    One camera: how it sees, and where it is relative to the sensor.

    ``k`` is the 3x3 intrinsic matrix (row-major, 9 floats) and ``rt`` the 3x4
    sensor-to-camera rigid transform (row-major, 12 floats). Kept as separate
    matrices rather than a single 3x4 projection because lens distortion is
    applied *between* them, and folding them together would make a distorted
    camera unrepresentable.
    """

    name: str
    k: Tuple[float, ...]
    rt: Tuple[float, ...]
    width: Optional[int] = None
    height: Optional[int] = None
    image: Optional[str] = None
    #: Brown-Conrady ``[k1, k2, p1, p2, k3]``. All zeros for a rectified rig,
    #: which KITTI and nuScenes both are.
    distortion: Tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        """The shape the browser receives. Matches ``pc-calibration.js``."""
        return {
            "name": self.name,
            "k": list(self.k),
            "rt": list(self.rt),
            "width": self.width,
            "height": self.height,
            "image": self.image,
            "distortion": list(self.distortion),
        }


@dataclass
class Calibration:
    """A rig: every camera that saw the scene, plus anything we could not read."""

    cameras: List[Camera] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: Sensor to **rectified reference camera** (KITTI's "cam 0 rect"), as a
    #: 3x4. Distinct from any ``Camera.rt``, which additionally carries that
    #: camera's stereo baseline: KITTI's 3D label coordinates are in the
    #: reference frame, so projecting a label through a camera's own rt would
    #: shift every box by the baseline. None for rigs with no such notion.
    reference_rt: Optional[Tuple[float, ...]] = None

    def camera(self, name: str) -> Optional[Camera]:
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cameras": [c.to_dict() for c in self.cameras],
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Small matrix helpers
#
# Pure Python rather than numpy: these are 3x3 and 3x4, they run once per item
# rather than per point, and `potato/media/` is on the request path for every
# image in a project. Importing numpy to invert a 3x3 would be the same
# boot-weight mistake the AI endpoints were refactored out of.
# ---------------------------------------------------------------------------

def _mat3_inverse(m: Sequence[float]) -> Tuple[float, ...]:
    """Inverse of a row-major 3x3, by cofactors."""
    a, b, c, d, e, f, g, h, i = (float(v) for v in m)
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise CalibrationError(
            "the intrinsic matrix is singular (determinant 0), so it cannot "
            "describe a camera; check for a row of zeros")
    inv = 1.0 / det
    return (
        (e * i - f * h) * inv, (c * h - b * i) * inv, (b * f - c * e) * inv,
        (f * g - d * i) * inv, (a * i - c * g) * inv, (c * d - a * f) * inv,
        (d * h - e * g) * inv, (b * g - a * h) * inv, (a * e - b * d) * inv,
    )


def _mat3_apply(m: Sequence[float], v: Sequence[float]) -> Tuple[float, float, float]:
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def compose_rt(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    """
    ``a @ b`` for two 3x4 rigid transforms, as a 3x4.

    Reading order is the usual one: the result applies ``b`` first. KITTI needs
    exactly this to get from velodyne to a rectified camera --
    ``P_rect ∘ R0_rect ∘ Tr_velo_to_cam`` -- and composing in the other order
    puts every box somewhere plausible but wrong.
    """
    out: List[float] = []
    for r in range(3):
        for c in range(4):
            total = 0.0
            for k in range(3):
                total += a[r * 4 + k] * b[k * 4 + c]
            if c == 3:
                total += a[r * 4 + 3]
            out.append(total)
    return tuple(out)


def invert_rt(rt: Sequence[float]) -> Tuple[float, ...]:
    """
    Inverse of a 3x4 rigid transform, using ``R⁻¹ = Rᵀ``.

    Only valid for a *rigid* transform. A general inverse would silently
    succeed on a matrix carrying scale and return something that is not a pose,
    so the rotation block is checked for orthonormality first.
    """
    r = (rt[0], rt[1], rt[2], rt[4], rt[5], rt[6], rt[8], rt[9], rt[10])
    for col in range(3):
        norm = math.sqrt(sum(r[row * 3 + col] ** 2 for row in range(3)))
        if abs(norm - 1.0) > 1e-3:
            raise CalibrationError(
                f"extrinsics are not a rigid transform (column {col} of the "
                f"rotation has length {norm:.4f}, expected 1.0); a scaled or "
                f"skewed matrix cannot be inverted as a pose")
    t = (rt[3], rt[7], rt[11])
    # Rᵀ, then -Rᵀ·t.
    rti = (r[0], r[3], r[6], r[1], r[4], r[7], r[2], r[5], r[8])
    ti = _mat3_apply(rti, t)
    return (rti[0], rti[1], rti[2], -ti[0],
            rti[3], rti[4], rti[5], -ti[1],
            rti[6], rti[7], rti[8], -ti[2])


IDENTITY_RT: Tuple[float, ...] = (1.0, 0.0, 0.0, 0.0,
                                  0.0, 1.0, 0.0, 0.0,
                                  0.0, 0.0, 1.0, 0.0)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def to_camera_frame(cam: Camera, point: Sequence[float]) -> Tuple[float, float, float]:
    """A sensor-frame point in the camera's own frame (+Z forward)."""
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    rt = cam.rt
    return (rt[0] * x + rt[1] * y + rt[2] * z + rt[3],
            rt[4] * x + rt[5] * y + rt[6] * z + rt[7],
            rt[8] * x + rt[9] * y + rt[10] * z + rt[11])


def _project_camera_point(cam: Camera, pc: Sequence[float]
                          ) -> Optional[Tuple[float, float]]:
    """Pixel coordinates of a point already in the camera frame, or None."""
    # `<`, not `<=`: :func:`project_segment` clips to *exactly* NEAR_PLANE, so
    # a strict test here rejects every clipped point and silently deletes the
    # one case clipping exists to handle.
    if pc[2] < NEAR_PLANE:
        return None
    xn = pc[0] / pc[2]
    yn = pc[1] / pc[2]

    k1, k2, p1, p2, k3 = cam.distortion
    if k1 or k2 or p1 or p2 or k3:
        r2 = xn * xn + yn * yn
        radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        xd = xn * radial + 2.0 * p1 * xn * yn + p2 * (r2 + 2.0 * xn * xn)
        yd = yn * radial + p1 * (r2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn
        xn, yn = xd, yd

    k = cam.k
    return (k[0] * xn + k[1] * yn + k[2],
            k[3] * xn + k[4] * yn + k[5])


def project_point(cam: Camera, point: Sequence[float]
                  ) -> Optional[Tuple[float, float]]:
    """
    Pixel coordinates of a sensor-frame point, or ``None`` behind the camera.

    ``None`` rather than a coordinate is the whole point: see the module
    docstring. Callers must not substitute a fallback pixel.
    """
    return _project_camera_point(cam, to_camera_frame(cam, point))


def project_segment(cam: Camera, a: Sequence[float], b: Sequence[float]
                    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    The visible part of a sensor-frame line segment, in pixels.

    Clipped against the near plane, so a box edge running from in front of the
    camera to behind it draws up to the plane instead of wrapping across the
    frame. Returns ``None`` when the whole segment is behind the camera.
    """
    pa = to_camera_frame(cam, a)
    pb = to_camera_frame(cam, b)
    za, zb = pa[2], pb[2]

    if za < NEAR_PLANE and zb < NEAR_PLANE:
        return None
    if za < NEAR_PLANE or zb < NEAR_PLANE:
        # Exactly one end is behind: move it onto the near plane.
        t = (NEAR_PLANE - za) / (zb - za)
        cut = (pa[0] + (pb[0] - pa[0]) * t,
               pa[1] + (pb[1] - pa[1]) * t,
               NEAR_PLANE)
        if za <= NEAR_PLANE:
            pa = cut
        else:
            pb = cut

    ua = _project_camera_point(cam, pa)
    ub = _project_camera_point(cam, pb)
    if ua is None or ub is None:
        return None
    return (ua, ub)


#: Cuboid edges as index pairs into ``spatial_utils.cuboid_corners`` order.
#: The same twelve pairs ``pc-viewer.js`` draws in 3D, so the wireframe in the
#: camera panel is the same wireframe as in the viewport.
BOX_EDGES: Tuple[Tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


def project_cuboid(cam: Camera, center: Sequence[float], size: Sequence[float],
                   rotation: Sequence[float]) -> Dict[str, Any]:
    """
    A cuboid as drawable 2D geometry for one camera.

    Returns ``{"edges": [[(u,v),(u,v)], ...], "bbox": [x0,y0,x1,y1] | None,
    "visible": bool}``.

    ``bbox`` is computed from the corners that are genuinely in front of the
    camera. It is what a KITTI-style 2D box column wants, and what decides
    whether the object is worth showing in this panel at all.
    """
    from potato.export.spatial_utils import cuboid_corners

    corners = cuboid_corners(center, size, rotation)
    edges: List[List[Tuple[float, float]]] = []
    for i, j in BOX_EDGES:
        seg = project_segment(cam, corners[i], corners[j])
        if seg is not None:
            edges.append([seg[0], seg[1]])

    front = [p for p in (project_point(cam, c) for c in corners) if p is not None]
    bbox = None
    if front:
        xs = [p[0] for p in front]
        ys = [p[1] for p in front]
        bbox = [min(xs), min(ys), max(xs), max(ys)]

    return {"edges": edges, "bbox": bbox, "visible": bool(edges)}


def clip_bbox_to_image(bbox: Sequence[float], width: Optional[int],
                       height: Optional[int]) -> Optional[List[float]]:
    """
    A projected box clipped to the image, or ``None`` if it falls outside.

    KITTI's 2D boxes are image-clipped, so an exporter that writes raw
    projected coordinates emits negative pixels and boxes wider than the frame,
    which some downstream loaders reject and others silently accept.
    """
    if not bbox or width is None or height is None:
        return list(bbox) if bbox else None
    x0 = max(0.0, min(float(bbox[0]), float(width)))
    y0 = max(0.0, min(float(bbox[1]), float(height)))
    x1 = max(0.0, min(float(bbox[2]), float(width)))
    y1 = max(0.0, min(float(bbox[3]), float(height)))
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return [x0, y0, x1, y1]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _numbers(text: str) -> List[float]:
    out = []
    for token in re.split(r"[\s,]+", text.strip()):
        if not token:
            continue
        try:
            out.append(float(token))
        except ValueError:
            return []
    return out


def parse_kitti_calib(text: str, *, images: Optional[Dict[str, str]] = None,
                      cameras: Sequence[str] = ("P2",)) -> Calibration:
    """
    A KITTI ``calib/xxxxxx.txt`` (or ``calib_cam_to_cam`` style) file.

    KITTI's chain is ``x_image = P_rect ⋅ R0_rect ⋅ Tr_velo_to_cam ⋅ x_velo``.
    ``P_rect`` is ``K ⋅ [I | t]`` where ``t`` is the rectified stereo baseline,
    **not** zero for cameras 1-3, so dropping it puts the right-hand cameras'
    boxes off by the baseline. It is recovered exactly here as ``K⁻¹ ⋅ P[:,3]``
    rather than assumed zero.

    ``cameras`` selects which ``P`` rows to build; the default is ``P2``, the
    left colour camera almost every KITTI benchmark uses.
    """
    rows: Dict[str, List[float]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        values = _numbers(rest)
        if values:
            rows[key.strip()] = values

    if not any(p in rows for p in _KITTI_PROJECTIONS):
        raise CalibrationError(
            "this does not look like a KITTI calibration file: none of "
            f"{', '.join(_KITTI_PROJECTIONS)} is present. Found: "
            f"{', '.join(sorted(rows)) or '(nothing)'}")

    warnings: List[str] = []

    # R0_rect is 3x3 in the object-detection calib files and absent in some
    # odometry ones, where the cameras are already rectified.
    r0 = rows.get("R0_rect") or rows.get("R_rect") or rows.get("R0")
    if r0 and len(r0) >= 9:
        r0_rt = (r0[0], r0[1], r0[2], 0.0,
                 r0[3], r0[4], r0[5], 0.0,
                 r0[6], r0[7], r0[8], 0.0)
    else:
        r0_rt = IDENTITY_RT
        if r0:
            warnings.append(
                "R0_rect had fewer than 9 values and was ignored; boxes may be "
                "rotated slightly relative to the image")

    velo_to_cam = rows.get("Tr_velo_to_cam") or rows.get("Tr_velo_cam")
    if velo_to_cam and len(velo_to_cam) >= 12:
        velo_rt = tuple(velo_to_cam[:12])
    else:
        velo_rt = IDENTITY_RT
        warnings.append(
            "no Tr_velo_to_cam in this calibration, so the lidar frame is "
            "assumed to be the camera frame; projected boxes will be wrong if "
            "it is not")

    base = compose_rt(r0_rt, velo_rt)
    images = images or {}
    built: List[Camera] = []

    for key in cameras:
        p = rows.get(key)
        if not p or len(p) < 12:
            warnings.append(f"{key} is missing from this calibration file")
            continue
        k = (p[0], p[1], p[2], p[4], p[5], p[6], p[8], p[9], p[10])
        # P = K ⋅ [I | t]  ⇒  t = K⁻¹ ⋅ P[:, 3]. Exact, not a factorization.
        t = _mat3_apply(_mat3_inverse(k), (p[3], p[7], p[11]))
        rect_rt = (1.0, 0.0, 0.0, t[0],
                   0.0, 1.0, 0.0, t[1],
                   0.0, 0.0, 1.0, t[2])
        built.append(Camera(
            name=_KITTI_CAMERA_NAMES.get(key, key),
            k=k,
            rt=compose_rt(rect_rt, base),
            image=images.get(key) or images.get(_KITTI_IMAGE_DIRS.get(key, "")),
        ))

    if not built:
        raise CalibrationError(
            f"none of the requested cameras ({', '.join(cameras)}) is in this "
            f"calibration file; it has {', '.join(sorted(rows))}")
    return Calibration(cameras=built, warnings=warnings, reference_rt=base)


def _intrinsics_from(raw: Any) -> Tuple[float, ...]:
    """A 3x3 intrinsic matrix from any of the shapes datasets ship."""
    if isinstance(raw, (list, tuple)):
        flat = [float(v) for row in raw for v in
                (row if isinstance(row, (list, tuple)) else [row])]
        if len(flat) == 9:
            return tuple(flat)
        if len(flat) == 12:                      # a 3x4 P; drop the translation
            return (flat[0], flat[1], flat[2],
                    flat[4], flat[5], flat[6],
                    flat[8], flat[9], flat[10])
        raise CalibrationError(
            f"intrinsics must be 3x3 or 3x4, got {len(flat)} numbers")

    if isinstance(raw, dict):
        if "matrix" in raw or "K" in raw or "P" in raw:
            return _intrinsics_from(raw.get("matrix") or raw.get("K")
                                    or raw.get("P"))
        try:
            fx = float(raw["fx"])
            fy = float(raw["fy"])
            cx = float(raw["cx"])
            cy = float(raw["cy"])
        except (KeyError, TypeError, ValueError):
            raise CalibrationError(
                "intrinsics need either a 3x3 'matrix' or all of fx, fy, cx, "
                f"cy; got keys {sorted(raw)}")
        skew = float(raw.get("skew", 0.0))
        return (fx, skew, cx, 0.0, fy, cy, 0.0, 0.0, 1.0)

    raise CalibrationError(f"intrinsics must be a matrix or an object, got "
                           f"{type(raw).__name__}")


def _extrinsics_from(raw: Any) -> Tuple[float, ...]:
    """A 3x4 sensor-to-camera transform from any of the shapes datasets ship."""
    if raw is None:
        return IDENTITY_RT

    if isinstance(raw, (list, tuple)):
        flat = [float(v) for row in raw for v in
                (row if isinstance(row, (list, tuple)) else [row])]
        if len(flat) == 12:
            return tuple(flat)
        if len(flat) == 16:                      # 4x4; the last row is [0001]
            return tuple(flat[:12])
        raise CalibrationError(
            f"extrinsics must be 3x4 or 4x4, got {len(flat)} numbers")

    if isinstance(raw, dict):
        if "matrix" in raw:
            return _extrinsics_from(raw["matrix"])
        translation = raw.get("translation") or raw.get("t") or [0.0, 0.0, 0.0]
        rotation = raw.get("rotation") or raw.get("R") or raw.get("quaternion")
        if rotation is None:
            m = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        elif isinstance(rotation, (list, tuple)) and len(rotation) == 4:
            m = rotation_matrix(rotation)
        else:
            flat = [float(v) for row in rotation for v in
                    (row if isinstance(row, (list, tuple)) else [row])]
            if len(flat) != 9:
                raise CalibrationError(
                    "extrinsic rotation must be a quaternion (4) or a 3x3 "
                    f"matrix (9), got {len(flat)} numbers")
            m = ((flat[0], flat[1], flat[2]),
                 (flat[3], flat[4], flat[5]),
                 (flat[6], flat[7], flat[8]))
        t = [float(v) for v in translation[:3]]
        return (m[0][0], m[0][1], m[0][2], t[0],
                m[1][0], m[1][1], m[1][2], t[1],
                m[2][0], m[2][1], m[2][2], t[2])

    raise CalibrationError(f"extrinsics must be a matrix or an object, got "
                           f"{type(raw).__name__}")


def parse_camera_dict(raw: Dict[str, Any], index: int = 0) -> Camera:
    """One camera from the native JSON shape."""
    if not isinstance(raw, dict):
        raise CalibrationError(
            f"camera {index} must be an object, got {type(raw).__name__}")

    intrinsics = (raw.get("intrinsics") if "intrinsics" in raw
                  else raw.get("K") or raw.get("camera_intrinsic"))
    if intrinsics is None:
        raise CalibrationError(
            f"camera {index} ('{raw.get('name', index)}') has no intrinsics; "
            f"add an 'intrinsics' object with fx, fy, cx, cy or a 3x3 matrix")

    extrinsics = raw.get("extrinsics")
    if extrinsics is None and ("rotation" in raw or "translation" in raw):
        # nuScenes' calibrated_sensor puts rotation/translation at the top
        # level, so accept that spelling rather than making the caller reshape.
        extrinsics = {"rotation": raw.get("rotation"),
                      "translation": raw.get("translation")}

    distortion = raw.get("distortion") or raw.get("D") or []
    dist = [float(v) for v in list(distortion)[:5]]
    dist += [0.0] * (5 - len(dist))

    return Camera(
        name=str(raw.get("name") or raw.get("channel") or f"camera {index + 1}"),
        k=_intrinsics_from(intrinsics),
        rt=_extrinsics_from(extrinsics),
        width=int(raw["width"]) if raw.get("width") else None,
        height=int(raw["height"]) if raw.get("height") else None,
        image=raw.get("image") or raw.get("filename") or raw.get("file_name"),
        distortion=tuple(dist),  # type: ignore[arg-type]
    )


def parse_calibration(raw: Any, *, base_dir: Optional[str] = None,
                      resolve=None) -> Calibration:
    """
    Read a calibration from whatever the item field holds.

    Accepts:

    * a **path string** -- ``.txt`` is read as KITTI, ``.json`` as native;
    * a **dict with ``cameras``** -- the native shape;
    * a **dict with a ``file`` key** -- a path plus an ``images`` mapping, which
      is how a KITTI item names both its calibration and its image;
    * a **dict with KITTI ``P`` rows** -- the same content inline.

    ``base_dir`` resolves relative paths. ``resolve`` overrides that with a
    caller-supplied function, and **the web route must pass one**: these paths
    come out of a project's data file and are handed straight to ``open()``, so
    without the media-directory containment guard this is an arbitrary-file-read
    primitive. It is passed in rather than imported so that this module stays
    usable from the CLI and the importers, which have no request context.

    Raises :class:`CalibrationError` rather than returning something partial.
    """
    if raw is None or raw == "":
        raise CalibrationError("no calibration was provided")

    if isinstance(raw, str):
        return _from_path(raw, base_dir=base_dir, resolve=resolve)

    if not isinstance(raw, dict):
        raise CalibrationError(
            f"calibration must be a path or an object, got "
            f"{type(raw).__name__}")

    if "file" in raw or "path" in raw:
        path = raw.get("file") or raw.get("path")
        images = raw.get("images") or {}
        cameras = raw.get("cameras")
        selected = tuple(cameras) if isinstance(cameras, (list, tuple)) \
            and all(isinstance(c, str) for c in cameras) else ("P2",)
        return _from_path(str(path), base_dir=base_dir, images=images,
                          kitti_cameras=selected, resolve=resolve)

    if isinstance(raw.get("cameras"), (list, tuple)):
        cams = [parse_camera_dict(c, i)
                for i, c in enumerate(raw["cameras"])]
        if not cams:
            raise CalibrationError("'cameras' is empty")
        return Calibration(cameras=cams)

    if any(p in raw for p in _KITTI_PROJECTIONS):
        text = "\n".join(
            f"{key}: {' '.join(str(v) for v in value)}"
            for key, value in raw.items()
            if isinstance(value, (list, tuple)))
        return parse_kitti_calib(text, images=raw.get("images") or {})

    # A single camera written flat, which is what a monocular rig looks like.
    return Calibration(cameras=[parse_camera_dict(raw)])


def _from_path(path: str, *, base_dir: Optional[str] = None,
               images: Optional[Dict[str, str]] = None,
               kitti_cameras: Sequence[str] = ("P2",),
               resolve=None) -> Calibration:
    if resolve is not None:
        target = resolve(path)
        if target is None:
            # The caller's containment guard refused it. The message stays
            # vague on purpose: confirming whether a path outside the media
            # directory exists is itself information.
            raise CalibrationError(
                f"calibration path is not inside the project's media "
                f"directory: {path}")
        resolved = Path(target)
    else:
        resolved = Path(path)
        if base_dir and not resolved.is_absolute():
            resolved = Path(base_dir) / resolved

    if not resolved.is_file():
        raise CalibrationError(f"calibration file not found: {path}")

    text = resolved.read_text(encoding="utf-8", errors="replace")
    if resolved.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise CalibrationError(
                f"{resolved.name} is not valid JSON: {exc}") from exc
        # `resolve` is carried through: a JSON calibration can name another
        # file, and the guard has to apply at every hop rather than only the
        # first.
        return parse_calibration(data, base_dir=str(resolved.parent),
                                 resolve=resolve)
    return parse_kitti_calib(text, images=images, cameras=kitti_cameras)
