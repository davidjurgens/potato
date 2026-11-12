"""Shapes in and out of the instance-segmentation trainers.

In: an annotator's polygon, ellipse, freeform outline or brush mask as pixel
polygons. Boxes are not outlines: a box says where an object is, not which
pixels it covers, so a segmentation trainer leaves them out (and the
held-out score does too, see ``evaluation._score_geometry``).

Out: predicted outlines as the image widget's polygons, normalized, with
``source: "ai"`` and the model's score, so write-back shows them as shapes
the annotator can edit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Shape types that outline an object's pixels.
OUTLINE_TYPES = ("polygon", "ellipse", "freeform", "mask")

#: Vertex budget for a predicted outline. A traced mask has one vertex per
#: boundary pixel; hundreds of handles make a polygon impossible to edit.
MAX_VERTICES = 64


def outline_polygons(obj: Dict[str, Any], width: int,
                     height: int) -> List[List[List[float]]]:
    """An annotated shape as pixel polygons, ``[]`` for a box or point.

    A mask can have several pieces; each is its own polygon.
    """
    from potato.export.cv_utils import (normalize_annotation_object,
                                        rle_to_polygons)

    kind = obj.get("type")
    if kind not in OUTLINE_TYPES:
        return []
    if kind == "mask":
        rle = obj.get("rle") or {}
        size = rle.get("size") or []
        if len(size) < 2 or not rle.get("counts"):
            return []
        mask_h, mask_w = int(size[0]), int(size[1])
        sx, sy = width / float(mask_w), height / float(mask_h)
        return [[[x * sx, y * sy] for x, y in ring]
                for ring in rle_to_polygons(rle, mask_w, mask_h) if len(ring) >= 3]
    canonical = normalize_annotation_object(obj, width, height)
    points = (canonical or {}).get("points") or []
    return [points] if len(points) >= 3 else []


def rasterize(polygons: List[List[List[float]]], width: int, height: int):
    """A uint8 ``(height, width)`` mask of the polygons' union."""
    import numpy
    from PIL import Image, ImageDraw

    canvas = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    for ring in polygons:
        draw.polygon([(float(x), float(y)) for x, y in ring], fill=1)
    return numpy.asarray(canvas, dtype="uint8")


def simplify(ring: List[List[float]], max_vertices: int = MAX_VERTICES,
             tolerance: float = 1.0) -> List[List[float]]:
    """Fewer vertices: the outline to within *tolerance* pixels, and at most
    *max_vertices*. A traced mask has a vertex on every boundary pixel step;
    a triangle came back with 51."""
    if len(ring) <= 4:
        return ring
    try:
        from shapely.geometry import Polygon

        polygon = Polygon(ring)
        while True:
            reduced = polygon.simplify(tolerance, preserve_topology=True)
            coords = list(reduced.exterior.coords)[:-1]
            if len(coords) <= max_vertices or tolerance > 64:
                return [[float(x), float(y)] for x, y in coords]
            tolerance *= 2
    except Exception:  # noqa: BLE001 - shapely missing or a degenerate ring
        if len(ring) <= max_vertices:
            return ring
        step = len(ring) / float(max_vertices)
        return [ring[int(i * step)] for i in range(max_vertices)]


def mask_polygons(mask) -> List[List[List[float]]]:
    """Outer outlines of a boolean ``(height, width)`` array, in pixels."""
    import numpy

    mask = numpy.asarray(mask).astype("uint8")
    if not mask.any():
        return []
    try:
        import cv2

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        rings = [[[float(p[0][0]), float(p[0][1])] for p in c]
                 for c in contours]
    except ImportError:
        from potato.export.cv_utils import bitmap_to_rle, rle_to_polygons

        height, width = mask.shape
        rle = bitmap_to_rle(mask.reshape(-1).tolist(), height, width)
        rings = rle_to_polygons(rle, width, height)
    return [simplify(r) for r in rings if len(r) >= 3]


def client_polygon(ring: List[List[float]], label: str, score: float,
                   width: int, height: int, model_version: str
                   ) -> Optional[Dict[str, Any]]:
    """One outline as the image widget's polygon object."""
    if len(ring) < 3:
        return None
    return {"type": "polygon", "label": label, "color": "",
            "coordinates": [{"x": round(x / width, 5), "y": round(y / height, 5)}
                            for x, y in ring],
            "source": "ai", "ai_model": model_version,
            "confidence": round(float(score), 4)}
