"""
CV Export Utilities

Shared helper functions for computer vision export formats (COCO, YOLO, VOC).
"""

from typing import Dict, List, Tuple, Any, Optional
import logging
import math
import os

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


#: Vertices used when approximating an ellipse as a polygon. 36 keeps the
#: worst-case radial error under 0.4% of the radius, which is well inside the
#: boundary noise of any human annotator, while staying small enough that COCO
#: segmentation lists remain readable.
ELLIPSE_POLYGON_VERTICES = 36


def ellipse_to_polygon(cx: float, cy: float, rx: float, ry: float,
                       angle: float = 0.0,
                       vertices: int = ELLIPSE_POLYGON_VERTICES
                       ) -> List[List[float]]:
    """
    Approximate an ellipse as a closed polygon in absolute pixels.

    Every exporter and IoU routine already understands polygons, so producing
    one here means ellipse support costs nothing downstream — the alternative
    is teaching each consumer the parametric form separately, which is how
    geometry types drift apart.

    ``angle`` is in degrees, clockwise, matching fabric's convention.
    """
    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    points: List[List[float]] = []
    for i in range(vertices):
        phi = 2.0 * math.pi * i / vertices
        ex, ey = rx * math.cos(phi), ry * math.sin(phi)
        points.append([cx + ex * cos_t - ey * sin_t,
                       cy + ex * sin_t + ey * cos_t])
    return points


def _coerce_keypoints(raw: Any) -> Tuple[List[List[float]], List[int]]:
    """
    Normalize a keypoint sequence to ``([[x, y], ...], [v, ...])``.

    Accepts the client's ``[{"x":..,"y":..,"v":..}, ...]`` form, the flat
    ``[[x, y, v], ...]`` form, and COCO's flat ``[x, y, v, x, y, v, ...]``.
    A missing visibility flag defaults to 2 (visible), because a point someone
    bothered to place is visible unless they said otherwise.
    """
    points: List[List[float]] = []
    vis: List[int] = []
    if not isinstance(raw, (list, tuple)) or not raw:
        return points, vis

    # COCO's flat triplet stream.
    if all(isinstance(v, (int, float)) for v in raw):
        for i in range(0, len(raw) - 2, 3):
            points.append([float(raw[i]), float(raw[i + 1])])
            vis.append(int(raw[i + 2]))
        return points, vis

    for p in raw:
        if isinstance(p, dict):
            points.append([float(p.get("x", 0) or 0), float(p.get("y", 0) or 0)])
            vis.append(int(p.get("v", 2) if p.get("v") is not None else 2))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            points.append([float(p[0]), float(p[1])])
            vis.append(int(p[2]) if len(p) >= 3 else 2)
    return points, vis


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
    cx = max(0.0, min(1.0, (x + w / 2) / img_w))
    cy = max(0.0, min(1.0, (y + h / 2) / img_h))
    nw = max(0.0, min(1.0, w / img_w))
    nh = max(0.0, min(1.0, h / img_h))
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


#: Dimensions read off disk, keyed by absolute path. An export walks every
#: annotation record, and two annotators on one image means two lookups for the
#: same file.
_DIMENSION_CACHE: Dict[str, Tuple[int, int]] = {}


def get_image_dimensions(item: dict, default_width: int = 0,
                         default_height: int = 0, *,
                         config: Any = None,
                         annotation: Any = None) -> Tuple[int, int]:
    """
    The image's pixel dimensions, from whichever source can supply them.

    In order: the item's own metadata, a mask's RLE size, the image file.

    A data file that names an image does not describe one, so for a study built
    in Potato the metadata keys are simply absent and this used to return
    ``(0, 0)``. Eleven exporters call it. YOLO refuses the export on a zero,
    which is right; COCO wrote the zero into its ``images`` record while the
    annotation beside it carried the true size, so the mask decoded correctly
    and only a consumer reading ``img['width']`` -- normalization, training,
    COCOeval -- saw the damage.

    Args:
        item: Item data dict
        default_width: Fallback width
        default_height: Fallback height
        config: Project config, used to locate the image on disk
        annotation: The annotation record for this item, whose mask RLE carries
            ``size`` as ``[height, width]``

    Returns:
        Tuple of (width, height)
    """
    # Check common field patterns
    width = default_width
    for w_key in ("image_width", "width", "img_width", "w"):
        if w_key in item:
            try:
                width = int(item[w_key])
            except (ValueError, TypeError):
                pass
            break

    height = default_height
    for h_key in ("image_height", "height", "img_height", "h"):
        if h_key in item:
            try:
                height = int(item[h_key])
            except (ValueError, TypeError):
                pass
            break

    if width > 0 and height > 0:
        return (width, height)

    # A mask states its own size and costs nothing to read. It is also the only
    # source that works when the image is remote or unreadable.
    derived = _dimensions_from_masks(annotation)
    if derived is None and config is not None:
        derived = _dimensions_from_file(config, item)
    if derived is not None:
        return derived

    return (width, height)


def _dimensions_from_masks(annotation: Any) -> Optional[Tuple[int, int]]:
    """``(width, height)`` from a stored mask's RLE, which holds [h, w]."""
    if not isinstance(annotation, dict):
        return None
    image_annotations = annotation.get("image_annotations")
    if not isinstance(image_annotations, dict):
        return None
    for objects in image_annotations.values():
        if not isinstance(objects, list):
            continue
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            size = (obj.get("rle") or {}).get("size") if isinstance(
                obj.get("rle"), dict) else None
            if isinstance(size, (list, tuple)) and len(size) >= 2:
                try:
                    height, width = int(size[0]), int(size[1])
                except (ValueError, TypeError):
                    continue
                if width > 0 and height > 0:
                    return (width, height)
    return None


def _dimensions_from_file(config: Any, item: dict) -> Optional[Tuple[int, int]]:
    """``(width, height)`` by opening the image the item names.

    Returns ``None`` rather than raising for every reason this can fail --
    no filename, a remote URL, a path outside the media directory, a missing
    file, Pillow absent. An export must not die because one image cannot be
    measured; the caller keeps its zeros and YOLO keeps refusing.
    """
    filename = get_image_filename(item)
    if not filename or "://" in str(filename):
        return None
    try:
        from potato.media.paths import resolve_media_path
    except ImportError:  # pragma: no cover
        return None

    reference = str(filename)
    for prefix in ("/media/", "media/"):
        if reference.startswith(prefix):
            reference = reference[len(prefix):]
            break
    reference = reference.lstrip("/")

    try:
        _, path = resolve_media_path(config, reference, context="export")
    except Exception:  # pragma: no cover - config shapes vary
        return None
    if not path:
        return None
    if path in _DIMENSION_CACHE:
        return _DIMENSION_CACHE[path]
    if not os.path.isfile(path):
        return None
    try:
        from PIL import Image
        with Image.open(path) as image:
            dimensions = (int(image.width), int(image.height))
    except Exception:
        logger.debug("export could not read the dimensions of %s", path)
        return None
    if dimensions[0] <= 0 or dimensions[1] <= 0:
        return None
    _DIMENSION_CACHE[path] = dimensions
    return dimensions


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


def _decode_coco_rle_string(s: str) -> List[int]:
    """
    Decode a COCO compressed ASCII RLE string back to integer counts.

    Exact inverse of :func:`_encode_coco_rle_string`, ported from pycocotools
    maskApi.c ``rleFrString()``.

    The delta boundary is ``> 2``, not ``>= 2`` -- it must mirror the encoder's
    ``x = counts[i] - counts[i - 2] if i > 2`` exactly. An off-by-one here
    corrupts every mask long enough to reach the third run, silently.

    Args:
        s: Encoded ASCII string

    Returns:
        List of integer run counts in column-major order
    """
    counts: List[int] = []
    p = 0
    n = len(s)
    while p < n:
        x = 0
        k = 0
        more = True
        while more:
            c = ord(s[p]) - 48
            x |= (c & 0x1F) << (5 * k)
            more = bool(c & 0x20)
            p += 1
            k += 1
            if not more and (c & 0x10):
                # Sign-extend: Python ints are arbitrary precision, so this
                # produces the correct negative value without masking.
                x |= -1 << (5 * k)
        if len(counts) > 2:
            x += counts[-2]
        counts.append(x)
    return counts


def coco_rle_to_rle(segmentation: dict) -> Dict[str, Any]:
    """
    Convert a COCO RLE segmentation to Potato RLE.

    Public inverse of :func:`rle_to_coco_rle`. Handles both COCO dialects
    without preprocessing:

    - ``{"counts": [ints], "size": [h, w]}``  -- uncompressed
    - ``{"counts": "ascii", "size": [h, w]}`` -- compressed

    COCO RLE is column-major; Potato RLE is row-major. Both alternate runs
    starting with a 0-run.

    Args:
        segmentation: COCO ``segmentation`` dict

    Returns:
        Potato RLE dict ``{"counts": [ints], "size": [height, width]}``

    Raises:
        ValueError: if ``size`` is missing or malformed
    """
    size = segmentation.get("size") or []
    if len(size) < 2:
        raise ValueError(
            f"COCO RLE segmentation needs size [height, width], got {size!r}"
        )
    height, width = int(size[0]), int(size[1])

    raw = segmentation.get("counts")
    if isinstance(raw, bytes):
        raw = raw.decode("ascii")
    if isinstance(raw, str):
        counts = _decode_coco_rle_string(raw)
    else:
        counts = [int(c) for c in (raw or [])]

    total = width * height

    # Expand column-major runs into a column-major bitmap.
    col_major = [0] * total
    pos = 0
    val = 0
    for count in counts:
        for _ in range(count):
            if pos < total:
                col_major[pos] = val
                pos += 1
        val = 1 - val

    # Transpose to row-major: column-major index i is (x=i//height, y=i%height).
    row_major = [0] * total
    for i, v in enumerate(col_major):
        if v:
            row_major[(i % height) * width + (i // height)] = 1

    return {"counts": _runs_from_bitmap(row_major), "size": [height, width]}


def _runs_from_bitmap(bitmap: List[int]) -> List[int]:
    """Re-run a flat 0/1 bitmap into alternating counts starting with 0s."""
    counts: List[int] = []
    current = 0
    run = 0
    for v in bitmap:
        if v == current:
            run += 1
        else:
            counts.append(run)
            current = 1 - current
            run = 1
    counts.append(run)
    return counts


def bitmap_to_rle(bitmap: List[int], height: int, width: int) -> Dict[str, Any]:
    """
    Encode a flat row-major 0/1 bitmap as a Potato RLE mask.

    The inverse of :func:`decode_rle`, and the entry point mask importers use
    when a format ships rasterized pixels rather than outlines (DAVIS and
    Cityscapes indexed PNGs, per-instance bitmaps). Exposed publicly so those
    importers do not each reach into a private helper and drift.

    Args:
        bitmap: Flat list of 0/1 values, ``width * height`` long, row-major
        height: Mask height in pixels
        width: Mask width in pixels

    Returns:
        Potato RLE dict ``{"counts": [ints], "size": [height, width]}``

    Raises:
        ValueError: If the bitmap length does not match the stated dimensions,
            which otherwise produces a mask that is silently sheared.
    """
    expected = width * height
    if len(bitmap) != expected:
        raise ValueError(
            f"bitmap has {len(bitmap)} pixels but {width}x{height} needs "
            f"{expected}; encoding it would shear the mask")
    return {"counts": _runs_from_bitmap(bitmap), "size": [height, width]}


def polygons_to_rle(polygons: List[Any], height: int, width: int) -> Dict[str, Any]:
    """
    Rasterize one or more polygons into a Potato RLE mask.

    Uses even-odd scanline fill, so a polygon fully inside another is treated
    as a hole -- which is how COCO's multi-ring ``segmentation`` lists encode
    holes.

    Args:
        polygons: List of rings. Each ring may be flat ``[x1, y1, x2, y2, ...]``
            (COCO's form) or ``[[x, y], ...]`` / ``[{"x":, "y":}, ...]``.
        height: Mask height in pixels
        width: Mask width in pixels

    Returns:
        Potato RLE dict ``{"counts": [ints], "size": [height, width]}``
    """
    edges = []
    for ring in polygons or []:
        if ring and isinstance(ring[0], (int, float)):
            pts = [[float(ring[i]), float(ring[i + 1])]
                   for i in range(0, len(ring) - 1, 2)]
        else:
            pts = _coerce_points(ring)
        if len(pts) < 3:
            continue
        for i in range(len(pts)):
            edges.append((pts[i], pts[(i + 1) % len(pts)]))

    bitmap = [0] * (width * height)
    for y in range(height):
        yc = y + 0.5
        crossings = []
        for (x0, y0), (x1, y1) in edges:
            if (y0 <= yc) == (y1 <= yc):
                continue
            crossings.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
        crossings.sort()
        row = y * width
        for i in range(0, len(crossings) - 1, 2):
            start = max(0, int(math.ceil(crossings[i] - 0.5)))
            end = min(width - 1, int(math.floor(crossings[i + 1] - 0.5)))
            for x in range(start, end + 1):
                bitmap[row + x] = 1

    return {"counts": _runs_from_bitmap(bitmap), "size": [height, width]}


def rle_to_polygons(rle: dict, width: int, height: int) -> List[List[List[float]]]:
    """
    Trace an RLE mask into one outer-boundary polygon per connected component.

    This is LOSSY and is only used behind an explicit opt-in:

    - Holes are dropped. A single outer ring cannot represent them.
    - The traced contour will not re-rasterize to exactly the source bitmap.
    - Boundaries follow pixel centers, so they sit half a pixel inside the mask.

    Prefer keeping RLE as RLE. This exists for teams who need polygon
    editability and accept the fidelity loss.

    Args:
        rle: Potato RLE dict
        width: Mask width
        height: Mask height

    Returns:
        List of rings, each a list of ``[x, y]`` points.
    """
    bitmap = decode_rle(rle, width, height)

    def at(x: int, y: int) -> int:
        if x < 0 or y < 0 or x >= width or y >= height:
            return 0
        return bitmap[y * width + x]

    seen = [False] * (width * height)
    rings: List[List[List[float]]] = []

    # 8-connected Moore neighborhood, clockwise from due east.
    neighborhood = [(1, 0), (1, 1), (0, 1), (-1, 1),
                    (-1, 0), (-1, -1), (0, -1), (1, -1)]

    for start_y in range(height):
        for start_x in range(width):
            if not at(start_x, start_y) or seen[start_y * width + start_x]:
                continue

            # Flood the component so we only trace it once.
            stack = [(start_x, start_y)]
            component = []
            seen[start_y * width + start_x] = True
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if (0 <= nx < width and 0 <= ny < height
                            and at(nx, ny) and not seen[ny * width + nx]):
                        seen[ny * width + nx] = True
                        stack.append((nx, ny))

            if len(component) < 3:
                continue

            # Moore-neighbor trace clockwise from the component's top-left.
            contour = [[float(start_x), float(start_y)]]
            cur = (start_x, start_y)
            backtrack = 4  # came from the west
            guard = 8 * len(component) + 16

            for _ in range(guard):
                found = False
                for step in range(1, 9):
                    idx = (backtrack + step) % 8
                    dx, dy = neighborhood[idx]
                    nx, ny = cur[0] + dx, cur[1] + dy
                    if at(nx, ny):
                        backtrack = (idx + 4 + 1) % 8
                        cur = (nx, ny)
                        contour.append([float(nx), float(ny)])
                        found = True
                        break
                if not found:
                    break
                if cur == (start_x, start_y):
                    contour.pop()
                    break

            if len(contour) >= 3:
                rings.append(contour)

    return rings


# ---------------------------------------------------------------------------
# Coordinate contract (client <-> exporter)
# ---------------------------------------------------------------------------
#
# The browser writes annotations in ONE shape, defined by
# ImageAnnotationManager._serializeAnnotations() / _getObjectCoordinates() in
# potato/static/image-annotation.js:
#
#   {"type": "bbox",     "label", "color", "coordinates": {x, y, width, height}}
#   {"type": "polygon",  "label", "color", "coordinates": [{x, y}, ...]}
#   {"type": "polyline", "label", "color", "coordinates": [{x, y}, ...]}
#   {"type": "ellipse",  "label", "color", "coordinates": {cx, cy, rx, ry, angle}}
#   {"type": "landmark", "label", "color", "coordinates": {x, y}}
#   {"type": "keypoint_set", "label", "color", "skeleton": "<name>",
#                            "coordinates": [{x, y, v}, ...]}
#   {"type": "cuboid_2d", "label", "color",
#                         "coordinates": {front: [{x,y} x4], back: [{x,y} x4]}}
#   {"type": "freeform", "label", "color", "coordinates": {path, left, top,
#                                                          scaleX, scaleY,
#                                                          pathOffset, angle}}
#   {"type": "mask",     "label", "color", "rle": {counts: [...], size: [h, w]}}
#
# Shape coordinates are NORMALIZED to [0, 1] against the image; masks are not.
# Freeform's `path` and `pathOffset` are the exception within `coordinates`:
# they stay in fabric's own path space, because that is the space `path` is
# expressed in and rescaling one without the other would be meaningless.
#
# Every exporter used to read flat, absolute-pixel fields (obj["x"],
# obj["points"], ...) that the client has never written. The result was that
# real annotation sessions exported bboxes as [0, 0, 0, 0] with area 0, and
# polygons hit `if not points: continue` and vanished silently -- only masks
# survived, because the mask half of the contract was fixed earlier (see the
# comment at image-annotation.js:1321). The unit tests hand-built the flat
# shape, so they passed while the exporters were broken.
#
# normalize_annotation_object() is now the single place that understands the
# client shape. to_client_object() is its exact inverse and is the only thing
# that should synthesize annotations for the client (used by the importers).
#
# THIS CONTRACT COVERS 2D ONLY. 3D spatial annotations (cuboid_3d, point_3d,
# polyline_3d, segment_3d) have their own pair in potato/export/spatial_utils.py
# and are NOT handled here. They are not normalized, they are in metres in a
# sensor frame rather than pixels, and they carry an orientation -- so they
# cannot pass through a function whose whole job is "normalized image
# coordinates to pixels, given a width and a height". See the module docstring
# there for the full reasoning.


def _coerce_points(raw: Any) -> List[List[float]]:
    """
    Normalize a point sequence to [[x, y], ...].

    Accepts the client's [{"x": .., "y": ..}, ...] form and the flat
    [[x, y], ...] form that legacy/hand-written data uses.
    """
    points: List[List[float]] = []
    if not isinstance(raw, (list, tuple)):
        return points
    for p in raw:
        if isinstance(p, dict):
            if "x" in p and "y" in p:
                points.append([float(p["x"]), float(p["y"])])
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            points.append([float(p[0]), float(p[1])])
    return points


def _get_dim(source: dict, *names: str, default: float = 0.0) -> float:
    """Read the first present key out of ``names`` as a float."""
    for name in names:
        if name in source and source[name] is not None:
            try:
                return float(source[name])
            except (TypeError, ValueError):
                return default
    return default


def _has_path_offset(coords: dict) -> bool:
    """True if a freeform annotation carries fabric's pathOffset."""
    offset = coords.get("pathOffset")
    return isinstance(offset, dict) and "x" in offset and "y" in offset


def _freeform_points(coords: dict, img_w: float, img_h: float) -> List[List[float]]:
    """
    Convert a freeform (fabric path) annotation to an absolute-pixel polyline.

    The client records {path, left, top, scaleX, scaleY, pathOffset, angle}.

    With ``pathOffset`` present the reconstruction is exact: fabric positions a
    path by treating ``pathOffset`` (the path bounding box's centre in the
    path's own coordinate space) as the object's origin, so the same transform
    fabric applies can be reproduced here, rotation included.

    Annotations written before the client recorded ``pathOffset`` can only be
    approximated: anchoring the path's own minimum corner at (left, top)
    reproduces the geometry for an unrotated, unscaled brush stroke and drifts
    otherwise. Callers surface the accompanying warning for that case only.
    """
    raw_path = coords.get("path") or []
    endpoints: List[List[float]] = []
    for cmd in raw_path:
        if not isinstance(cmd, (list, tuple)) or len(cmd) < 3:
            continue
        # Every fabric path command ends with its destination point.
        try:
            endpoints.append([float(cmd[-2]), float(cmd[-1])])
        except (TypeError, ValueError):
            continue

    if not endpoints:
        return []

    left = _get_dim(coords, "left") * img_w
    top = _get_dim(coords, "top") * img_h
    scale_x = _get_dim(coords, "scaleX", default=1.0) or 1.0
    scale_y = _get_dim(coords, "scaleY", default=1.0) or 1.0

    if not _has_path_offset(coords):
        min_x = min(p[0] for p in endpoints)
        min_y = min(p[1] for p in endpoints)
        return [
            [left + (p[0] - min_x) * scale_x, top + (p[1] - min_y) * scale_y]
            for p in endpoints
        ]

    offset = coords["pathOffset"]
    off_x = float(offset.get("x") or 0.0)
    off_y = float(offset.get("y") or 0.0)
    angle = math.radians(float(coords.get("angle") or 0.0))
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    points: List[List[float]] = []
    for px, py in endpoints:
        # Into the object's local space, then scale, rotate, translate --
        # the order fabric itself uses in calcTransformMatrix().
        lx = (px - off_x) * scale_x
        ly = (py - off_y) * scale_y
        points.append([
            left + lx * cos_a - ly * sin_a,
            top + lx * sin_a + ly * cos_a,
        ])
    return points


def normalize_annotation_object(obj: dict, img_w: float,
                                img_h: float) -> Optional[dict]:
    """
    Convert one stored image-annotation object into canonical absolute pixels.

    This accepts the shape the browser actually writes (normalized, nested
    under ``coordinates``) as well as the older flat absolute-pixel shape that
    hand-written fixtures and pre-2.x data use.

    The two are distinguished STRUCTURALLY, never by magnitude: a ``coordinates``
    key means the client shape. Guessing from magnitude is not possible --
    a 1x1 pixel box at the origin is [0, 0, 1, 1] in both coordinate spaces.

    Args:
        obj: One annotation object from ``annotation["image_annotations"][schema]``
        img_w: Image width in pixels
        img_h: Image height in pixels

    Returns:
        Canonical dict, or None if ``obj`` is not a usable annotation::

            {"type", "label", "color",
             "bbox": [x, y, w, h],          # absolute px, always present
             "points": [[x, y], ...] | None,  # absolute px
             "rle": {...} | None,             # passed through untouched
             "area": float,
             "instance": int | None,
             "iscrowd": 0 | 1,
             "warnings": [str]}
    """
    if not isinstance(obj, dict):
        return None

    obj_type = obj.get("type", "")
    warnings: List[str] = []

    result: Dict[str, Any] = {
        "type": obj_type,
        "label": obj.get("label", ""),
        "color": obj.get("color", ""),
        "bbox": None,
        "points": None,
        "rle": None,
        "area": 0.0,
        "instance": obj.get("instance"),
        "iscrowd": int(obj.get("iscrowd", 0) or 0),
        "warnings": warnings,
    }

    # Masks carry no `coordinates`; the RLE is already resolution-absolute.
    if obj_type == "mask":
        rle = obj.get("rle") or {}
        counts = rle.get("counts")
        if not counts:
            return None
        size = rle.get("size") or []
        mask_h = int(size[0]) if len(size) >= 2 else int(img_h)
        mask_w = int(size[1]) if len(size) >= 2 else int(img_w)
        decoded = decode_rle(rle, mask_w, mask_h)
        result["rle"] = rle
        result["bbox"] = rle_bbox(decoded, mask_w, mask_h)
        result["area"] = float(rle_area(decoded))
        # A brush mask with no explicit flag is keyed by label, so it merges
        # every stroke of that class into one region -- which is exactly what
        # COCO means by iscrowd=1. Imported per-instance masks carry an
        # explicit iscrowd=0 and an instance index, and keep them.
        crowd = obj.get("iscrowd", 1)
        result["iscrowd"] = 1 if crowd is None else int(crowd)
        return result

    coords = obj.get("coordinates")
    normalized = coords is not None

    if obj_type == "bbox":
        source = coords if normalized else obj
        if not isinstance(source, dict):
            return None
        x = _get_dim(source, "x")
        y = _get_dim(source, "y")
        w = _get_dim(source, "width", "w")
        h = _get_dim(source, "height", "h")
        if normalized:
            x, y, w, h = x * img_w, y * img_h, w * img_w, h * img_h
        result["bbox"] = [x, y, w, h]
        result["area"] = float(w * h)
        return result

    if obj_type == "polygon":
        raw = coords if normalized else obj.get("points")
        points = _coerce_points(raw)
        if not points:
            return None
        if normalized:
            points = [[p[0] * img_w, p[1] * img_h] for p in points]
        result["points"] = points
        bx, by, bw, bh = polygon_to_bbox(points)
        result["bbox"] = [bx, by, bw, bh]
        result["area"] = polygon_area(points)
        return result

    if obj_type == "polyline":
        # An OPEN path: lane markings, vessels, cracks, coastlines. It has
        # length but no interior, so `area` stays 0 and the bbox is the extent
        # of the vertices. Treating it as a closed polygon would invent an
        # interior the annotator never claimed.
        raw = coords if normalized else obj.get("points")
        points = _coerce_points(raw)
        if len(points) < 2:
            return None
        if normalized:
            points = [[p[0] * img_w, p[1] * img_h] for p in points]
        result["points"] = points
        result["bbox"] = list(polygon_to_bbox(points))
        result["area"] = 0.0
        result["closed"] = False
        return result

    if obj_type == "ellipse":
        source = coords if normalized else obj
        if not isinstance(source, dict):
            return None
        cx = _get_dim(source, "cx", "x")
        cy = _get_dim(source, "cy", "y")
        rx = _get_dim(source, "rx")
        ry = _get_dim(source, "ry")
        angle = float(source.get("angle", 0.0) or 0.0)
        if normalized:
            cx, cy, rx, ry = cx * img_w, cy * img_h, rx * img_w, ry * img_h
        if rx <= 0 or ry <= 0:
            return None

        result["ellipse"] = {"cx": cx, "cy": cy, "rx": rx, "ry": ry,
                             "angle": angle}
        # A polygon approximation so every exporter that understands polygons
        # understands ellipses for free, rather than each learning the maths.
        result["points"] = ellipse_to_polygon(cx, cy, rx, ry, angle)
        # The tight bbox of a ROTATED ellipse is not the rotated corner box:
        # half-extents are sqrt((rx cos)^2 + (ry sin)^2) and its transpose.
        theta = math.radians(angle)
        hw = math.hypot(rx * math.cos(theta), ry * math.sin(theta))
        hh = math.hypot(rx * math.sin(theta), ry * math.cos(theta))
        result["bbox"] = [cx - hw, cy - hh, 2 * hw, 2 * hh]
        result["area"] = math.pi * rx * ry
        return result

    if obj_type == "freeform":
        if normalized and isinstance(coords, dict) and "path" in coords:
            points = _freeform_points(coords, img_w, img_h)
            # The client records pathOffset since the path:created fix; older
            # annotations predate it and can only be approximated. Warn about
            # the ones that are actually approximate rather than all of them.
            if not _has_path_offset(coords):
                warnings.append(
                    "freeform reconstructed from a fabric path without pathOffset; "
                    "geometry is approximate. Re-saving this annotation in the "
                    "browser records the offset and makes it exact."
                )
        else:
            raw = coords if normalized else obj.get("points")
            points = _coerce_points(raw)
            if normalized:
                points = [[p[0] * img_w, p[1] * img_h] for p in points]
        if not points:
            return None
        result["points"] = points
        bx, by, bw, bh = polygon_to_bbox(points)
        result["bbox"] = [bx, by, bw, bh]
        result["area"] = polygon_area(points)
        return result

    if obj_type == "keypoint_set":
        # An ORDERED set with COCO visibility flags (0 unlabelled, 1 labelled
        # but occluded, 2 visible). Order is the whole point — index 5 means
        # "left shoulder" only because the skeleton says so — which is why this
        # is one object rather than N landmarks. Exploding it into landmarks (as
        # the COCO importer used to) loses the ordering, the skeleton, and the
        # visibility flags, and there is no way to reassemble them on export.
        raw = coords if normalized else obj.get("keypoints")
        points, vis = _coerce_keypoints(raw)
        if not points:
            return None
        if normalized:
            points = [[p[0] * img_w, p[1] * img_h] for p in points]

        result["points"] = points
        result["visibility"] = vis
        result["skeleton"] = obj.get("skeleton") or ""
        # The bbox spans only the points the annotator actually marked; an
        # unlabelled keypoint is stored as (0, 0, 0) and would otherwise drag
        # the box to the image corner.
        marked = [p for p, v in zip(points, vis) if v]
        result["bbox"] = list(polygon_to_bbox(marked)) if marked else [0.0, 0.0, 0.0, 0.0]
        result["area"] = 0.0
        return result

    if obj_type == "cuboid_2d":
        # A 3D box PROJECTED into the image (KITTI-style), not true 3D — that
        # is Wave 8's `spatial_annotation`, which lives in sensor coordinates.
        source = coords if normalized else obj
        if not isinstance(source, dict):
            return None
        front = _coerce_points(source.get("front"))
        back = _coerce_points(source.get("back"))
        if len(front) != 4 or len(back) != 4:
            return None
        if normalized:
            front = [[p[0] * img_w, p[1] * img_h] for p in front]
            back = [[p[0] * img_w, p[1] * img_h] for p in back]

        result["front"] = front
        result["back"] = back
        # `points` is the full 8-vertex hull so consumers that only understand
        # point lists still get something usable.
        result["points"] = front + back
        result["bbox"] = list(polygon_to_bbox(front + back))
        # The visible extent is what a detector would be scored on, so area is
        # the front face rather than the whole hull.
        result["area"] = polygon_area(front)
        return result

    if obj_type == "landmark":
        source = coords if normalized else obj
        if not isinstance(source, dict):
            return None
        x = _get_dim(source, "x")
        y = _get_dim(source, "y")
        if normalized:
            x, y = x * img_w, y * img_h
        result["points"] = [[x, y]]
        result["bbox"] = [x, y, 0.0, 0.0]
        result["area"] = 0.0
        return result

    return None


def to_client_object(obj_type: str, label: str, color: str = "", *,
                     img_w: float, img_h: float,
                     bbox: Optional[List[float]] = None,
                     points: Optional[List[List[float]]] = None,
                     rle: Optional[dict] = None,
                     ellipse: Optional[dict] = None,
                     keypoints: Optional[Any] = None,
                     skeleton: str = "",
                     cuboid: Optional[dict] = None,
                     instance: Optional[int] = None,
                     iscrowd: int = 0) -> Optional[dict]:
    """
    Build one annotation object in the shape the browser expects.

    Exact inverse of :func:`normalize_annotation_object`. Inputs are absolute
    pixels; shape outputs are normalized to [0, 1]. This is the only function
    that should synthesize annotations for the client.

    Args:
        obj_type: One of bbox, polygon, polyline, ellipse, freeform, landmark, mask
        label: Label name (must match a label in the schema config)
        color: Display color
        img_w: Image width in pixels
        img_h: Image height in pixels
        bbox: [x, y, w, h] absolute pixels (bbox type)
        points: [[x, y], ...] absolute pixels (polygon/polyline/freeform/landmark)
        rle: Potato RLE dict, passed through untouched (mask type)
        ellipse: {cx, cy, rx, ry, angle} absolute pixels (ellipse type)
        instance: Optional instance index, used to key per-instance masks
        iscrowd: COCO crowd flag, preserved for round-tripping

    Returns:
        Client-shaped dict, or None if the inputs are unusable.
    """
    obj: Dict[str, Any] = {"type": obj_type, "label": label, "color": color}
    if instance is not None:
        obj["instance"] = instance
    if iscrowd:
        obj["iscrowd"] = int(iscrowd)

    if obj_type == "mask":
        if not rle or not rle.get("counts"):
            return None
        obj["rle"] = rle
        # Masks are the one type whose iscrowd default is 1 -- a brush mask is
        # keyed by label, so it merges every stroke of that class, which is what
        # COCO means by a crowd region. An imported per-instance mask therefore
        # has to say iscrowd=0 out loud; omitting it would silently promote it
        # back to a crowd region on export and collapse instance segmentation.
        obj["iscrowd"] = int(iscrowd)
        return obj

    if img_w <= 0 or img_h <= 0:
        return None

    if obj_type == "bbox":
        if not bbox or len(bbox) < 4:
            return None
        x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
        obj["coordinates"] = {
            "x": x / img_w,
            "y": y / img_h,
            "width": w / img_w,
            "height": h / img_h,
        }
        return obj

    if obj_type in ("polygon", "freeform", "polyline"):
        if not points:
            return None
        if obj_type == "polyline" and len(points) < 2:
            return None
        obj["coordinates"] = [
            {"x": p[0] / img_w, "y": p[1] / img_h} for p in points
        ]
        if obj_type == "polyline":
            obj["closed"] = False
        return obj

    if obj_type == "ellipse":
        if not ellipse:
            return None
        rx = float(ellipse.get("rx", 0) or 0)
        ry = float(ellipse.get("ry", 0) or 0)
        if rx <= 0 or ry <= 0:
            return None
        obj["coordinates"] = {
            "cx": float(ellipse.get("cx", 0) or 0) / img_w,
            "cy": float(ellipse.get("cy", 0) or 0) / img_h,
            "rx": rx / img_w,
            "ry": ry / img_h,
            "angle": float(ellipse.get("angle", 0) or 0),
        }
        return obj

    if obj_type == "keypoint_set":
        pts, vis = _coerce_keypoints(keypoints if keypoints is not None else points)
        if not pts:
            return None
        obj["coordinates"] = [
            {"x": p[0] / img_w, "y": p[1] / img_h, "v": v}
            for p, v in zip(pts, vis)
        ]
        obj["skeleton"] = skeleton or ""
        return obj

    if obj_type == "cuboid_2d":
        front = _coerce_points((cuboid or {}).get("front"))
        back = _coerce_points((cuboid or {}).get("back"))
        if len(front) != 4 or len(back) != 4:
            return None
        obj["coordinates"] = {
            "front": [{"x": p[0] / img_w, "y": p[1] / img_h} for p in front],
            "back": [{"x": p[0] / img_w, "y": p[1] / img_h} for p in back],
        }
        return obj

    if obj_type == "landmark":
        if not points:
            return None
        obj["coordinates"] = {
            "x": points[0][0] / img_w,
            "y": points[0][1] / img_h,
        }
        return obj

    return None


def build_coco_category_map(
    schemas: List[dict], annotations: List[dict]
) -> Tuple[Dict[str, int], List[dict]]:
    """
    Build COCO category IDs, honoring original IDs when the config carries them.

    COCO datasets in the wild use sparse category IDs -- COCO 2017 runs 1..90
    with gaps. Renumbering them densely on export means a file cannot survive
    an import/export round trip, so a ``label_id`` recorded on the label config
    (which the COCO importer writes) is preserved verbatim.

    Labels without a ``label_id`` are assigned IDs above the highest explicit
    one, so explicit and derived IDs never collide.

    This is deliberately separate from :func:`build_category_mapping`, which
    returns dense 0-indexed IDs that YOLO requires.

    Args:
        schemas: annotation_scheme config dicts
        annotations: Annotation records (to discover labels absent from config)

    Returns:
        (label name -> COCO category id, COCO ``categories`` list)
    """
    explicit: Dict[str, int] = {}
    supercategory: Dict[str, str] = {}
    ordered: List[str] = []
    seen = set()

    for schema in schemas:
        if schema.get("annotation_type") != "image_annotation":
            continue
        for label_def in schema.get("labels", []):
            if isinstance(label_def, str):
                name, meta = label_def, {}
            else:
                name, meta = label_def.get("name", ""), label_def
            if not name or name in seen:
                continue
            ordered.append(name)
            seen.add(name)
            if meta.get("label_id") is not None:
                try:
                    explicit[name] = int(meta["label_id"])
                except (TypeError, ValueError):
                    pass
            if meta.get("supercategory"):
                supercategory[name] = str(meta["supercategory"])

    for ann in annotations:
        for _schema_name, objects in ann.get("image_annotations", {}).items():
            if not isinstance(objects, list):
                continue
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                label = obj.get("label", "")
                if label and label not in seen:
                    ordered.append(label)
                    seen.add(label)

    category_map: Dict[str, int] = {}
    next_id = max(explicit.values(), default=0) + 1
    for name in ordered:
        if name in explicit:
            category_map[name] = explicit[name]
        else:
            category_map[name] = next_id
            next_id += 1

    categories = [
        {
            "id": category_map[name],
            "name": name,
            "supercategory": supercategory.get(name, ""),
        }
        for name in sorted(ordered, key=lambda n: category_map[n])
    ]
    return category_map, categories


def items_without_image_annotations(context: Any) -> List[str]:
    """Instance ids in the study that carry no image annotation from anyone.

    Every CV exporter here walks ``context.annotations``, so an item nobody
    marked produces no record and is absent from the output entirely -- no
    image entry, no empty annotation list, nothing. For detector training an
    image with no objects is a negative example, and dropping it changes what
    the model learns.
    """
    annotated = set()
    for annotation in getattr(context, "annotations", None) or []:
        if extract_image_annotations(annotation):
            annotated.add(annotation.get("instance_id", ""))
    return [iid for iid in (getattr(context, "items", None) or {})
            if iid not in annotated]


def blank_item_warning(context: Any, destination: str = "this export"):
    """The warning for items that carry no image annotation, or ``None``.

    Says nothing about whether they should be there -- most of these formats
    are annotation interchange rather than dataset manifests, and the right
    answer differs by format. What is not defensible is the silence: a
    researcher reconciling "I had 300 images" against a file listing 214
    cannot tell whether the rest errored or were simply blank.
    """
    blank = items_without_image_annotations(context)
    if not blank:
        return None
    shown = ", ".join(sorted(blank)[:5])
    more = f", and {len(blank) - 5} more" if len(blank) > 5 else ""
    return (
        f"{len(blank)} item(s) carry no image annotation and are absent from "
        f"{destination}: {shown}{more}. For detector training an image with "
        f"no objects is a negative example; if you need them, add them to the "
        f"output manually or export a format that lists images separately."
    )
