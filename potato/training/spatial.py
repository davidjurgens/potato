"""Point-cloud cuboids as training targets, and 3D detection scoring.

A ``spatial_annotation`` answer is a list of objects in absolute metres in
the sensor frame (``export/spatial_utils``). The training target is its
``cuboid_3d`` objects, normalized: ``{label, center, size, rotation}``,
rotation a quaternion ``(qx, qy, qz, qw)``. Points, polylines and point
segments are not detection targets. A sequence (frames with ``track_id``) is
not a target in this version: one scan per item.

Held-out scoring is 3D average precision: predictions matched greedily, by
score, to unmatched annotated cuboids of the same label at a volumetric IoU
of at least 0.5 (``iaa.geometry.iou_cuboid_3d``, exact for any rotation),
then VOC-style AP per label, averaged over labels.

Standard library only, apart from what ``iaa.geometry`` uses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

__all__ = ["spatial_target", "score_cuboids", "client_cuboid"]


def spatial_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """The answer's labelled cuboids, normalized; None when there are none."""
    from potato.export.spatial_utils import normalize_spatial_object
    from potato.training.vision import blob
    answer = blob(value_map)
    if isinstance(answer, dict):
        answer = answer.get("objects")
    if not isinstance(answer, list):
        return None
    out = []
    for obj in answer:
        if not isinstance(obj, dict) or obj.get("type") != "cuboid_3d":
            continue
        if obj.get("frame") is not None or obj.get("track_id") is not None:
            continue
        canonical = normalize_spatial_object(obj)
        if not canonical or not canonical.get("label") or not canonical.get("size"):
            continue
        out.append({"label": str(canonical["label"]),
                    "center": [float(v) for v in canonical["center"]],
                    "size": [float(v) for v in canonical["size"]],
                    "rotation": [float(v) for v in canonical["rotation"]]})
    return out or None


def client_cuboid(label: str, center: Sequence[float], size: Sequence[float],
                  yaw: float, score: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """A predicted cuboid in the viewer's stored shape, marked as a model's."""
    from potato.export.spatial_utils import to_client_spatial_object
    obj = to_client_spatial_object("cuboid_3d", label, center=center, size=size, yaw=yaw)
    if obj is None:
        return None
    obj["source"] = "model"
    if score is not None:
        obj["confidence"] = round(float(score), 4)
    return obj


def _canonical(payload: Any) -> List[Dict[str, Any]]:
    """Predicted cuboids, from the stored client shape or the target shape."""
    from potato.export.spatial_utils import normalize_spatial_object
    out = []
    for obj in payload if isinstance(payload, list) else []:
        if not isinstance(obj, dict):
            continue
        if "coordinates" in obj:
            if obj.get("type") != "cuboid_3d":
                continue
            canonical = normalize_spatial_object(obj)
            if not canonical or not canonical.get("size"):
                continue
            obj = {"label": canonical["label"], "center": canonical["center"],
                   "size": canonical["size"], "rotation": canonical["rotation"],
                   "confidence": obj.get("confidence")}
        out.append(obj)
    return out


def _average_precision(hits: List[bool], n_truth: int) -> float:
    """VOC all-point AP from matches in descending score order."""
    if not n_truth:
        return 0.0
    precisions, recalls, tp = [], [], 0
    for rank, hit in enumerate(hits, start=1):
        tp += hit
        precisions.append(tp / rank)
        recalls.append(tp / n_truth)
    ap, previous = 0.0, 0.0
    for i, recall in enumerate(recalls):
        if recall > previous:
            ap += (recall - previous) * max(precisions[i:])
            previous = recall
    return ap


def score_cuboids(gold: List[Any], predicted: List[Any],
                  thresholds: Sequence[float] = (0.25, 0.5)) -> Dict[str, float]:
    """3D AP per label at each IoU threshold, mean over labels; F1 at 0.5."""
    from potato.server_utils.iaa.geometry import iou_cuboid_3d
    labels = sorted({t["label"] for target in gold for t in target or []})
    if not labels:
        return {}
    out: Dict[str, float] = {}
    for threshold in thresholds:
        aps, tp_all, fp_all, fn_all = [], 0, 0, 0
        for label in labels:
            scored, n_truth = [], 0
            for target, payload in zip(gold, predicted):
                truths = [t for t in target or [] if t["label"] == label]
                n_truth += len(truths)
                guesses = sorted((p for p in _canonical(payload) if p.get("label") == label),
                                 key=lambda p: -(p.get("confidence") or 0.0))
                taken = set()
                for guess in guesses:
                    best, best_iou = None, threshold
                    for index, truth in enumerate(truths):
                        if index in taken:
                            continue
                        iou = iou_cuboid_3d(truth, guess)
                        if iou >= best_iou:
                            best, best_iou = index, iou
                    if best is not None:
                        taken.add(best)
                    scored.append((guess.get("confidence") or 0.0, best is not None))
                fn_all += len(truths) - len(taken)
            scored.sort(key=lambda s: -s[0])
            hits = [hit for _, hit in scored]
            tp_all += sum(hits)
            fp_all += len(hits) - sum(hits)
            aps.append(_average_precision(hits, n_truth))
            if threshold == 0.5:
                out["ap_3d_50_%s" % label] = aps[-1]
        key = "map_3d_%d" % round(threshold * 100)
        out[key] = sum(aps) / len(aps)
        if threshold == 0.5:
            precision = tp_all / (tp_all + fp_all) if tp_all + fp_all else 0.0
            recall = tp_all / (tp_all + fn_all) if tp_all + fn_all else 0.0
            out.update(precision=precision, recall=recall,
                       f1=2 * precision * recall / (precision + recall)
                       if precision + recall else 0.0)
    return out
