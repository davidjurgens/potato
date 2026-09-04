"""
Chance-corrected agreement over geometry.

Nothing else self-hostable reports this. CVAT's consensus engine and V7's
consensus stage both threshold raw IoU against a per-class cutoff; neither
applies any chance correction, so "0.7 mean IoU" is uninterpretable without
knowing how easy the task was. This module answers "how good is this dataset?"
with a number that can go in a paper.

WHY NOT SIMPLY ALPHA OVER 1 - IoU
---------------------------------
That was the original plan and it is empirically the wrong default. Braylan,
Alonso and Lease (WWW 2022, "Measuring Annotator Agreement Generally across
Complex Structured, Multi-object, and Free-text Annotation Tasks") evaluate
distance functions by whether the resulting agreement score RANKS annotator
quality correctly, and find IoU-based distances rank below simple L2 on their
own benchmark. IoU is also badly behaved where it matters most: two boxes that
do not overlap have IoU 0 whether they are adjacent or on opposite sides of the
image, so every disjoint pair looks equally bad and the coefficient loses its
gradient exactly where annotators disagree most.

So the primary measures here follow Braylan et al.'s generalized approach:

* **sigma** -- ``1 - mean(within-item distance) / mean(between-item distance)``.
  This is alpha's own ``1 - D_o/D_e`` form with an arbitrary distance, where the
  chance baseline is estimated by comparing annotations of DIFFERENT items.
  0 means annotators agree no more than they would on unrelated items; 1 means
  perfect agreement; negative means systematic disagreement.
* **ks** -- the Kolmogorov-Smirnov statistic between the within-item and
  between-item distance DISTRIBUTIONS. Sigma compares two means and can be
  dragged around by a few outliers; KS compares the whole distributions and is
  the more robust of the pair when item difficulty varies a lot.

GIoU is provided as the distance of choice because it keeps a gradient for
disjoint shapes (Rezatofighi et al., CVPR 2019) -- the property plain IoU lacks.

THREE QUESTIONS, NOT ONE
------------------------
Annotators can disagree about whether an object exists, what class it is, and
where its boundary lies. These have different causes and different remedies, so
reporting one blended number is misleading:

* **detection** -- did they find the same objects? (alpha over present/absent)
* **classification** -- given they found it, do they agree what it is?
  (alpha over labels, nominal)
* **localization** -- given they agree it is there, do they agree where?
  (sigma / KS over matched-pair distances)

A project with detection 0.9 and localization 0.4 needs better drawing
guidelines. One with detection 0.4 and localization 0.9 needs a clearer
definition of what counts as an object. The blend, 0.65, suggests neither.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import geometry
from .alpha import krippendorff_alpha

logger = logging.getLogger(__name__)

#: IoU above which two objects are considered the same object by different
#: annotators. 0.5 is the COCO detection convention.
DEFAULT_MATCH_THRESHOLD = 0.5

#: Between-item pairs sampled to estimate the chance baseline. The full
#: cross-product is quadratic in the corpus and adds nothing after a few
#: thousand draws.
DEFAULT_CHANCE_SAMPLES = 2000

#: Bootstrap resamples for confidence intervals. Resampling ITEMS, not
#: instances: instances within an item are not independent, and treating them
#: as though they were produces intervals that are far too narrow.
DEFAULT_BOOTSTRAP = 200

#: Seeded so a reported interval is reproducible. An agreement number that
#: moves between runs of the same data is not usable in a paper.
DEFAULT_SEED = 20260813

#: Hard ceiling on matched-pair distance computations.
#:
#: Pairwise comparison is quadratic in annotators AND in instances per item, so
#: a 5-annotator project with 50 instances per image costs 25k mask decodes per
#: image. The budget stops that turning an admin page load into a hang.
#:
#: When it is hit the report says so LOUDLY and reports how much it saw. A
#: truncated agreement number that reads as complete is worse than no number:
#: it will be quoted.
DEFAULT_MAX_PAIRS = 200_000


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------


def giou_bbox(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Generalized IoU for two ``[x, y, w, h]`` boxes (Rezatofighi et al. 2019).

    Ranges [-1, 1]. The point of it: plain IoU is 0 for every disjoint pair,
    whether the boxes are touching or at opposite corners, so it has no
    gradient exactly where annotators disagree most. GIoU subtracts the share
    of the smallest enclosing box that neither occupies, so "nearly touching"
    scores better than "far apart".
    """
    ax, ay, aw, ah = (float(v) for v in a[:4])
    bx, by, bw, bh = (float(v) for v in b[:4])
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return -1.0

    inter_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = inter_w * inter_h
    union = aw * ah + bw * bh - intersection
    if union <= 0:
        return -1.0
    iou = intersection / union

    hull_w = max(ax + aw, bx + bw) - min(ax, bx)
    hull_h = max(ay + ah, by + bh) - min(ay, by)
    hull = hull_w * hull_h
    if hull <= 0:
        return iou
    return iou - (hull - union) / hull


def giou_distance(obj_a: Dict[str, Any], obj_b: Dict[str, Any]) -> float:
    """
    Distance in [0, 1] built from GIoU, for objects with a bounding box.

    GIoU runs [-1, 1], so the affine map to a distance is ``(1 - giou) / 2``.
    Objects without usable boxes fall back to the shared ``delta_geometric``.
    """
    box_a = _bbox_of(obj_a)
    box_b = _bbox_of(obj_b)
    if box_a is None or box_b is None:
        return geometry.delta_geometric(obj_a, obj_b)
    return (1.0 - giou_bbox(box_a, box_b)) / 2.0


def _bbox_of(obj: Dict[str, Any]) -> Optional[List[float]]:
    """
    An [x, y, w, h] box for any object type, or None.

    Reads the CANONICAL form first (`bbox`, as normalize_annotation_object
    produces) and falls back to the client form (`coordinates`). Reading only
    the client form meant GIoU silently never fired on canonical objects and
    every distance fell through to plain IoU -- the exact measure this module
    exists to avoid defaulting to.
    """
    if not isinstance(obj, dict):
        return None

    box = obj.get("bbox")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
        except (TypeError, ValueError):
            pass

    points = obj.get("points")
    if isinstance(points, (list, tuple)) and points:
        xs, ys = [], []
        for point in points:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            elif isinstance(point, dict):
                xs.append(float(point.get("x", 0)))
                ys.append(float(point.get("y", 0)))
        if xs and ys:
            return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]

    coords = obj.get("coordinates")
    if isinstance(coords, dict) and "width" in coords and "height" in coords:
        return [float(coords.get("x", 0)), float(coords.get("y", 0)),
                float(coords["width"]), float(coords["height"])]
    if isinstance(coords, list) and coords:
        xs, ys = [], []
        for point in coords:
            if isinstance(point, dict):
                xs.append(float(point.get("x", 0)))
                ys.append(float(point.get("y", 0)))
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
        if xs and ys:
            return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
    if isinstance(coords, dict) and "rx" in coords:
        return [float(coords.get("cx", 0)) - float(coords["rx"]),
                float(coords.get("cy", 0)) - float(coords.get("ry", 0)),
                2 * float(coords["rx"]), 2 * float(coords.get("ry", 0))]
    return None


def centroid_distance(obj_a: Dict[str, Any], obj_b: Dict[str, Any]) -> float:
    """
    Normalized L2 between object centres.

    Braylan et al. found plain L2 ranks annotator quality better than IoU on
    their benchmark, so it is offered as a first-class alternative rather than
    a curiosity. Divided by sqrt(2) so a diagonal-opposite pair scores 1.0 in
    normalized image coordinates.
    """
    box_a = _bbox_of(obj_a)
    box_b = _bbox_of(obj_b)
    if box_a is None or box_b is None:
        return geometry.delta_geometric(obj_a, obj_b)
    ax = box_a[0] + box_a[2] / 2
    ay = box_a[1] + box_a[3] / 2
    bx = box_b[0] + box_b[2] / 2
    by = box_b[1] + box_b[3] / 2
    return min(1.0, math.hypot(ax - bx, ay - by) / math.sqrt(2))


#: Named distances the report can be asked for.
DISTANCES: Dict[str, Callable[[dict, dict], float]] = {
    "giou": giou_distance,
    "iou": geometry.delta_geometric,
    "centroid": centroid_distance,
}

DEFAULT_DISTANCE = "giou"


# ---------------------------------------------------------------------------
# Sigma and KS
# ---------------------------------------------------------------------------


def _within_item_distances(items: Dict[str, Dict[str, List[dict]]],
                           distance: Callable[[dict, dict], float],
                           threshold: float,
                           max_pairs: int = DEFAULT_MAX_PAIRS,
                           ) -> Tuple[List[float], int]:
    """
    Distances between MATCHED pairs from different annotators, same item.

    Returns ``(distances, items_skipped)``. Skipping is reported rather than
    silent: a truncated agreement number that reads as complete will be quoted.
    """
    out: List[float] = []
    budget = max_pairs
    skipped = 0

    for objects_by_annotator in items.values():
        annotators = sorted(objects_by_annotator)
        # Cheap upper bound on this item's cost, so a pathological item is
        # skipped WHOLE rather than half-measured -- a partially processed item
        # biases the mean toward whichever annotator pair happened to run.
        widest = max((len(objects_by_annotator[a]) for a in annotators),
                     default=0)
        pairs = len(annotators) * (len(annotators) - 1) // 2
        if budget <= 0 or pairs * max(1, widest) > budget:
            skipped += 1
            continue

        for i, left in enumerate(annotators):
            for right in annotators[i + 1:]:
                matches, _, _ = geometry.match_instances(
                    objects_by_annotator[left], objects_by_annotator[right],
                    threshold=threshold)
                # (index_a, index_b, similarity) triples.
                for a_idx, b_idx, _score in matches:
                    out.append(distance(objects_by_annotator[left][a_idx],
                                        objects_by_annotator[right][b_idx]))
                budget -= max(1, len(objects_by_annotator[left])
                              * len(objects_by_annotator[right]))
    return out, skipped


def _between_item_distances(items: Dict[str, Dict[str, List[dict]]],
                            distance: Callable[[dict, dict], float],
                            samples: int, rng: random.Random) -> List[float]:
    """
    The chance baseline: distances between objects on DIFFERENT items.

    This is what makes the measure chance-corrected. An easy corpus -- one big
    centred object per image -- produces small between-item distances too, so
    the ratio stays honest instead of rewarding the task for being easy.
    """
    pool: List[Tuple[str, dict]] = []
    for item_id, objects_by_annotator in items.items():
        for objects in objects_by_annotator.values():
            for obj in objects:
                pool.append((item_id, obj))
    if len(pool) < 2:
        return []

    out: List[float] = []
    attempts = 0
    limit = samples * 4
    while len(out) < samples and attempts < limit:
        attempts += 1
        left_item, left = pool[rng.randrange(len(pool))]
        right_item, right = pool[rng.randrange(len(pool))]
        if left_item == right_item:
            continue
        out.append(distance(left, right))
    return out


def _ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Two-sample Kolmogorov-Smirnov statistic, in [0, 1].

    Implemented here rather than pulled from scipy: this package is imported on
    the agreement path, and scipy is an optional dependency elsewhere in Potato.
    The statistic is a sorted merge, so there is nothing to gain from the
    dependency.
    """
    if not a or not b:
        return float("nan")
    sorted_a = sorted(a)
    sorted_b = sorted(b)
    i = j = 0
    cdf_a = cdf_b = 0.0
    best = 0.0
    n, m = len(sorted_a), len(sorted_b)
    while i < n and j < m:
        if sorted_a[i] <= sorted_b[j]:
            i += 1
            cdf_a = i / n
        else:
            j += 1
            cdf_b = j / m
        best = max(best, abs(cdf_a - cdf_b))
    return best


def sigma_agreement(within: Sequence[float],
                    between: Sequence[float]) -> float:
    """
    ``1 - mean(within) / mean(between)``.

    Alpha's own form with an arbitrary distance. 1 is perfect agreement, 0 is
    chance, negative is systematic disagreement -- annotators further apart on
    the same item than on unrelated ones, which usually means a definition
    problem rather than carelessness.
    """
    if not within or not between:
        return float("nan")
    expected = sum(between) / len(between)
    if expected <= 0:
        # Every pair of objects is identical, so the measure is undefined
        # rather than perfect: there is no variation to agree about.
        return float("nan")
    observed = sum(within) / len(within)
    return 1.0 - observed / expected


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def geometry_agreement(
    items: Dict[str, Dict[str, List[dict]]],
    *,
    distance: str = DEFAULT_DISTANCE,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    chance_samples: int = DEFAULT_CHANCE_SAMPLES,
    bootstrap: int = 0,
    seed: int = DEFAULT_SEED,
    max_pairs: int = DEFAULT_MAX_PAIRS,
) -> Dict[str, Any]:
    """
    Agreement over geometry, decomposed into its three questions.

    Args:
        items: ``{item_id: {annotator_id: [client-shaped objects]}}``
        distance: one of :data:`DISTANCES`
        threshold: IoU above which two objects are "the same object"
        chance_samples: between-item pairs used for the chance baseline
        bootstrap: resamples for confidence intervals; 0 to skip
        seed: fixed so a reported interval is reproducible

    Returns:
        A dict with ``detection``, ``classification``, ``localization``,
        counts, and the settings used. Every number is NaN rather than a
        fabricated 0 or 1 when it is undefined.
    """
    if distance not in DISTANCES:
        raise ValueError(
            f"Unknown distance {distance!r}. Available: "
            f"{', '.join(sorted(DISTANCES))}")
    metric = DISTANCES[distance]
    rng = random.Random(seed)

    comparable = {
        item_id: _canonicalize(by_annotator)
        for item_id, by_annotator in items.items()
        if len(by_annotator) >= 2
    }

    within, budget_skipped = _within_item_distances(
        comparable, metric, threshold, max_pairs)
    between = _between_item_distances(comparable, metric, chance_samples, rng)

    result: Dict[str, Any] = {
        "distance": distance,
        "match_threshold": threshold,
        "n_items": len(comparable),
        "n_items_skipped": len(items) - len(comparable),
        "n_matched_pairs": len(within),
        "n_chance_pairs": len(between),
        "detection": _detection_agreement(comparable, threshold),
        "classification": _classification_agreement(comparable, threshold),
        "localization": {
            "sigma": sigma_agreement(within, between),
            "ks": _ks_statistic(within, between),
            "mean_distance": (sum(within) / len(within)) if within else float("nan"),
            "mean_chance_distance": (
                (sum(between) / len(between)) if between else float("nan")),
        },
    }

    if budget_skipped:
        result["truncated"] = True
        result["n_items_over_budget"] = budget_skipped
        result["truncation_note"] = (
            f"{budget_skipped} item(s) exceeded the {max_pairs:,}-pair "
            f"comparison budget and were left out ENTIRELY rather than "
            f"partially measured. The numbers above describe the "
            f"{len(comparable) - budget_skipped} item(s) that fit. Raise "
            f"max_pairs to include them.")
        logger.warning(result["truncation_note"])

    if len(items) and not comparable:
        result["note"] = (
            "No item has two or more annotators, so agreement is undefined. "
            "Raise annotators_per_instance, or wait for more annotations.")

    if bootstrap:
        result["confidence"] = _bootstrap_intervals(
            comparable, metric, threshold, chance_samples, bootstrap, seed)
    return result


def canonical_object(obj: dict) -> Optional[dict]:
    """
    One client-shaped object -> the canonical form the distance functions read.

    `similarity()` and everything built on it expect what
    `cv_utils.normalize_annotation_object` returns -- `bbox`, `points`, `rle` --
    NOT the stored client shape with `coordinates`. Passing the client shape
    does not raise; it silently scores every pair 0 similarity, so nothing
    matches and every measure comes back NaN. `detection_ap` was written
    against the client shape and scored a perfect detector 0.0 for exactly
    this reason, so the conversion lives here rather than in each caller.

    Returns None for anything that is not a dict.
    """
    from potato.server_utils.annotation_values import _as_canonical

    if not isinstance(obj, dict):
        return None
    # Already canonical (has bbox/points/rle and no coordinates)?
    if "coordinates" not in obj and (
            "bbox" in obj or "points" in obj or "rle" in obj):
        return obj
    return _as_canonical(obj)


def _canonicalize(objects_by_annotator: Dict[str, List[dict]]
                  ) -> Dict[str, List[dict]]:
    """Client-shaped objects -> canonical, for a whole {annotator: [obj]} map."""
    out: Dict[str, List[dict]] = {}
    for annotator, objects in objects_by_annotator.items():
        converted = [canonical_object(obj) for obj in objects or []]
        out[annotator] = [obj for obj in converted if obj is not None]
    return out


def _matched_clusters(objects_by_annotator: Dict[str, List[dict]],
                      threshold: float) -> List[Dict[str, dict]]:
    """
    Group one item's objects into clusters that different annotators agree on.

    Greedy against the first annotator who contributed each cluster. Not
    optimal, but the alternative -- global assignment across N annotators -- is
    a much larger problem for a difference that only shows up when several
    annotators draw heavily overlapping objects, which is rare and is itself a
    sign the task needs clearer instructions.
    """
    clusters: List[Dict[str, dict]] = []
    for annotator in sorted(objects_by_annotator):
        for obj in objects_by_annotator[annotator]:
            placed = False
            for cluster in clusters:
                if annotator in cluster:
                    continue
                reference = next(iter(cluster.values()))
                if geometry.similarity(reference, obj) >= threshold:
                    cluster[annotator] = obj
                    placed = True
                    break
            if not placed:
                clusters.append({annotator: obj})
    return clusters


def _detection_agreement(items: Dict[str, Dict[str, List[dict]]],
                         threshold: float) -> Dict[str, Any]:
    """
    Alpha over present/absent per matched cluster.

    A genuine categorical variable: for each object anybody found, did each
    annotator find it? This is the question MACE can also answer, which is why
    it is kept separate from the geometry.
    """
    rows: List[Tuple[str, str, str]] = []
    for item_id, by_annotator in items.items():
        annotators = sorted(by_annotator)
        for index, cluster in enumerate(_matched_clusters(by_annotator, threshold)):
            unit = f"{item_id}#{index}"
            for annotator in annotators:
                rows.append((annotator, unit,
                             "present" if annotator in cluster else "absent"))
    return _alpha_result(rows, "every annotator found every object")


def _classification_agreement(items: Dict[str, Dict[str, List[dict]]],
                              threshold: float) -> Dict[str, Any]:
    """
    Alpha over labels, on clusters at least two annotators found.

    Restricted to agreed-upon objects on purpose: mixing in the ones only one
    annotator saw would conflate "we disagree what this is" with "one of us
    missed it", which is the detection question and is reported separately.
    """
    rows: List[Tuple[str, str, str]] = []
    for item_id, by_annotator in items.items():
        for index, cluster in enumerate(_matched_clusters(by_annotator, threshold)):
            if len(cluster) < 2:
                continue
            unit = f"{item_id}#{index}"
            for annotator, obj in cluster.items():
                rows.append((annotator, unit, str(obj.get("label", ""))))
    return _alpha_result(rows, "every matched object got the same label")


def _alpha_result(rows, unanimous_note: str) -> Dict[str, Any]:
    """
    Alpha, plus a reason when it is undefined.

    Alpha divides by expected disagreement, so a corpus where every annotator
    gave the same answer everywhere has D_e = 0 and alpha is genuinely
    undefined -- not 1.0. Reporting a bare NaN is technically right and
    practically useless: the reader cannot tell "perfect agreement" from "the
    computation broke". So the unanimous case is named.
    """
    value = krippendorff_alpha(rows, "nominal")
    result: Dict[str, Any] = {
        "alpha": value,
        "n_clusters": len({unit for _a, unit, _v in rows}),
    }
    if math.isnan(value) and rows:
        distinct = {v for _a, _u, v in rows}
        if len(distinct) < 2:
            result["undefined_because"] = (
                f"{unanimous_note}, so there is no variation for alpha to "
                f"correct against. Perfect agreement, not a failed "
                f"computation.")
        else:
            result["undefined_because"] = (
                "too few items or annotators for alpha to be defined")
    return result


def _bootstrap_intervals(items, metric, threshold, chance_samples,
                         resamples, seed) -> Dict[str, Any]:
    """
    Percentile bootstrap over ITEMS.

    Resampling items rather than instances is the whole point: two boxes on one
    image are not independent observations, and resampling them individually
    produces intervals far too narrow to be honest.
    """
    item_ids = sorted(items)
    if len(item_ids) < 2:
        return {"note": "too few items to bootstrap"}

    rng = random.Random(seed)
    sigmas: List[float] = []
    for _ in range(resamples):
        drawn = [item_ids[rng.randrange(len(item_ids))]
                 for _ in range(len(item_ids))]
        # Distinct keys, or a duplicate draw would silently collapse.
        sample = {f"{item_id}~{i}": items[item_id]
                  for i, item_id in enumerate(drawn)}
        within, _skipped = _within_item_distances(sample, metric, threshold)
        between = _between_item_distances(
            sample, metric, chance_samples, rng)
        value = sigma_agreement(within, between)
        if not math.isnan(value):
            sigmas.append(value)

    if len(sigmas) < 2:
        return {"note": "sigma undefined in too many resamples"}
    sigmas.sort()
    return {
        "sigma_lower": sigmas[int(0.025 * len(sigmas))],
        "sigma_upper": sigmas[min(len(sigmas) - 1, int(0.975 * len(sigmas)))],
        "n_resamples": len(sigmas),
    }


# ---------------------------------------------------------------------------
# Mask consensus (STAPLE)
# ---------------------------------------------------------------------------


def mask_consensus(items: Dict[str, Dict[str, List[dict]]],
                   dimensions: Dict[str, Tuple[int, int]],
                   *, label: Optional[str] = None) -> Dict[str, Any]:
    """
    Per-annotator mask performance, via STAPLE.

    Answers the question sigma cannot: not "do they agree?" but "whose boundary
    should the dataset record, and who drew it well?" See :mod:`potato.staple`
    for why MACE cannot do this and STAPLE can.

    Args:
        items: ``{item_id: {annotator_id: [client-shaped objects]}}``
        dimensions: ``{item_id: (width, height)}`` -- masks are absolute RLE,
            so the pixel grid has to come from the item
        label: restrict to one class; None pools every mask on the item

    Returns:
        Per-annotator mean sensitivity/specificity across items, plus the
        per-item detail. Items with fewer than two mask-bearing annotators are
        counted and skipped rather than silently dropped.
    """
    try:
        import numpy as np  # noqa: F401

        from potato import staple as staple_module
    except ImportError:
        return {"error": "STAPLE needs numpy, which is not installed"}

    per_item: Dict[str, Any] = {}
    sensitivity: Dict[str, List[float]] = {}
    specificity: Dict[str, List[float]] = {}
    skipped = 0

    for item_id, by_annotator in items.items():
        size = dimensions.get(item_id)
        if not size:
            skipped += 1
            continue
        width, height = size
        if width <= 0 or height <= 0:
            skipped += 1
            continue

        rles = {}
        for annotator, objects in by_annotator.items():
            merged = _merge_masks(objects, label, width, height)
            if merged:
                rles[annotator] = merged
        if len(rles) < 2:
            skipped += 1
            continue

        try:
            result = staple_module.staple_from_rle(rles, width, height)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("STAPLE failed on %s: %s", item_id, exc)
            skipped += 1
            continue

        per_item[item_id] = result.as_dict()
        for annotator, value in result.sensitivity.items():
            sensitivity.setdefault(annotator, []).append(value)
        for annotator, value in result.specificity.items():
            specificity.setdefault(annotator, []).append(value)

    def _mean(values):
        return sum(values) / len(values) if values else float("nan")

    return {
        "n_items": len(per_item),
        "n_items_skipped": skipped,
        "mean_sensitivity": {a: _mean(v) for a, v in sensitivity.items()},
        "mean_specificity": {a: _mean(v) for a, v in specificity.items()},
        "per_item": per_item,
    }


def _merge_masks(objects: List[dict], label: Optional[str],
                 width: int, height: int) -> Optional[dict]:
    """
    One binary mask per annotator per item, OR-ing their mask objects together.

    STAPLE compares two annotators pixel by pixel, so an annotator who drew
    three separate instances of a class contributes the union of them. Keeping
    the instances apart would need them matched across annotators first, which
    is the detection question and is answered separately.
    """
    from potato.export.cv_utils import decode_rle

    flat = None
    for obj in objects or []:
        if not isinstance(obj, dict) or obj.get("type") != "mask":
            continue
        if label is not None and obj.get("label") != label:
            continue
        rle = obj.get("rle") or {}
        if not rle.get("counts"):
            continue
        decoded = decode_rle(rle, width, height)
        if flat is None:
            flat = list(decoded)
        else:
            for i, value in enumerate(decoded):
                if value:
                    flat[i] = 1

    if flat is None:
        return None

    counts: List[int] = []
    current = 0
    run = 0
    for value in flat:
        if value == current:
            run += 1
        else:
            counts.append(run)
            current = 1 - current
            run = 1
    counts.append(run)
    return {"counts": counts, "size": [height, width]}
