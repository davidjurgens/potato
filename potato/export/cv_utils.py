"""
CV Export Utilities

Shared helper functions for computer vision export formats (COCO, YOLO, VOC).
"""

from typing import Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)


def build_category_mapping(annotations: List[dict], schemas: List[dict]) -> Dict[str, int]:
    """
    Build a mapping from label names to integer category IDs.

    Extracts labels from image_annotation schemas first (preserving config order),
    then discovers any additional labels from annotations.

    Args:
        annotations: List of annotation records
        schemas: List of annotation_scheme config dicts

    Returns:
        Dict mapping label name -> integer ID (starting from 1 for COCO, 0-indexed for YOLO)
    """
    labels = []
    seen = set()

    # First, collect labels from schema configs (preserves defined order)
    for schema in schemas:
        if schema.get("annotation_type") == "image_annotation":
            for label_def in schema.get("labels", []):
                name = label_def if isinstance(label_def, str) else label_def.get("name", "")
                if name and name not in seen:
                    labels.append(name)
                    seen.add(name)

    # Then discover any labels in annotation data not already in config
    for ann in annotations:
        for schema_name, img_annotations in ann.get("image_annotations", {}).items():
            if not isinstance(img_annotations, list):
                continue
            for obj in img_annotations:
                label = obj.get("label", "")
                if label and label not in seen:
                    labels.append(label)
                    seen.add(label)

    return {name: idx for idx, name in enumerate(labels)}


def polygon_to_bbox(points: List[List[float]]) -> Tuple[float, float, float, float]:
    """
    Compute axis-aligned bounding box from a polygon.

    Args:
        points: List of [x, y] coordinate pairs

    Returns:
        Tuple of (x_min, y_min, width, height)
    """
    if not points:
        return (0, 0, 0, 0)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min = min(xs)
    y_min = min(ys)
    return (x_min, y_min, max(xs) - x_min, max(ys) - y_min)


def polygon_area(points: List[List[float]]) -> float:
    """
    Compute the area of a polygon using the shoelace formula.

    Args:
        points: List of [x, y] coordinate pairs

    Returns:
        Absolute area of the polygon
    """
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0


def normalize_bbox(x: float, y: float, w: float, h: float,
                   img_w: float, img_h: float) -> Tuple[float, float, float, float]:
    """
    Normalize bounding box coordinates to [0, 1] range.

    Args:
        x, y: Top-left corner coordinates
        w, h: Width and height
        img_w, img_h: Image dimensions

    Returns:
        Tuple of (center_x, center_y, width, height) normalized to [0, 1]
    """
    if img_w <= 0 or img_h <= 0:
        return (0, 0, 0, 0)
    cx = (x + w / 2) / img_w
    cy = (y + h / 2) / img_h
    nw = w / img_w
    nh = h / img_h
    return (cx, cy, nw, nh)


def flatten_polygon(points: List[List[float]]) -> List[float]:
    """
    Flatten a list of [x, y] points into a flat coordinate list [x1, y1, x2, y2, ...].

    This is the format used by COCO segmentation.

    Args:
        points: List of [x, y] coordinate pairs

    Returns:
        Flat list of coordinates
    """
    result = []
    for p in points:
        result.extend(p[:2])
    return result


def extract_image_annotations(annotation: dict) -> List[Tuple[str, List[dict]]]:
    """
    Extract image annotation objects from an annotation record.

    Args:
        annotation: Single annotation record with image_annotations field

    Returns:
        List of (schema_name, annotation_objects) tuples
    """
    results = []
    for schema_name, objects in annotation.get("image_annotations", {}).items():
        if isinstance(objects, list) and objects:
            results.append((schema_name, objects))
    return results


def get_image_dimensions(item: dict, default_width: int = 0,
                         default_height: int = 0) -> Tuple[int, int]:
    """
    Extract image dimensions from item metadata.

    Checks common field names for image width/height.

    Args:
        item: Item data dict
        default_width: Fallback width
        default_height: Fallback height

    Returns:
        Tuple of (width, height)
    """
    # Check common field patterns
    for w_key in ("image_width", "width", "img_width", "w"):
        if w_key in item:
            width = int(item[w_key])
            break
    else:
        width = default_width

    for h_key in ("image_height", "height", "img_height", "h"):
        if h_key in item:
            height = int(item[h_key])
            break
    else:
        height = default_height

    return (width, height)


def get_image_filename(item: dict) -> Optional[str]:
    """
    Extract image filename from item data.

    Args:
        item: Item data dict

    Returns:
        Image filename/path string or None
    """
    for key in ("image", "image_path", "image_url", "file_name", "filename", "img"):
        if key in item and item[key]:
            return str(item[key])
    return None
