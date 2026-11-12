"""
Scoring a model's grounding against a person's.

Everything here takes annotations in the **client contract** shape defined at
``potato/export/cv_utils.py`` — normalized ``coordinates`` for shapes, absolute
RLE for masks — so a prediction loaded from a benchmark and a region drawn by an
annotator go through the same code and cannot be scored by two slightly
different definitions of "the same box".

## Why pointing is not grounding with a small box

A point has no area. Every IoU against it is 0, so scoring points the way boxes
are scored reports total failure for a model that is pointing perfectly. The
question a point answers is "is it *in* the thing", which is a hit rate over
regions, and the two numbers are not comparable — a 0.8 point-in-mask rate and
a 0.8 grounding accuracy at IoU 0.5 mean different things and belong in
different columns.

## Why "not present" cannot be inferred

An expression with no region might mean the annotator judged nothing to match
it, or might mean they never got to it. Those support opposite conclusions
about a model that also produced nothing — a correct refusal versus no evidence
at all — so the absent case is read from an explicit list and everything else
is excluded rather than assumed.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence


class GroundingError(RuntimeError):
    """Raised with a message the caller can show verbatim."""


#: Thresholds reported by default. 0.5 is the convention almost every
#: referring-expression paper quotes; the others are there because a single
#: threshold hides whether a model is nearly right or nowhere near, in exactly
#: the way a single matching tolerance does for break-points.
DEFAULT_IOU_THRESHOLDS = (0.25, 0.5, 0.75, 0.9)


#: The image size regions are normalized against when comparing. Grounding
#: coordinates are already in [0, 1], and `similarity` works on the canonical
#: absolute-pixel objects `normalize_annotation_object` produces, so
#: normalizing against a 1x1 image makes "pixels" and "fractions" the same
#: number and the comparison exact.
#:
#: This conversion is not optional and was not obvious: passing raw client
#: objects to `similarity` returns **0.0 for every pair**, because it reads a
#: `bbox` key the client shape does not have. That is a confident report of
#: total disagreement, and it is the same failure the coordinate contract at
#: `cv_utils.py:729` was written to end. Never call `similarity` on a client
#: object.
_UNIT = 1.0


def region_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """
    Overlap between two client-contract annotation objects, 0..1.

    Normalizes both to the canonical form first, then delegates to
    ``iaa.geometry.similarity`` — which already knows every shape in the
    contract, including masks, polygons, ellipses and keypoint sets.
    Reimplementing IoU here would give grounding its own definition of overlap,
    and the first time the two disagreed the difference would be blamed on the
    model.
    """
    from potato.export.cv_utils import normalize_annotation_object
    from potato.server_utils.iaa import geometry

    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    canonical_a = normalize_annotation_object(a, _UNIT, _UNIT)
    canonical_b = normalize_annotation_object(b, _UNIT, _UNIT)
    if not canonical_a or not canonical_b:
        return 0.0
    return geometry.similarity(canonical_a, canonical_b)


def region_center(region: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """
    A region's centre in normalized coordinates, or None.

    Used to turn a ground-truth box into something a pointing model can be
    scored against when no mask is available. It is a fallback and a poor one —
    the centre of a box around a person standing behind a chair may be the
    chair — so callers that have a mask should use it.
    """
    if not isinstance(region, dict):
        return None
    kind = str(region.get("type") or "")
    coordinates = region.get("coordinates")

    if kind == "landmark" and isinstance(coordinates, dict):
        return {"x": float(coordinates.get("x", 0.0)),
                "y": float(coordinates.get("y", 0.0))}
    if kind == "bbox" and isinstance(coordinates, dict):
        return {"x": float(coordinates.get("x", 0.0))
                     + float(coordinates.get("width", 0.0)) / 2.0,
                "y": float(coordinates.get("y", 0.0))
                     + float(coordinates.get("height", 0.0)) / 2.0}
    if kind == "ellipse" and isinstance(coordinates, dict):
        return {"x": float(coordinates.get("cx", 0.0)),
                "y": float(coordinates.get("cy", 0.0))}
    if kind in ("polygon", "polyline") and isinstance(coordinates, list):
        points = [(float(p.get("x", 0.0)), float(p.get("y", 0.0)))
                  for p in coordinates if isinstance(p, dict)]
        if not points:
            return None
        return {"x": sum(p[0] for p in points) / len(points),
                "y": sum(p[1] for p in points) / len(points)}
    if kind == "mask":
        return _mask_centroid(region)
    return None


def _mask_centroid(region: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """The centroid of a mask's set pixels, normalized."""
    from potato.export.cv_utils import decode_rle

    rle = region.get("rle") or {}
    size = rle.get("size") or []
    if len(size) != 2:
        return None
    height, width = int(size[0]), int(size[1])
    if height <= 0 or width <= 0:
        return None
    bitmap = decode_rle(rle, width, height)
    total = 0
    sum_x = sum_y = 0
    for index, value in enumerate(bitmap):
        if value:
            total += 1
            sum_x += index % width
            sum_y += index // width
    if not total:
        return None
    return {"x": (sum_x / total) / width, "y": (sum_y / total) / height}


def point_in_region(point: Dict[str, float], region: Dict[str, Any]) -> bool:
    """
    Does a normalized point fall inside a region?

    The measure Molmo-style pointing is scored with. For a mask this is exact;
    for a polygon it is a ray cast; for a box it is a range test. A *point*
    ground truth has no interior, so it is never a valid region here — that
    comparison is a distance question, and answering it with a boolean would
    report False for two points a pixel apart.
    """
    if not isinstance(point, dict) or not isinstance(region, dict):
        return False
    try:
        x = float(point["x"])
        y = float(point["y"])
    except (KeyError, TypeError, ValueError):
        return False

    kind = str(region.get("type") or "")
    coordinates = region.get("coordinates")

    if kind == "bbox" and isinstance(coordinates, dict):
        left = float(coordinates.get("x", 0.0))
        top = float(coordinates.get("y", 0.0))
        return (left <= x <= left + float(coordinates.get("width", 0.0))
                and top <= y <= top + float(coordinates.get("height", 0.0)))

    if kind == "ellipse" and isinstance(coordinates, dict):
        rx = float(coordinates.get("rx", 0.0)) or 1e-12
        ry = float(coordinates.get("ry", 0.0)) or 1e-12
        dx = (x - float(coordinates.get("cx", 0.0))) / rx
        dy = (y - float(coordinates.get("cy", 0.0))) / ry
        return dx * dx + dy * dy <= 1.0

    if kind == "polygon" and isinstance(coordinates, list):
        from potato.server_utils.iaa.geometry import _point_in_polygon

        points = [[float(p.get("x", 0.0)), float(p.get("y", 0.0))]
                  for p in coordinates if isinstance(p, dict)]
        return bool(points) and _point_in_polygon(x, y, points)

    if kind == "mask":
        from potato.export.cv_utils import decode_rle

        rle = region.get("rle") or {}
        size = rle.get("size") or []
        if len(size) != 2:
            return False
        height, width = int(size[0]), int(size[1])
        if height <= 0 or width <= 0:
            return False
        col = min(width - 1, max(0, int(x * width)))
        row = min(height - 1, max(0, int(y * height)))
        return bool(decode_rle(rle, width, height)[row * width + col])

    # landmark, keypoint_set, cuboid_2d and anything unknown: no interior.
    return False


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def grounding_accuracy(pairs: Sequence[Dict[str, Any]],
                       thresholds: Sequence[float] = DEFAULT_IOU_THRESHOLDS,
                       ) -> Dict[str, Any]:
    """
    Accuracy at several IoU thresholds, plus the absent/present breakdown.

    ``pairs`` is a list of ``{"truth": <object|None>, "prediction": <object|None>,
    "truth_absent": bool, "prediction_absent": bool}``. A pair whose truth is
    neither a region nor an explicit absence is **excluded** and counted, not
    scored: it is an expression nobody answered.

    Reported at several thresholds for the same reason a break-point report
    sweeps its tolerance — one number cannot distinguish "nearly right" from
    "nowhere near", and a model tuned to clear 0.5 exactly looks identical to
    one that is genuinely tight.
    """
    scored = []
    skipped = 0
    absent_correct = absent_missed = absent_false = 0

    for pair in pairs:
        truth = pair.get("truth")
        prediction = pair.get("prediction")
        truth_absent = bool(pair.get("truth_absent"))
        prediction_absent = bool(pair.get("prediction_absent"))

        if not truth_absent and not _is_region(truth):
            skipped += 1
            continue

        if truth_absent:
            # The model was right to point at nothing, or it hallucinated a
            # location for something that is not there. Neither is an IoU.
            if prediction_absent or not _is_region(prediction):
                absent_correct += 1
            else:
                absent_false += 1
            continue

        if prediction_absent or not _is_region(prediction):
            # There is a referent and the model declined to locate it.
            absent_missed += 1
            scored.append(0.0)
            continue

        scored.append(region_similarity(truth, prediction))

    result: Dict[str, Any] = {
        "n_scored": len(scored),
        "n_unanswered_excluded": skipped,
        "mean_iou": (sum(scored) / len(scored)) if scored else float("nan"),
        "absent": {
            "n_truth_absent": absent_correct + absent_false,
            "correctly_declined": absent_correct,
            "hallucinated_a_location": absent_false,
            "missed_a_present_referent": absent_missed,
        },
    }
    for threshold in thresholds:
        hits = sum(1 for value in scored if value >= threshold)
        result[f"acc@{threshold:g}"] = (hits / len(scored)) if scored else float("nan")
    return result


def pointing_accuracy(pairs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Point-in-region hit rate, with the near-misses measured rather than binned.

    ``pairs`` is ``{"truth": <region>, "point": {"x", "y"}, ...}`` with the same
    absence flags as :func:`grounding_accuracy`.

    A bare hit rate says nothing about how a model fails: pointing just outside
    a thin object and pointing at the other side of the image are both misses.
    So the mean distance from the region's centre is reported alongside, over
    the misses only — averaged over hits as well it would mostly measure how
    large the objects are.
    """
    hits = 0
    total = 0
    skipped = 0
    miss_distances: List[float] = []
    absent_correct = absent_false = absent_missed = 0

    for pair in pairs:
        truth = pair.get("truth")
        point = pair.get("point")
        truth_absent = bool(pair.get("truth_absent"))
        prediction_absent = bool(pair.get("prediction_absent"))

        if not truth_absent and not _is_region(truth):
            skipped += 1
            continue

        if truth_absent:
            if prediction_absent or not isinstance(point, dict):
                absent_correct += 1
            else:
                absent_false += 1
            continue

        if prediction_absent or not isinstance(point, dict):
            absent_missed += 1
            total += 1
            continue

        total += 1
        if point_in_region(point, truth):
            hits += 1
        else:
            centre = region_center(truth)
            if centre:
                miss_distances.append(
                    math.hypot(float(point.get("x", 0.0)) - centre["x"],
                               float(point.get("y", 0.0)) - centre["y"]))

    return {
        "n_scored": total,
        "n_unanswered_excluded": skipped,
        "point_in_region": (hits / total) if total else float("nan"),
        "n_hits": hits,
        "mean_miss_distance": (sum(miss_distances) / len(miss_distances))
                              if miss_distances else float("nan"),
        "absent": {
            "n_truth_absent": absent_correct + absent_false,
            "correctly_declined": absent_correct,
            "hallucinated_a_location": absent_false,
            "missed_a_present_referent": absent_missed,
        },
    }


def _is_region(value: Any) -> bool:
    """A usable annotation object, as opposed to None or an empty dict."""
    return bool(isinstance(value, dict) and value.get("type"))
