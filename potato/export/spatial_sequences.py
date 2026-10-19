"""
Point-cloud sequences: tracks of 3D objects across frames.

A sequence item holds a list of clouds, one per frame. The annotation is the
same flat list of objects a single cloud stores, each with two more keys:
``frame`` (0-based) and ``track_id``. Only keyframes are stored. Between two
keyframes of a track the object is interpolated -- centre and size linearly,
rotation by quaternion slerp -- and outside its first and last keyframe the
track is absent. This module is the one place that rule lives; the viewer
(pc-viewer.js) implements the same interpolation for display.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: KITTI's occlusion levels, for an `occluded` attribute that uses names.
OCCLUSION_LEVELS = {"none": 0, "fully visible": 0, "partly": 1, "partial": 1,
                    "partly occluded": 1, "largely": 2, "heavy": 2,
                    "largely occluded": 2, "unknown": 3}


def sequence_frames(value: Any) -> Optional[List[str]]:
    """The frame paths of a sequence item's cloud field, or None for one cloud."""
    if isinstance(value, dict):
        value = value.get("frames")
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, str) for v in value):
        return [v.strip() for v in value]
    return None


def _canonical(obj: dict) -> Optional[dict]:
    from potato.export.spatial_utils import normalize_spatial_object
    return normalize_spatial_object(obj)


def tracks(objects: Iterable[dict]) -> Dict[str, List[Tuple[int, dict]]]:
    """``{track_id: [(frame, canonical object), ...]}`` sorted by frame.

    Objects without a frame or a track id are not part of any track.
    """
    out: Dict[str, List[Tuple[int, dict]]] = {}
    for obj in objects or []:
        if not isinstance(obj, dict) or obj.get("track_id") in (None, ""):
            continue
        try:
            frame = int(obj.get("frame"))
        except (TypeError, ValueError):
            continue
        canonical = _canonical(obj)
        if canonical is None:
            continue
        canonical = dict(canonical)
        canonical["attributes"] = obj.get("attributes") or {}
        out.setdefault(str(obj["track_id"]), []).append((frame, canonical))
    for keyframes in out.values():
        keyframes.sort(key=lambda pair: pair[0])
    return out


def _lerp(a: Sequence[float], b: Sequence[float], t: float) -> List[float]:
    return [x + (y - x) * t for x, y in zip(a, b)]


def slerp(q0: Sequence[float], q1: Sequence[float], t: float) -> Tuple[float, ...]:
    """Spherical interpolation between two unit quaternions (x, y, z, w)."""
    q0 = [float(v) for v in q0]
    q1 = [float(v) for v in q1]
    dot = sum(a * b for a, b in zip(q0, q1))
    if dot < 0:                       # the short way round
        q1, dot = [-v for v in q1], -dot
    if dot > 0.9995:                  # nearly equal: lerp and renormalize
        out = _lerp(q0, q1, t)
    else:
        theta = math.acos(max(-1.0, min(1.0, dot)))
        s0 = math.sin((1 - t) * theta) / math.sin(theta)
        s1 = math.sin(t * theta) / math.sin(theta)
        out = [s0 * a + s1 * b for a, b in zip(q0, q1)]
    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return tuple(v / norm for v in out)


def object_at(keyframes: List[Tuple[int, dict]], frame: int) -> Optional[dict]:
    """The track's object at ``frame``: a keyframe, an interpolation, or None."""
    if not keyframes or frame < keyframes[0][0] or frame > keyframes[-1][0]:
        return None
    for index, (f, obj) in enumerate(keyframes):
        if f == frame:
            return dict(obj, frame=frame, interpolated=False)
        if f > frame:
            f0, a = keyframes[index - 1]
            f1, b = f, obj
            t = (frame - f0) / (f1 - f0)
            out = dict(a, frame=frame, interpolated=True)
            if a.get("center") and b.get("center"):
                out["center"] = _lerp(a["center"], b["center"], t)
            if a.get("size") and b.get("size"):
                out["size"] = _lerp(a["size"], b["size"], t)
            if a.get("rotation") and b.get("rotation"):
                out["rotation"] = slerp(a["rotation"], b["rotation"], t)
            if a.get("points") and b.get("points") and len(a["points"]) == len(b["points"]):
                out["points"] = [_lerp(p, q, t) for p, q in zip(a["points"], b["points"])]
            return out
    return None


def dense_frames(objects: Iterable[dict], n_frames: int) -> Dict[int, List[dict]]:
    """Every frame's objects, interpolated between keyframes, each with track_id."""
    by_track = tracks(objects)
    out: Dict[int, List[dict]] = {f: [] for f in range(n_frames)}
    for track_id, keyframes in by_track.items():
        first, last = keyframes[0][0], keyframes[-1][0]
        for frame in range(max(0, first), min(n_frames - 1, last) + 1):
            obj = object_at(keyframes, frame)
            if obj is not None:
                obj["track_id"] = track_id
                out[frame].append(obj)
    return out


def _occlusion(attributes: Dict[str, Any]) -> int:
    value = attributes.get("occluded", attributes.get("occlusion"))
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return int(value)
    return OCCLUSION_LEVELS.get(str(value).strip().lower(), 0) if value is not None else 0


#: Categorical truncation values, as KITTI's tracking codes.
TRUNCATION_LEVELS = {"none": 0, "no": 0, "false": 0, "not truncated": 0,
                     "partly": 1, "partial": 1, "partially": 1, "yes": 1, "true": 1,
                     "fully": 2, "full": 2, "largely": 2, "heavy": 2}

#: What a categorical "partly" (or true) writes in the object format when the
#: image edge cuts nothing off: the format wants a fraction and the label gives
#: none, so it is set at KITTI's limit for the Hard difficulty.
PARTLY_TRUNCATED = 0.5


def truncation_attribute(attributes: Dict[str, Any]):
    """``(code, fraction, unrecognized)`` from a truncated/truncation attribute.

    ``code`` is KITTI's tracking code (0, 1, 2) and ``fraction`` a share when
    the attribute was numeric; both None when unset. ``unrecognized`` is a
    value that could not be read, which the caller reports.
    """
    value = attributes.get("truncated", attributes.get("truncation"))
    if value is None or value == "":
        return None, None, None
    if isinstance(value, bool):
        return (1 if value else 0), None, None
    if isinstance(value, int) and value in (0, 1, 2):
        return value, None, None
    if isinstance(value, (int, float)):
        fraction = max(0.0, min(1.0, float(value)))
        return (0 if fraction <= 0 else 2 if fraction >= 1 else 1), fraction, None
    code = TRUNCATION_LEVELS.get(str(value).strip().lower())
    if code is None:
        return None, None, value
    return code, None, None


def _truncation(attributes: Dict[str, Any], measured: float = 0.0) -> float:
    """KITTI's object-format truncation.

    The share of the projected box outside the image is the floor; an
    attribute can only raise it, so `truncated: false` (a bool attribute's
    starting value) cannot hide a box the image edge cuts in half.
    """
    measured = max(0.0, min(1.0, measured))
    code, fraction, _unknown = truncation_attribute(attributes)
    if fraction is not None:
        return max(measured, fraction)
    if code == 2:
        return 1.0
    if code == 1:
        return max(measured, PARTLY_TRUNCATED)
    return measured


def tracking_truncation(attributes: Dict[str, Any], measured: float = 0.0) -> int:
    """KITTI's tracking-format truncation: 0 none, 1 partly, 2 fully.

    The larger of the measured code and the attribute's.
    """
    measured_code = 0 if measured <= 0 else 2 if measured >= 1 else 1
    code, _fraction, _unknown = truncation_attribute(attributes)
    return max(measured_code, code or 0)


def kitti_tracking_lines(objects: Iterable[dict], n_frames: int,
                         reference_rt: Sequence[float], camera=None,
                         image_size: Optional[Tuple[int, int]] = None,
                         ) -> Tuple[List[str], Dict[str, int]]:
    """KITTI tracking label lines for one sequence, dense over every frame.

    ``frame track_id type truncated occluded alpha x1 y1 x2 y2 h w l x y z ry``.
    KITTI track ids are integers; Potato's are mapped in order of first
    appearance, and the mapping is returned with the lines. Only cuboids are
    written. The 2D box is the cuboid projected through ``camera`` and clipped
    to ``image_size`` (see kitti3d.projected_box); without a camera it is
    zeros, which KITTI evaluation ignores. Truncation and occlusion come from
    `truncated` / `occluded` attributes when the track has them, and
    truncation otherwise from how much of the box the image edge cuts off.
    """
    from potato.export.kitti3d import cuboid_to_kitti, format_kitti_3d_line, projected_box

    width, height = image_size or (None, None)
    ids: Dict[str, int] = {}
    lines: List[str] = []
    for frame, objects_at in sorted(dense_frames(objects, n_frames).items()):
        for obj in sorted(objects_at, key=lambda o: str(o["track_id"])):
            fields = cuboid_to_kitti(obj, reference_rt)
            if fields is None:
                continue
            box, cut = projected_box(obj, camera, width, height) if camera else (None, 0.0)
            number = ids.setdefault(obj["track_id"], len(ids))
            attributes = obj.get("attributes") or {}
            row = format_kitti_3d_line(str(obj.get("label") or "DontCare"), fields, bbox=box,
                                       truncated=tracking_truncation(attributes, cut),
                                       occluded=_occlusion(attributes))
            lines.append(f"{frame} {number} {row}")
    return lines, ids
