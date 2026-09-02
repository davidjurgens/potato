"""
Distance functions over spatial and temporal annotations.

This is the layer that lets the existing agreement machinery reach geometry.
``alpha.krippendorff_alpha`` already forwards a ``metric_fn`` to simpledorff, so
generalizing alpha to masks and boxes needs a difference function, not a new
coefficient -- and the same functions serve adjudication routing, IoU-tolerant
gold standards, and consensus checks.

Everything here is pure: no Potato state, no I/O. Inputs are the canonical
absolute-pixel dicts ``cv_utils.normalize_annotation_object`` produces, so this
module and the exporters agree on what a shape *is* by construction.

Three separable questions, deliberately not collapsed into one number:

* **detection**  - did two annotators mark the same object at all?
* **localization** - given they did, do the boundaries agree?
* **classification** - did they give it the same label?

Reporting a single score hides which of the three is failing, and the three have
different remedies (better instructions, better tooling, a clearer codebook).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bounding boxes
# ---------------------------------------------------------------------------

def iou_bbox(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Intersection over union of two ``[x, y, width, height]`` boxes.

    Returns 0.0 for degenerate (zero-area) boxes rather than dividing by zero;
    a box with no area cannot agree with anything.
    """
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0

    ax, ay, aw, ah = (float(v) for v in a[:4])
    bx, by, bw, bh = (float(v) for v in b[:4])
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0

    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = ix * iy
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def containment_bbox(inner: Sequence[float], outer: Sequence[float]) -> float:
    """
    How much of ``inner`` lies inside ``outer``: intersection over inner's area.

    Asymmetric, unlike IoU, and that asymmetry is the point. IoU conflates "is
    this thing inside that thing?" with "are these two things the same size?",
    so a small object sitting inside a much larger box scores low -- lower the
    looser the box is.

    Found by running the VLM critique on a deliberately oversized box: the box
    plainly contained the car, but IoU was 0.12 *because* it was three times too
    big, so "you missed this car" was reported about a car that was annotated.
    Containment answers that question directly and is 1.0 there.

    Returns 0.0 when ``inner`` has no area, since nothing can be contained.
    """
    if not inner or not outer or len(inner) < 4 or len(outer) < 4:
        return 0.0

    ix0, iy0, iw, ih = (float(v) for v in inner[:4])
    ox0, oy0, ow, oh = (float(v) for v in outer[:4])
    if iw <= 0 or ih <= 0 or ow <= 0 or oh <= 0:
        return 0.0

    ix = max(0.0, min(ix0 + iw, ox0 + ow) - max(ix0, ox0))
    iy = max(0.0, min(iy0 + ih, oy0 + oh) - max(iy0, oy0))
    return (ix * iy) / (iw * ih)


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------

def iou_mask(rle_a: dict, rle_b: dict) -> float:
    """
    IoU of two Potato RLE masks.

    Computed by walking the runs rather than decoding both masks to dense
    arrays: a pair of 4000x3000 masks is 24M Python ints per comparison, and an
    agreement report does this for every annotator pair on every instance.
    """
    if not rle_a or not rle_b:
        return 0.0

    spans_a = _rle_true_spans(rle_a)
    spans_b = _rle_true_spans(rle_b)
    if not spans_a or not spans_b:
        return 0.0

    area_a = sum(end - start for start, end in spans_a)
    area_b = sum(end - start for start, end in spans_b)
    if area_a == 0 or area_b == 0:
        return 0.0

    intersection = _span_intersection(spans_a, spans_b)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _rle_true_spans(rle: dict) -> List[Tuple[int, int]]:
    """
    Half-open ``[start, end)`` index spans of the set pixels in a Potato RLE.

    Potato RLE alternates run lengths starting with 0-pixels, row-major.
    """
    counts = (rle or {}).get("counts") or []
    spans: List[Tuple[int, int]] = []
    pos = 0
    value = 0
    for count in counts:
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        if value == 1 and count:
            spans.append((pos, pos + count))
        pos += count
        value = 1 - value
    return spans


def _span_intersection(a: List[Tuple[int, int]], b: List[Tuple[int, int]]) -> int:
    """Total overlap between two sorted lists of half-open spans."""
    total = 0
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if end > start:
            total += end - start
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


# ---------------------------------------------------------------------------
# Polygons
# ---------------------------------------------------------------------------

def iou_polygon(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]],
                samples: int = 128) -> float:
    """
    IoU of two polygons, given as ``[[x, y], ...]`` in absolute pixels.

    Uses shapely when available; otherwise rasterizes onto a shared grid of at
    most ``samples`` cells per side. The raster path is approximate, and says
    so -- it is a fallback so that a deployment without shapely still gets a
    usable number, not a claim of exactness.
    """
    if not a or not b or len(a) < 3 or len(b) < 3:
        return 0.0

    try:
        from shapely.geometry import Polygon  # type: ignore

        pa = Polygon([(float(p[0]), float(p[1])) for p in a])
        pb = Polygon([(float(p[0]), float(p[1])) for p in b])
        if not pa.is_valid:
            pa = pa.buffer(0)
        if not pb.is_valid:
            pb = pb.buffer(0)
        if pa.is_empty or pb.is_empty:
            return 0.0
        union = pa.union(pb).area
        return pa.intersection(pb).area / union if union > 0 else 0.0
    except ImportError:
        return _iou_polygon_raster(a, b, samples)


def _iou_polygon_raster(a, b, samples: int) -> float:
    xs = [float(p[0]) for p in a] + [float(p[0]) for p in b]
    ys = [float(p[1]) for p in a] + [float(p[1]) for p in b]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if max_x <= min_x or max_y <= min_y:
        return 0.0

    step_x = (max_x - min_x) / samples
    step_y = (max_y - min_y) / samples
    inter = union = 0
    for row in range(samples):
        py = min_y + (row + 0.5) * step_y
        for col in range(samples):
            px = min_x + (col + 0.5) * step_x
            in_a = _point_in_polygon(px, py, a)
            in_b = _point_in_polygon(px, py, b)
            if in_a and in_b:
                inter += 1
            if in_a or in_b:
                union += 1
    return inter / union if union else 0.0


def _point_in_polygon(x: float, y: float, poly: Sequence[Sequence[float]]) -> bool:
    """Ray casting; boundary handling is not exact, which the caller accepts."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = float(poly[i][0]), float(poly[i][1])
        x2, y2 = float(poly[(i + 1) % n][0]), float(poly[(i + 1) % n][1])
        if (y1 > y) != (y2 > y):
            x_at = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_at:
                inside = not inside
    return inside


# ---------------------------------------------------------------------------
# Open paths and points
# ---------------------------------------------------------------------------

def boundary_f1(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]],
                tolerance: float = 5.0, dims: int = 2) -> float:
    """
    Symmetric F1 of two point sequences within ``tolerance`` units.

    For polylines and open paths, where IoU is undefined (no interior) and
    where boundary *precision* is the thing under study. Also the right measure
    for large masks, whose IoU saturates: two annotators can differ by many
    pixels of boundary and still score 0.98.

    ``dims`` is explicit rather than inferred from the points' length. 2D
    points arrive in several shapes -- ``[x, y]`` from a polygon and
    ``[x, y, visibility]`` from a keypoint set -- so measuring "however many
    numbers are there" would quietly fold a visibility flag into a distance.
    Pass ``dims=3`` for genuinely spatial paths, where using the default would
    be equally quiet the other way: two polylines one above the other would
    score a perfect 1.0.
    """
    if not a or not b:
        return 0.0

    matched_a = sum(1 for p in a if _min_distance(p, b, dims) <= tolerance)
    matched_b = sum(1 for p in b if _min_distance(p, a, dims) <= tolerance)
    precision = matched_a / len(a)
    recall = matched_b / len(b)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _min_distance(point: Sequence[float], others: Sequence[Sequence[float]],
                  dims: int = 2) -> float:
    coords = [float(point[i]) for i in range(dims)]
    best = float("inf")
    for other in others:
        total = 0.0
        for i in range(dims):
            delta = coords[i] - float(other[i])
            total += delta * delta
        if total < best:
            best = total
    return math.sqrt(best)


#: COCO's per-keypoint standard deviations, for the 17-point person skeleton.
COCO_OKS_SIGMAS = [
    .026, .025, .025, .035, .035, .079, .079, .072, .072,
    .062, .062, .107, .107, .087, .087, .089, .089,
]


def oks(kps_a: Sequence[Sequence[float]], kps_b: Sequence[Sequence[float]],
        area: float, sigmas: Optional[Sequence[float]] = None,
        vis_a: Optional[Sequence[int]] = None,
        vis_b: Optional[Sequence[int]] = None) -> float:
    """
    Object Keypoint Similarity — the COCO-standard keypoint agreement measure.

    Each keypoint is ``[x, y]`` or ``[x, y, visibility]``; visibility may also
    be supplied as parallel ``vis_a`` / ``vis_b`` lists, which is the form
    ``normalize_annotation_object`` produces. Points invisible to either
    annotator are skipped rather than counted as disagreement: one annotator
    not marking an occluded joint is a different phenomenon from the two
    disagreeing about where it is.
    """
    if not kps_a or not kps_b or area <= 0:
        return 0.0

    sigmas = list(sigmas or COCO_OKS_SIGMAS)
    scores = []
    for i, (pa, pb) in enumerate(zip(kps_a, kps_b)):
        va = vis_a[i] if vis_a is not None and i < len(vis_a) else (
            pa[2] if len(pa) > 2 else 2)
        vb = vis_b[i] if vis_b is not None and i < len(vis_b) else (
            pb[2] if len(pb) > 2 else 2)
        if float(va) <= 0 or float(vb) <= 0:
            continue
        sigma = sigmas[i] if i < len(sigmas) else (sigmas[-1] if sigmas else 0.05)
        d2 = (float(pa[0]) - float(pb[0])) ** 2 + (float(pa[1]) - float(pb[1])) ** 2
        scores.append(math.exp(-d2 / (2 * area * (2 * sigma) ** 2)))

    return sum(scores) / len(scores) if scores else 0.0


# ---------------------------------------------------------------------------
# Oriented 3D boxes
#
# Exact for ANY rotation, not just yaw. The tempting shortcut is
# bird's-eye-view IoU times vertical overlap, which is exact when both boxes
# are level and silently wrong when either is not -- and the storage contract
# carries full quaternions precisely so that drone, handheld and indoor-scan
# data are representable. An agreement number that quietly degrades on exactly
# the datasets the contract was widened for would undo that decision.
#
# The method: a box is six half-spaces, so the intersection of two boxes is the
# convex region satisfying twelve. Its vertices are among the intersections of
# every triple of those planes, and its volume follows from the divergence
# theorem over the resulting faces. 12 choose 3 is 220 tiny linear solves,
# which is affordable because `axis_aligned_overlap` rejects non-overlapping
# pairs first and that is the overwhelming majority.
# ---------------------------------------------------------------------------

def _box_planes(center: Sequence[float], size: Sequence[float],
                rotation: Sequence[float]) -> List[Tuple[Tuple[float, float, float], float]]:
    """
    A box as six ``(normal, offset)`` half-spaces, inside being ``n·x <= d``.

    Imported from the contract module rather than re-deriving the rotation
    matrix: a sign error in a second copy produces a mirrored box that still
    looks like a box.
    """
    from potato.export.spatial_utils import rotation_matrix

    m = rotation_matrix(rotation)
    c = [float(v) for v in center[:3]]
    h = [abs(float(v)) / 2.0 for v in size[:3]]

    planes = []
    for axis in range(3):
        # Column `axis` of the rotation matrix is that box axis in world space.
        u = (m[0][axis], m[1][axis], m[2][axis])
        centre_along = u[0] * c[0] + u[1] * c[1] + u[2] * c[2]
        planes.append((u, centre_along + h[axis]))
        planes.append(((-u[0], -u[1], -u[2]), -centre_along + h[axis]))
    return planes


def _intersect_three_planes(p, q, r):
    """The single point on all three planes, or None if they do not meet in one."""
    (a1, b1, c1), d1 = p
    (a2, b2, c2), d2 = q
    (a3, b3, c3), d3 = r
    det = (a1 * (b2 * c3 - b3 * c2)
           - b1 * (a2 * c3 - a3 * c2)
           + c1 * (a2 * b3 - a3 * b2))
    if abs(det) < 1e-12:
        return None
    x = (d1 * (b2 * c3 - b3 * c2)
         - b1 * (d2 * c3 - d3 * c2)
         + c1 * (d2 * b3 - d3 * b2)) / det
    y = (a1 * (d2 * c3 - d3 * c2)
         - d1 * (a2 * c3 - a3 * c2)
         + c1 * (a2 * d3 - a3 * d2)) / det
    z = (a1 * (b2 * d3 - b3 * d2)
         - b1 * (a2 * d3 - a3 * d2)
         + d1 * (a2 * b3 - a3 * b2)) / det
    return (x, y, z)


def _convex_volume(planes, vertices, tol: float) -> float:
    """
    Volume of the convex body bounded by ``planes`` with corners ``vertices``.

    By the divergence theorem, ``V = (1/3) Σ hᵢ Aᵢ`` over the faces, where
    ``hᵢ`` is the distance from an interior point to face ``i``. The centroid
    of the vertices is interior for a convex body, which is what makes the
    per-face distances all positive and the sum a volume rather than a signed
    quantity.
    """
    if len(vertices) < 4:
        return 0.0
    n = float(len(vertices))
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n
    cz = sum(v[2] for v in vertices) / n

    total = 0.0
    for normal, offset in _distinct_planes(planes):
        on_face = [v for v in vertices
                   if abs(normal[0] * v[0] + normal[1] * v[1]
                          + normal[2] * v[2] - offset) <= tol]
        if len(on_face) < 3:
            continue

        # An in-plane basis, from whichever axis is least parallel to the
        # normal -- picking a fixed axis would be degenerate for one face
        # orientation in six.
        pick = min(range(3), key=lambda i: abs(normal[i]))
        seed = [0.0, 0.0, 0.0]
        seed[pick] = 1.0
        ux = _normalize3(_cross(normal, seed))
        if ux is None:
            continue
        uy = _normalize3(_cross(normal, ux))
        if uy is None:
            continue

        fx = sum(v[0] for v in on_face) / len(on_face)
        fy = sum(v[1] for v in on_face) / len(on_face)
        fz = sum(v[2] for v in on_face) / len(on_face)
        projected = []
        for v in on_face:
            dx, dy, dz = v[0] - fx, v[1] - fy, v[2] - fz
            projected.append((dx * ux[0] + dy * ux[1] + dz * ux[2],
                              dx * uy[0] + dy * uy[1] + dz * uy[2]))
        # Angular order around the face centroid: the shoelace formula needs a
        # traversal of the boundary, and the vertices arrive unordered.
        projected.sort(key=lambda p: math.atan2(p[1], p[0]))

        area = 0.0
        for i, (x0, y0) in enumerate(projected):
            x1, y1 = projected[(i + 1) % len(projected)]
            area += x0 * y1 - x1 * y0
        area = abs(area) / 2.0
        if area <= 0:
            continue

        height = abs(offset - (normal[0] * cx + normal[1] * cy
                               + normal[2] * cz))
        total += area * height
    return total / 3.0


def _distinct_planes(planes):
    """
    Drop coincident half-spaces before summing faces.

    Two boxes that share a face -- identical boxes, or any pair aligned on one
    axis -- contribute that plane twice, and the divergence sum then counts the
    face twice. For two identical 2x2x2 boxes that yields a shared volume of
    16 instead of 8, which makes the union ``8 + 8 - 16 = 0`` and the IoU of a
    box with itself **zero**. Perfect agreement reported as total disagreement
    is the worst possible failure for an agreement statistic, so this is
    deduplicated rather than assumed not to happen.
    """
    distinct = []
    for normal, offset in planes:
        duplicate = False
        for other_normal, other_offset in distinct:
            if (abs(normal[0] - other_normal[0]) < 1e-9
                    and abs(normal[1] - other_normal[1]) < 1e-9
                    and abs(normal[2] - other_normal[2]) < 1e-9
                    and abs(offset - other_offset) < 1e-9):
                duplicate = True
                break
        if not duplicate:
            distinct.append((normal, offset))
    return distinct


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _normalize3(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length < 1e-12:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def _cuboid_aabb(center, size, rotation):
    from potato.export.spatial_utils import cuboid_corners

    corners = cuboid_corners(center, size, rotation)
    return ([min(c[i] for c in corners) for i in range(3)],
            [max(c[i] for c in corners) for i in range(3)])


def cuboid_intersection_volume(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """
    Volume shared by two oriented boxes, in cubic metres.

    ``a`` and ``b`` are the dicts ``normalize_spatial_object`` returns.
    """
    if not a or not b or not a.get("size") or not b.get("size"):
        return 0.0

    lo_a, hi_a = _cuboid_aabb(a["center"], a["size"], a["rotation"])
    lo_b, hi_b = _cuboid_aabb(b["center"], b["size"], b["rotation"])
    # Cheap reject: boxes whose axis-aligned bounds miss cannot intersect, and
    # in a real scene almost every pair is this case.
    for axis in range(3):
        if hi_a[axis] <= lo_b[axis] or hi_b[axis] <= lo_a[axis]:
            return 0.0

    planes = (_box_planes(a["center"], a["size"], a["rotation"])
              + _box_planes(b["center"], b["size"], b["rotation"]))

    # Tolerances are relative to the boxes because "how close is on the same
    # plane" is a length and therefore has units. Measured, a fixed epsilon
    # also holds up across nine orders of magnitude of box size here, so this
    # is dimensional hygiene rather than a fix for an observed failure -- it
    # keeps a future change of units or coordinate origin from quietly
    # mattering.
    scale = max(max(abs(float(v)) for v in a["size"]),
                max(abs(float(v)) for v in b["size"]), 1e-6)
    tol = scale * 1e-9

    vertices = []
    count = len(planes)
    for i in range(count):
        for j in range(i + 1, count):
            for k in range(j + 1, count):
                point = _intersect_three_planes(planes[i], planes[j], planes[k])
                if point is None:
                    continue
                inside = True
                for normal, offset in planes:
                    if (normal[0] * point[0] + normal[1] * point[1]
                            + normal[2] * point[2]) > offset + scale * 1e-9:
                        inside = False
                        break
                if inside:
                    vertices.append(point)

    if len(vertices) < 4:
        return 0.0

    # Deduplicate: a corner of the intersection typically lies on more than
    # three planes, so the same point is found several times and would be
    # counted repeatedly when ordering a face.
    unique = []
    merge_tol = scale * 1e-7
    for point in vertices:
        if not any(abs(point[0] - u[0]) < merge_tol
                   and abs(point[1] - u[1]) < merge_tol
                   and abs(point[2] - u[2]) < merge_tol for u in unique):
            unique.append(point)

    return _convex_volume(planes, unique, max(tol, merge_tol))


def iou_cuboid_3d(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """
    Volumetric IoU of two oriented 3D boxes, exact for any rotation.

    The localization measure for cuboid agreement: given that two annotators
    marked the same object, do their boxes describe the same volume?
    """
    if not a or not b or not a.get("size") or not b.get("size"):
        return 0.0
    vol_a = abs(a["size"][0] * a["size"][1] * a["size"][2])
    vol_b = abs(b["size"][0] * b["size"][1] * b["size"][2])
    if vol_a <= 0 or vol_b <= 0:
        # A degenerate box is kept by the contract (with a warning) rather than
        # dropped, so it reaches here; it has no volume to share.
        return 0.0

    intersection = cuboid_intersection_volume(a, b)
    union = vol_a + vol_b - intersection
    if union <= 0:
        return 0.0
    # Clamped: the plane arithmetic can overshoot by a rounding error on
    # near-identical boxes, and an IoU of 1.0000000002 breaks any caller that
    # treats the range as closed.
    return max(0.0, min(1.0, intersection / union))


def spatial_similarity(obj_a: Dict[str, Any], obj_b: Dict[str, Any]) -> float:
    """
    Similarity in [0, 1] between two 3D annotations.

    Takes the dicts ``spatial_utils.normalize_spatial_object`` returns, which
    are a different shape from the 2D ones -- absolute metres with an
    orientation, rather than pixels. :func:`similarity` dispatches here on
    type, so callers do not have to know which contract an object came from.
    """
    if not obj_a or not obj_b:
        return 0.0
    type_a, type_b = obj_a.get("type"), obj_b.get("type")
    if type_a != type_b:
        return 0.0

    if type_a == "cuboid_3d":
        return iou_cuboid_3d(obj_a, obj_b)

    if type_a == "point_3d":
        pa = (obj_a.get("points") or [obj_a.get("center")])[0]
        pb = (obj_b.get("points") or [obj_b.get("center")])[0]
        if not pa or not pb:
            return 0.0
        distance = math.sqrt(sum((float(pa[i]) - float(pb[i])) ** 2
                                 for i in range(3)))
        # Half a metre of tolerance: two annotators clicking the same lamppost
        # in a sparse cloud will not agree to the centimetre, and treating
        # that as disagreement would make the number useless. Linear falloff
        # to zero at 2 m.
        return max(0.0, 1.0 - distance / 2.0)

    if type_a == "polyline_3d":
        # dims=3, or two paths at different heights would score a perfect 1.0.
        # Half a metre of tolerance, in metres rather than the pixel default.
        return boundary_f1(obj_a.get("points") or [],
                           obj_b.get("points") or [], tolerance=0.5, dims=3)

    if type_a == "segment_3d":
        set_a = set(obj_a.get("indices") or [])
        set_b = set(obj_b.get("indices") or [])
        if not set_a or not set_b:
            return 0.0
        # Jaccard over point indices, which IS IoU when the unit is a point.
        return len(set_a & set_b) / len(set_a | set_b)

    return 0.0


# ---------------------------------------------------------------------------
# Temporal
# ---------------------------------------------------------------------------

def temporal_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """IoU of two ``[start, end]`` intervals — video and audio segments."""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return 0.0
    a_start, a_end = float(a[0]), float(a[1])
    b_start, b_end = float(b[0]), float(b[1])
    if a_end <= a_start or b_end <= b_start:
        return 0.0

    intersection = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = (a_end - a_start) + (b_end - b_start) - intersection
    return intersection / union if union > 0 else 0.0


def temporal_boundary_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Mean absolute difference of two intervals' start and end, in seconds.

    Complements ``temporal_iou``, which saturates on long segments: two
    annotators can disagree by a second on a thirty-second segment and still
    score 0.97. Nothing on the market reports whether temporal boundaries
    agree, and this is the measure that would.
    """
    if not a or not b or len(a) < 2 or len(b) < 2:
        return float("inf")
    return (abs(float(a[0]) - float(b[0])) + abs(float(a[1]) - float(b[1]))) / 2


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def similarity(obj_a: Dict[str, Any], obj_b: Dict[str, Any]) -> float:
    """
    Similarity in [0, 1] between two canonical annotation objects.

    Objects are the dicts ``cv_utils.normalize_annotation_object`` returns.
    Different geometry types never match: a mask and a box may cover the same
    pixels, but treating them as interchangeable would hide a real
    disagreement about how the object should be represented.
    """
    if not obj_a or not obj_b:
        return 0.0

    type_a = obj_a.get("type")
    type_b = obj_b.get("type")
    if type_a != type_b:
        return 0.0

    from potato.export.spatial_utils import SPATIAL_TYPES

    if type_a in SPATIAL_TYPES:
        # 3D objects carry a different canonical shape -- metres and an
        # orientation, not pixels -- so they route to their own measures.
        # Without this they fall through to the bbox default below, which
        # reads a "bbox" key a spatial object does not have and scores every
        # pair of cuboids 0.0: a confident report of total disagreement.
        return spatial_similarity(obj_a, obj_b)

    if type_a == "mask":
        return iou_mask(obj_a.get("rle") or {}, obj_b.get("rle") or {})

    if type_a == "keypoint_set":
        # OKS, COCO's own keypoint metric: per-point distance scaled by the
        # object's size and by a per-joint tolerance, because annotators agree
        # far more tightly on an eye than on a hip. IoU is meaningless here --
        # a point has no area.
        box = obj_a.get("bbox") or [0, 0, 0, 0]
        area = float(box[2] or 0) * float(box[3] or 0)
        return oks(obj_a.get("points") or [], obj_b.get("points") or [],
                   area=area,
                   vis_a=obj_a.get("visibility"),
                   vis_b=obj_b.get("visibility"))

    if type_a == "cuboid_2d":
        # Compare the visible front faces. The back face is a depth estimate
        # the annotator infers rather than sees, so scoring it equally would
        # punish disagreement about something neither of them can observe.
        return iou_polygon(obj_a.get("front") or [], obj_b.get("front") or [])

    if type_a in ("polygon", "freeform", "polyline", "ellipse"):
        points_a = obj_a.get("points") or []
        points_b = obj_b.get("points") or []
        if type_a in ("freeform", "polyline"):
            # An open path has no interior for IoU to measure, so agreement is
            # about whether the two traces follow the same course.
            return boundary_f1(points_a, points_b)
        # Ellipses arrive here with a polygon approximation already attached by
        # normalize_annotation_object, so area IoU works with no extra maths.
        return iou_polygon(points_a, points_b)

    if type_a == "landmark":
        pa = (obj_a.get("points") or [[0, 0]])[0]
        pb = (obj_b.get("points") or [[0, 0]])[0]
        # Scale tolerance to the objects' own size when we know it.
        box = obj_a.get("bbox") or [0, 0, 0, 0]
        scale = max(1.0, math.hypot(float(box[2] or 0), float(box[3] or 0)))
        distance = math.hypot(float(pa[0]) - float(pb[0]), float(pa[1]) - float(pb[1]))
        return max(0.0, 1.0 - distance / (scale * 10))

    return iou_bbox(obj_a.get("bbox") or [], obj_b.get("bbox") or [])


def temporal_similarity(seg_a: Dict[str, Any], seg_b: Dict[str, Any]) -> float:
    """
    Similarity in [0, 1] between two ``{"start", "end", "label"}`` segments.

    The temporal counterpart of :func:`similarity`, so audio and video segments
    can flow through the same matching and agreement machinery as 2D shapes.
    A text span, an audio segment and a video segment are the same object with
    different arity.
    """
    if not seg_a or not seg_b:
        return 0.0
    return temporal_iou(
        [seg_a.get("start", 0.0), seg_a.get("end", 0.0)],
        [seg_b.get("start", 0.0), seg_b.get("end", 0.0)],
    )


def delta_geometric(obj_a: Dict[str, Any], obj_b: Dict[str, Any]) -> float:
    """
    Difference function for Krippendorff's alpha: ``1 - similarity``.

    Pass to ``krippendorff_alpha(long_format, level=delta_geometric)`` once the
    coefficient accepts a callable.
    """
    return 1.0 - similarity(obj_a, obj_b)


# ---------------------------------------------------------------------------
# Instance matching
# ---------------------------------------------------------------------------

def match_instances(objects_a: List[Dict[str, Any]], objects_b: List[Dict[str, Any]],
                    threshold: float = 0.5,
                    sim_fn=None,
                    ) -> Tuple[List[Tuple[int, int, float]], List[int], List[int]]:
    """
    Pair up two annotators' objects on one item by maximum similarity.

    Returns ``(matches, unmatched_a, unmatched_b)`` where each match is
    ``(index_a, index_b, similarity)``. Matching is what separates the three
    questions: pairs feed localization and classification agreement, while the
    unmatched are exactly the detection disagreements.

    ``sim_fn`` defaults to :func:`similarity` (2D geometry); pass
    :func:`temporal_similarity` to match audio/video segments with the same
    algorithm.

    Uses the Hungarian algorithm when scipy is available so the assignment is
    globally optimal; otherwise falls back to greedy best-first, which can be
    wrong when several objects overlap heavily.
    """
    if not objects_a or not objects_b:
        return [], list(range(len(objects_a))), list(range(len(objects_b)))

    score_of = sim_fn or similarity
    scores = [[score_of(a, b) for b in objects_b] for a in objects_a]

    pairs: List[Tuple[int, int]] = []
    try:
        from scipy.optimize import linear_sum_assignment  # type: ignore

        cost = [[1.0 - s for s in row] for row in scores]
        rows, cols = linear_sum_assignment(cost)
        pairs = list(zip(rows.tolist(), cols.tolist()))
    except ImportError:
        used_b = set()
        order = sorted(
            ((scores[i][j], i, j) for i in range(len(objects_a))
             for j in range(len(objects_b))),
            reverse=True,
        )
        used_a = set()
        for _score, i, j in order:
            if i in used_a or j in used_b:
                continue
            used_a.add(i)
            used_b.add(j)
            pairs.append((i, j))

    matches = [(i, j, scores[i][j]) for i, j in pairs if scores[i][j] >= threshold]
    matched_a = {i for i, _, _ in matches}
    matched_b = {j for _, j, _ in matches}
    return (
        matches,
        [i for i in range(len(objects_a)) if i not in matched_a],
        [j for j in range(len(objects_b)) if j not in matched_b],
    )
