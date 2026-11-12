"""
Bounding-box consensus across annotators.

The boxes of one label on one item, from every annotator, are put into groups
that each hold at most one box per annotator:

1. For every remaining box (the *seed*), take the other annotators' remaining
   boxes in order of IoU with the seed, highest first, and add each one whose
   IoU with every box already in the group is at least ``iou_threshold``, at
   most one box per annotator.
2. Keep the seed whose group is largest (ties: the larger summed IoU with the
   seed, then the earlier box).
3. Remove the group's boxes and repeat until no box is left. A box that
   overlaps nothing becomes a group of one.

Every pair of boxes in a group therefore overlaps by at least the threshold,
so two boxes that each overlap a third but not each other are not merged.

The consensus box of a group is the median of its members' left, top, right
and bottom edges. Each group reports its support (annotators in it), the
support as a fraction of the item's classifiers for the scheme, and the mean
and minimum IoU of its members against the consensus box.

IoU does not change when both axes are scaled, so the grouping is done on the
stored image fractions and needs no image size; pixel coordinates are added
when the size is known.

This is not a port of panoptes_aggregation's box reducers: its
``rectangle_reducer`` runs DBSCAN on each box's x, y, width and height, and
``shape_reducer_dbscan`` with ``metric_type: IoU`` runs DBSCAN with 1 - IoU as
the distance, which can join boxes that do not overlap one another through a
chain of boxes that do.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.server_utils.iaa.geometry import iou_bbox


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def group_boxes(boxes: Sequence[Tuple[str, Sequence[float]]],
                iou_threshold: float) -> List[List[int]]:
    """Indices of ``boxes`` (``(annotator, [x, y, w, h])``) per group, in the
    order the groups were formed."""
    limit = iou_threshold - 1e-12
    n = len(boxes)
    iou = [[iou_bbox(boxes[i][1], boxes[j][1]) if i != j else 1.0 for j in range(n)]
           for i in range(n)]
    remaining = list(range(n))
    groups: List[List[int]] = []
    while remaining:
        best = None
        for seed in remaining:
            group, users = [seed], {boxes[seed][0]}
            candidates = sorted((j for j in remaining
                                 if j != seed and iou[seed][j] >= limit),
                                key=lambda j: (-iou[seed][j], j))
            for j in candidates:
                if boxes[j][0] in users:
                    continue
                if all(iou[j][k] >= limit for k in group):
                    group.append(j)
                    users.add(boxes[j][0])
            key = (len(group), sum(iou[seed][k] for k in group[1:]), -seed)
            if best is None or key > best[0]:
                best = (key, [group[0]] + sorted(group[1:]))
        group = best[1]
        groups.append(group)
        remaining = [k for k in remaining if k not in group]
    return groups


def box_consensus(boxes: Sequence[Tuple[str, Sequence[float]]], *,
                  iou_threshold: float, n_classifiers: int,
                  size: Optional[Tuple[float, float]] = None) -> List[Dict[str, Any]]:
    """Consensus boxes for one label on one item.

    Args:
        boxes: ``(annotator, [x, y, width, height])`` in image fractions.
        iou_threshold: least IoU between any two boxes in a group.
        n_classifiers: annotators who drew on this item for the scheme (the
            denominator of ``support_fraction``).
        size: ``(width, height)`` in pixels, or None.
    """
    out: List[Dict[str, Any]] = []
    for index, group in enumerate(group_boxes(boxes, iou_threshold)):
        members = [boxes[i] for i in group]
        x0 = _median([b[0] for _, b in members])
        y0 = _median([b[1] for _, b in members])
        x1 = _median([b[0] + b[2] for _, b in members])
        y1 = _median([b[1] + b[3] for _, b in members])
        consensus = [x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)]
        ious = [iou_bbox(b, consensus) for _, b in members]
        support = len({u for u, _ in members})
        entry: Dict[str, Any] = {
            "group": index,
            "x": consensus[0], "y": consensus[1],
            "width": consensus[2], "height": consensus[3],
            "x_px": None, "y_px": None, "width_px": None, "height_px": None,
            "support": support,
            "n_classifiers": n_classifiers,
            "support_fraction": (support / n_classifiers) if n_classifiers else 0.0,
            "mean_iou": sum(ious) / len(ious),
            "min_iou": min(ious),
            "annotators": sorted(u for u, _ in members),
        }
        if size:
            w, h = size
            entry.update(x_px=consensus[0] * w, y_px=consensus[1] * h,
                         width_px=consensus[2] * w, height_px=consensus[3] * h)
        out.append(entry)
    return out
