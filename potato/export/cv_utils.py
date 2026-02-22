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


# ---------------------------------------------------------------------------
# RLE mask utilities (Potato RLE <-> COCO RLE conversion)
# ---------------------------------------------------------------------------


def decode_rle(rle: dict, width: int, height: int) -> List[int]:
    """
    Decode Potato RLE-encoded mask to a flat binary array (row-major order).

    Potato RLE stores counts alternating between 0-pixels and 1-pixels,
    starting with 0s, in row-major (left-to-right, top-to-bottom) order.

    Args:
        rle: Dict with 'counts' (list of ints) and 'size' [height, width]
        width: Image width
        height: Image height

    Returns:
        Flat list of 0/1 values in row-major order
    """
    counts = rle.get("counts", [])
    total = width * height
    mask = [0] * total
    pos = 0
    val = 0
    for count in counts:
        for _ in range(count):
            if pos < total:
                mask[pos] = val
                pos += 1
        val = 1 - val
    return mask


def rle_bbox(mask: List[int], width: int, height: int) -> List[float]:
    """
    Compute axis-aligned bounding box [x, y, w, h] from a flat binary mask.

    Args:
        mask: Flat list of 0/1 values (row-major)
        width: Image width
        height: Image height

    Returns:
        [x_min, y_min, bbox_width, bbox_height] or [0, 0, 0, 0] if empty
    """
    x_min, y_min = width, height
    x_max, y_max = -1, -1
    for i, val in enumerate(mask):
        if val:
            y = i // width
            x = i % width
            if x < x_min:
                x_min = x
            if x > x_max:
                x_max = x
            if y < y_min:
                y_min = y
            if y > y_max:
                y_max = y
    if x_max < 0:
        return [0, 0, 0, 0]
    return [float(x_min), float(y_min),
            float(x_max - x_min + 1), float(y_max - y_min + 1)]


def rle_area(mask: List[int]) -> int:
    """
    Compute mask area as the count of foreground pixels.

    Args:
        mask: Flat list of 0/1 values

    Returns:
        Number of 1-pixels
    """
    return sum(mask)


def _column_major_rle_counts(mask_2d: List[List[int]], height: int,
                              width: int) -> List[int]:
    """
    Read a 2D mask in column-major order and compute RLE counts.

    Counts alternate between 0-pixels and 1-pixels, starting with 0s.

    Args:
        mask_2d: 2D list [height][width] of 0/1 values
        height: Image height
        width: Image width

    Returns:
        List of integer run counts in column-major order
    """
    counts: List[int] = []
    current_val = 0
    current_run = 0

    for x in range(width):
        for y in range(height):
            pixel = mask_2d[y][x]
            if pixel == current_val:
                current_run += 1
            else:
                counts.append(current_run)
                current_val = 1 - current_val
                current_run = 1
    counts.append(current_run)
    return counts


def _encode_coco_rle_string(counts: List[int]) -> str:
    """
    Encode RLE integer counts as a COCO compressed ASCII string.

    Implements the exact algorithm from pycocotools maskApi.c rleToString():
    - Delta encoding for i > 2: x = counts[i] - counts[i-2]
    - Each value encoded as 6-bit groups (5 data bits + 1 continuation bit)
    - Each group offset by 48 to produce printable ASCII
    - Signed values supported via arithmetic right shift

    Args:
        counts: List of integer run counts

    Returns:
        Encoded ASCII string
    """
    chars = []
    for i, cnt in enumerate(counts):
        # Delta encoding: for i > 2, encode difference from counts[i-2]
        x = cnt - counts[i - 2] if i > 2 else cnt
        while True:
            c = x & 0x1F
            x >>= 5
            # If bit 4 set, sign bit is 1 → more groups unless x is all-ones (-1)
            # If bit 4 clear, sign bit is 0 → more groups unless x is all-zeros (0)
            if c & 0x10:
                more = (x != -1)
            else:
                more = (x != 0)
            if more:
                c |= 0x20
            chars.append(chr(c + 48))
            if not more:
                break
    return "".join(chars)


def rle_to_coco_rle(rle: dict, width: int, height: int) -> Dict[str, Any]:
    """
    Convert Potato RLE to COCO RLE format.

    Potato RLE is row-major; COCO RLE is column-major with compressed
    ASCII string encoding.

    Args:
        rle: Potato RLE dict with 'counts' and 'size'
        width: Image width
        height: Image height

    Returns:
        COCO RLE dict {"counts": "encoded_string", "size": [height, width]}
    """
    # Decode to flat row-major mask
    flat = decode_rle(rle, width, height)

    # Reshape to 2D
    mask_2d = []
    for y in range(height):
        row = flat[y * width:(y + 1) * width]
        mask_2d.append(row)

    # Compute column-major RLE counts
    col_counts = _column_major_rle_counts(mask_2d, height, width)

    # Encode as COCO compressed string
    encoded = _encode_coco_rle_string(col_counts)

    return {"counts": encoded, "size": [height, width]}
