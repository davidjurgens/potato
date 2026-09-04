"""Average precision for detection, the way COCO computes it.

Every other metric in this package answers "do two annotators agree". This one
answers a different question: "is this model's detector any good", scored
against human annotations as ground truth. It is here rather than in the
training package because it shares the IoU functions and object contract with
:mod:`potato.server_utils.iaa.geometry`, and because a run's score belongs in
the same vocabulary as everything else the admin reads.

Without it there is no way to compare detector run *n* to run *n+1*. IoU on its
own tells you how well two boxes overlap; it says nothing about the boxes the
model missed or the ones it invented, and those are the whole question for a
detector. A model that finds one object perfectly and misses forty scores 1.0
on mean IoU.

The confidence ordering is what makes it a *curve* rather than a number, so
predictions without a score are ranked last rather than dropped -- a detector
that reports no confidence still deserves a number, it just cannot be
thresholded.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "average_precision",
    "mean_average_precision",
    "detection_pr_curve",
    "COCO_THRESHOLDS",
]

#: The IoU sweep COCO averages over: 0.50 to 0.95 in steps of 0.05.
COCO_THRESHOLDS = tuple(round(0.50 + 0.05 * i, 2) for i in range(10))

#: COCO interpolates the PR curve at 101 evenly spaced recall points.
_RECALL_POINTS = tuple(round(i / 100.0, 2) for i in range(101))


def _confidence_of(obj: Dict[str, Any]) -> float:
    for key in ("confidence", "score", "probability", "prob"):
        value = obj.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    # No score: rank last, but still count. Dropping it would silently improve
    # precision by hiding the model's least-confident guesses.
    return -1.0


def _label_of(obj: Dict[str, Any]) -> str:
    return str(obj.get("label", obj.get("category", "")))


def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Overlap between two objects in either the stored or the canonical shape.

    `similarity()` reads the canonical form -- `bbox`, `points`, `rle` -- while
    annotators and the client store `coordinates`. Handing it the stored shape
    does not raise; it scores every pair 0.0, so a detector that reproduces the
    ground truth exactly scores AP 0.0 and reads as completely broken. Both
    shapes reach this function in practice: ground truth comes from
    annotations, predictions come from a model.
    """
    from potato.server_utils.iaa.geometry import similarity
    from potato.server_utils.iaa.geometry_agreement import canonical_object

    try:
        obj_a, obj_b = canonical_object(a), canonical_object(b)
        if obj_a is None or obj_b is None:
            return 0.0
        return float(similarity(obj_a, obj_b))
    except Exception:
        return 0.0


def detection_pr_curve(
    predictions: Sequence[Tuple[str, Dict[str, Any]]],
    ground_truth: Dict[str, List[Dict[str, Any]]],
    threshold: float = 0.5,
) -> Tuple[List[float], List[float]]:
    """Precision and recall arrays for one class at one IoU threshold.

    Args:
        predictions: ``(instance_id, object)`` pairs, any order.
        ground_truth: ``{instance_id: [object, ...]}``.
        threshold: IoU at or above which a match counts as a hit.

    Each ground-truth object can be matched once. A second prediction covering
    the same object is a false positive, which is what stops a model from
    scoring well by predicting the same box fifty times.
    """
    n_truth = sum(len(objs) for objs in ground_truth.values())
    if n_truth == 0:
        return [], []

    ranked = sorted(predictions, key=lambda p: _confidence_of(p[1]),
                    reverse=True)
    claimed: Dict[str, set] = {iid: set() for iid in ground_truth}

    true_positives = 0
    false_positives = 0
    precisions: List[float] = []
    recalls: List[float] = []

    for instance_id, prediction in ranked:
        candidates = ground_truth.get(instance_id, [])
        best_index, best_iou = -1, 0.0
        for index, truth in enumerate(candidates):
            if index in claimed.get(instance_id, ()):
                continue
            score = _iou(prediction, truth)
            if score > best_iou:
                best_index, best_iou = index, score

        if best_index >= 0 and best_iou >= threshold:
            claimed.setdefault(instance_id, set()).add(best_index)
            true_positives += 1
        else:
            false_positives += 1

        precisions.append(true_positives / (true_positives + false_positives))
        recalls.append(true_positives / n_truth)

    return precisions, recalls


def _interpolated_ap(precisions: Sequence[float],
                     recalls: Sequence[float]) -> float:
    """101-point interpolated average precision, as COCO defines it.

    Precision is made monotonically decreasing first, so a later spike in
    precision cannot make an earlier recall level look better than it was.
    """
    if not precisions:
        return 0.0

    # Make precision monotone from the right.
    envelope = list(precisions)
    for i in range(len(envelope) - 2, -1, -1):
        envelope[i] = max(envelope[i], envelope[i + 1])

    total = 0.0
    for point in _RECALL_POINTS:
        best = 0.0
        for precision, recall in zip(envelope, recalls):
            if recall >= point:
                best = precision
                break
        total += best
    return total / len(_RECALL_POINTS)


def average_precision(
    predictions: Sequence[Tuple[str, Dict[str, Any]]],
    ground_truth: Dict[str, List[Dict[str, Any]]],
    threshold: float = 0.5,
) -> float:
    """AP for one class at one IoU threshold."""
    precisions, recalls = detection_pr_curve(predictions, ground_truth,
                                             threshold)
    return _interpolated_ap(precisions, recalls)


def mean_average_precision(
    predictions: Dict[str, List[Dict[str, Any]]],
    ground_truth: Dict[str, List[Dict[str, Any]]],
    thresholds: Optional[Iterable[float]] = None,
) -> Dict[str, Any]:
    """mAP over every class present, at one or more IoU thresholds.

    Args:
        predictions: ``{instance_id: [object, ...]}`` from the model.
        ground_truth: ``{instance_id: [object, ...]}`` from annotators.
        thresholds: defaults to ``(0.5,)`` plus the COCO sweep.

    Returns a dict with ``mAP_50``, ``mAP_50_95``, ``per_class`` and
    ``n_predictions`` / ``n_truth``, so a caller can tell "the model is bad"
    apart from "there was nothing to score".

    Classes are taken from the *union* of predicted and true labels. Scoring
    only the classes a model predicted would let it score well by refusing to
    predict the hard ones.
    """
    thresholds = tuple(thresholds) if thresholds is not None else COCO_THRESHOLDS

    classes = set()
    for objects in predictions.values():
        classes.update(_label_of(o) for o in objects)
    for objects in ground_truth.values():
        classes.update(_label_of(o) for o in objects)

    n_predictions = sum(len(o) for o in predictions.values())
    n_truth = sum(len(o) for o in ground_truth.values())

    if not classes or not n_truth:
        return {"mAP_50": None, "mAP_50_95": None, "per_class": {},
                "n_predictions": n_predictions, "n_truth": n_truth,
                "note": ("Nothing to score: there are no ground-truth objects."
                         if not n_truth else "No labelled classes.")}

    per_class: Dict[str, Dict[str, float]] = {}
    for label in sorted(classes):
        class_predictions = [
            (iid, obj) for iid, objs in predictions.items()
            for obj in objs if _label_of(obj) == label]
        class_truth = {
            iid: [o for o in objs if _label_of(o) == label]
            for iid, objs in ground_truth.items()}
        class_truth = {k: v for k, v in class_truth.items() if v}

        if not class_truth:
            # Predicted but never annotated: every prediction is a false
            # positive, and AP is 0 rather than undefined.
            per_class[label] = {t: 0.0 for t in thresholds}
            continue

        per_class[label] = {
            t: average_precision(class_predictions, class_truth, t)
            for t in thresholds}

    def mean_at(threshold: float) -> Optional[float]:
        values = [scores[threshold] for scores in per_class.values()
                  if threshold in scores]
        return (sum(values) / len(values)) if values else None

    all_values = [v for scores in per_class.values() for v in scores.values()]

    return {
        "mAP_50": mean_at(0.5) if 0.5 in thresholds else None,
        "mAP_50_95": (sum(all_values) / len(all_values)) if all_values else None,
        "per_class": {label: {str(t): round(v, 4) for t, v in scores.items()}
                      for label, scores in per_class.items()},
        "n_predictions": n_predictions,
        "n_truth": n_truth,
        "thresholds": list(thresholds),
    }
