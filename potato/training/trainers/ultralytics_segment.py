"""Train a YOLO instance-segmentation model with Ultralytics.

The segmentation counterpart of ``ultralytics-detect``, for ``image_annotation``
schemes with polygons, ellipses, freeform outlines or brush masks. Each outline
becomes a YOLO-seg label line (``class x1 y1 x2 y2 ...``, normalized); boxes
are left out, because a box does not say which pixels the object covers. A
mask in several pieces trains as its largest piece.

Predictions are the model's outlines as the image widget's polygons, at most
64 vertices each, with ``source: "ai"`` and the model's score.

AGPL-3.0, with the same acknowledgement, analytics and auto-install handling
as ``ultralytics-detect``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Tuple

from potato.training.trainers import _segmentation as seg
from potato.training.trainers.ultralytics_detect import UltralyticsDetectTrainer


def _area(ring: List[List[float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                   in zip(ring, ring[1:] + ring[:1]))) / 2.0


def yolo_seg_lines(objects, width: int, height: int,
                   index: Dict[str, int]) -> List[str]:
    """YOLO-seg label lines for one image's outlines."""
    lines = []
    for obj in objects or []:
        label = str(obj.get("label", ""))
        if label not in index:
            continue
        rings = seg.outline_polygons(obj, width, height)
        if not rings:
            continue
        ring = seg.simplify(max(rings, key=_area), 128)
        coords = " ".join("%.6f %.6f" % (min(max(x / width, 0.0), 1.0),
                                         min(max(y / height, 0.0), 1.0))
                          for x, y in ring)
        lines.append("%d %s" % (index[label], coords))
    return lines


class UltralyticsSegmentTrainer(UltralyticsDetectTrainer):
    name: ClassVar[str] = "ultralytics-segment"
    description: ClassVar[str] = (
        "Instance segmentation with Ultralytics YOLO-seg, predicting polygons. "
        "AGPL-3.0: confirm the licence before the first run.")
    default_model: ClassVar[str] = "yolo11n-seg.pt"
    metric_keys: ClassVar[Tuple[Tuple[str, str], ...]] = (
        ("metrics/mAP50(M)", "map_50"), ("metrics/mAP50-95(M)", "map_50_95"))
    unit: ClassVar[str] = "outlines"

    def _label_lines(self, objects, width: int, height: int,
                     index: Dict[str, int]) -> List[str]:
        return yolo_seg_lines(objects, width, height, index)

    def _payload(self, result, labels: List[str], width: int, height: int,
                 version: str) -> List[Dict[str, Any]]:
        if result.masks is None:
            return []
        shapes = []
        for ring, score, cls in sorted(
                zip(result.masks.xy, result.boxes.conf.cpu().tolist(),
                    result.boxes.cls.cpu().tolist()), key=lambda t: -t[1]):
            if not 0 <= int(cls) < len(labels):
                continue
            ring = seg.simplify([[float(x), float(y)] for x, y in ring])
            shape = seg.client_polygon(ring, labels[int(cls)], score, width,
                                       height, version)
            if shape:
                shapes.append(shape)
        return shapes
