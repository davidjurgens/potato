"""Training detectors on images too large to train on whole.

A 40x pathology slide is about 100,000 x 80,000 pixels, and a satellite scene
or a large microscopy mosaic is not far behind. The detection and
segmentation trainers resize each image to a few hundred pixels, at which
size a nucleus is gone, and the bundle used to ship the whole file to every
remote host (``protocol._pack`` dereferences symlinks), gigabytes per run.

So a large image is cut into tiles **when the bundle is built**, on the
machine that has the file and openslide:

- train: the grid tiles that hold an annotated object, plus a sample of
  empty tiles (``background``, a share of the object tiles) so the model
  sees what is not an object; objects are clipped to each tile;
- val, test, unlabeled: every grid tile over tissue (all tiles of an image
  that is not a slide), capped at ``max_predict_tiles`` per image.

Split membership is decided per image before cutting, so tiles of one slide
never land in two splits. Each tile becomes a row of its own
(``<instance id>@<x>,<y>``) with ``parent_id`` and its place on the parent;
the parents, with their whole-image targets, go to ``tiling.jsonl``.

After prediction the worker maps every tile's objects back to the parent,
normalized to its full-resolution size (what the deep-zoom viewer stores),
and removes the duplicates the tile overlap produces: per label, the more
confident of two objects whose boxes overlap at IoU 0.5, or one of which
mostly lies inside the other. Held-out scores are computed on those merged
predictions against the parents' targets. An object larger than the
overlap is still found in pieces, one per tile; the overlap should be at
least the size of the objects being detected.

Readers: openslide for slide formats (``potato/media/slides.py``), Pillow for
anything else. Standard library apart from those and numpy (tissue).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = ["DEFAULTS", "TILED_KINDS", "PARENTS_FILE", "settings", "tile_rows",
           "clip_object", "to_parent", "merge", "stitch_file", "scoring_rows"]

#: Kinds whose targets are shapes on the image, the only ones tiling applies to.
TILED_KINDS = ("geometry", "geo", "acoustic")

PARENTS_FILE = "tiling.jsonl"

DEFAULTS: Dict[str, Any] = {
    # auto: tile slides and images whose longer side is at least
    # auto_min_side; true: tile every image; false: never.
    "enabled": "auto",
    "auto_min_side": 4096,
    "tile_size": 1024,
    "overlap": 128,
    # Full-resolution pixels per tile pixel. ``mpp`` (microns per pixel)
    # picks it from the slide's own resolution instead.
    "downsample": 1.0,
    "mpp": None,
    "background": 0.25,
    "max_predict_tiles": 2000,
    # Share of an object that must be inside a tile for it to be a training
    # object there.
    "min_visible": 0.4,
    # Share of a tile that must be tissue (slides only) to predict on it.
    "tissue_threshold": 0.05,
}

#: A clipped piece of a large object is still worth training on when it
#: covers this share of the tile, however small a share of the object it is.
_TILE_COVER = 0.25

#: Pillow decodes the whole image; above this many pixels it is refused
#: rather than allowed to exhaust memory. A slide goes through openslide.
_MAX_FLAT_PIXELS = 1_000_000_000

#: Masks larger than this many pixels are not decoded for clipping.
_MAX_MASK_PIXELS = 64_000_000


class TilingError(ValueError):
    pass


def settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """``model_training.tiling`` over the defaults, checked."""
    raw = ((config or {}).get("model_training") or {}).get("tiling")
    if raw is None:
        raw = {}
    elif raw is True:
        raw = {"enabled": True}
    elif raw is False:
        raw = {"enabled": False}
    if not isinstance(raw, dict):
        raise TilingError("model_training.tiling must be a mapping, true or false")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise TilingError("model_training.tiling has unknown key(s): %s"
                          % ", ".join(sorted(unknown)))
    out = dict(DEFAULTS, **raw)
    if out["enabled"] not in ("auto", True, False):
        raise TilingError("model_training.tiling.enabled must be auto, true or false")
    for key in ("tile_size", "max_predict_tiles", "auto_min_side"):
        if not isinstance(out[key], int) or out[key] < 1:
            raise TilingError("model_training.tiling.%s must be a positive integer" % key)
    if not isinstance(out["overlap"], int) or not 0 <= out["overlap"] * 2 <= out["tile_size"]:
        # Past half a tile, the grid grows with the square of the overlap:
        # 511 on 512-pixel tiles made 6 million tiles of a 3000-pixel image.
        raise TilingError("model_training.tiling.overlap must be at least 0 and at most "
                          "half of tile_size")
    try:
        out["downsample"] = float(out["downsample"])
    except (TypeError, ValueError):
        raise TilingError("model_training.tiling.downsample must be a number")
    if out["downsample"] < 1:
        raise TilingError("model_training.tiling.downsample must be at least 1")
    for key in ("background", "min_visible", "tissue_threshold"):
        if not isinstance(out[key], (int, float)) or out[key] < 0:
            raise TilingError("model_training.tiling.%s must be a number >= 0" % key)
    if out["mpp"] is not None and (not isinstance(out["mpp"], (int, float))
                                   or out["mpp"] <= 0):
        raise TilingError("model_training.tiling.mpp must be a positive number")
    return out


# ------------------------------------------------------------------ readers

class _Reader:
    """Regions of one image at full-resolution coordinates."""

    slide = False
    mpp: Optional[float] = None

    def __init__(self, path: str):
        self.path = path
        self.size: Tuple[int, int] = (0, 0)

    def read(self, x: int, y: int, w: int, h: int, out_w: int, out_h: int):
        raise NotImplementedError

    def thumbnail(self, longest: int):
        raise NotImplementedError

    def close(self):
        pass


class _SlideReader(_Reader):
    slide = True

    def __init__(self, path: str):
        super().__init__(path)
        from potato.media.slides import _openslide
        openslide = _openslide()
        self._slide = openslide.OpenSlide(path)
        self.size = tuple(self._slide.dimensions)
        try:
            self.mpp = float(self._slide.properties.get("openslide.mpp-x"))
        except (TypeError, ValueError):
            self.mpp = None

    def read(self, x, y, w, h, out_w, out_h):
        from PIL import Image
        downsample = w / float(out_w)
        level = self._slide.get_best_level_for_downsample(downsample)
        scale = self._slide.level_downsamples[level]
        size = (max(1, int(math.ceil(w / scale))), max(1, int(math.ceil(h / scale))))
        region = self._slide.read_region((int(x), int(y)), level, size)
        # Transparent where the scan has no data: white, like a glass slide.
        background = Image.new("RGB", region.size, (255, 255, 255))
        background.paste(region, mask=region.split()[3])
        if background.size != (out_w, out_h):
            background = background.resize((out_w, out_h), Image.BILINEAR)
        return background

    def thumbnail(self, longest):
        return self._slide.get_thumbnail((longest, longest)).convert("RGB")

    def close(self):
        self._slide.close()


class _FlatReader(_Reader):
    def __init__(self, path: str):
        super().__init__(path)
        from PIL import Image
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(path) as probe:
                self.size = tuple(probe.size)
            if self.size[0] * self.size[1] > _MAX_FLAT_PIXELS:
                raise TilingError(
                    "%s is %d x %d pixels, too large to decode whole. Convert it "
                    "to a tiled pyramidal TIFF that openslide reads."
                    % (os.path.basename(path), self.size[0], self.size[1]))
            self._image = Image.open(path).convert("RGB")
        finally:
            Image.MAX_IMAGE_PIXELS = previous

    def read(self, x, y, w, h, out_w, out_h):
        from PIL import Image
        region = self._image.crop((int(x), int(y), int(x + w), int(y + h)))
        if region.size != (out_w, out_h):
            region = region.resize((out_w, out_h), Image.BILINEAR)
        return region

    def thumbnail(self, longest):
        copy = self._image.copy()
        copy.thumbnail((longest, longest))
        return copy

    def close(self):
        self._image.close()


def _open(path: str) -> _Reader:
    from potato.media.slides import is_slide
    if is_slide(path):
        return _SlideReader(path)
    return _FlatReader(path)


def _image_size(path: str) -> Optional[Tuple[int, int]]:
    """Full-resolution size from the header, without decoding."""
    try:
        from potato.media.slides import is_slide
        if is_slide(path):
            from potato.media.slides import _openslide
            slide = _openslide().OpenSlide(path)
            try:
                return tuple(slide.dimensions)
            finally:
                slide.close()
        from PIL import Image
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(path) as probe:
                return tuple(probe.size)
        finally:
            Image.MAX_IMAGE_PIXELS = previous
    except Exception:
        return None


def wants_tiling(path: str, opts: Dict[str, Any]) -> bool:
    """Whether the image at *path* is tiled under *opts*."""
    if opts["enabled"] is False:
        return False
    if opts["enabled"] is True:
        return True
    from potato.media.slides import SLIDE_EXTENSIONS
    if os.path.splitext(path)[1].lower() in SLIDE_EXTENSIONS:
        return True
    size = _image_size(path)
    return bool(size and max(size) >= opts["auto_min_side"])


# ------------------------------------------------------------------ geometry

def grid(width: int, height: int, region: int, stride: int) -> List[Tuple[int, int, int, int]]:
    """``(x, y, w, h)`` tiles of side *region* every *stride* pixels, the
    last row and column shifted back to end at the edge rather than run off
    it. An image smaller than a tile is one tile of its own size."""
    def starts(length):
        if length <= region:
            return [0]
        out = list(range(0, length - region + 1, stride))
        if out[-1] + region < length:
            out.append(length - region)
        return out
    return [(x, y, min(region, width), min(region, height))
            for y in starts(height) for x in starts(width)]


def _box_of(points: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _area(ring: Sequence[Sequence[float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                   in zip(ring, list(ring[1:]) + [ring[0]]))) / 2.0


def _clip_ring(ring: Sequence[Sequence[float]], x0: float, y0: float,
               x1: float, y1: float) -> List[List[float]]:
    """Sutherland-Hodgman: *ring* clipped to the rectangle. A concave ring
    can come back with zero-width bridges along the edge, which rasterize to
    nothing, so the area and the mask are right."""
    def clip(points, inside, cross):
        out = []
        for n, current in enumerate(points):
            previous = points[n - 1]
            if inside(current):
                if not inside(previous):
                    out.append(cross(previous, current))
                out.append(current)
            elif inside(previous):
                out.append(cross(previous, current))
        return out

    def at_x(x):
        return lambda a, b: [x, a[1] + (b[1] - a[1]) * (x - a[0]) / ((b[0] - a[0]) or 1e-12)]

    def at_y(y):
        return lambda a, b: [a[0] + (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-12), y]

    points = [list(map(float, p)) for p in ring]
    for inside, cross in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                          (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not points:
            break
        points = clip(points, inside, cross)
    return points


def clip_object(obj: Dict[str, Any], tile: Tuple[int, int, int, int],
                width: int, height: int, min_visible: float) -> List[Dict[str, Any]]:
    """An object on the parent (normalized to *width* x *height*) as zero or
    more objects normalized to *tile*.

    Kept when at least *min_visible* of it is inside, or when the piece
    inside covers a quarter of the tile: a gland that spans ten tiles is
    still gland in each of them. A box stays a box; an outline (polygon,
    ellipse, freeform, mask) becomes a polygon per piece; a landmark is kept
    when it is inside."""
    from potato.export.cv_utils import normalize_annotation_object
    from potato.training.trainers._segmentation import OUTLINE_TYPES, outline_polygons
    tx, ty, tw, th = tile
    kind = obj.get("type")
    extra = {k: obj[k] for k in ("label", "attributes") if k in obj}

    def keep(inside_area, whole_area):
        if whole_area <= 0 or inside_area <= 0:
            return False
        return inside_area / whole_area >= min_visible or \
            inside_area / float(tw * th) >= _TILE_COVER

    if kind == "bbox":
        canonical = normalize_annotation_object(obj, width, height)
        if not canonical or not canonical.get("bbox"):
            return []
        x, y, w, h = (float(v) for v in canonical["bbox"][:4])
        ix0, iy0 = max(x, tx), max(y, ty)
        ix1, iy1 = min(x + w, tx + tw), min(y + h, ty + th)
        if ix1 <= ix0 or iy1 <= iy0 or not keep((ix1 - ix0) * (iy1 - iy0), w * h):
            return []
        return [dict(extra, type="bbox", coordinates={
            "x": (ix0 - tx) / tw, "y": (iy0 - ty) / th,
            "width": (ix1 - ix0) / tw, "height": (iy1 - iy0) / th})]

    if kind in OUTLINE_TYPES:
        if kind == "mask":
            size = (obj.get("rle") or {}).get("size") or [0, 0]
            if len(size) < 2 or size[0] * size[1] > _MAX_MASK_PIXELS:
                return []
        out = []
        for ring in outline_polygons(obj, width, height):
            whole = _area(ring)
            clipped = _clip_ring(ring, tx, ty, tx + tw, ty + th)
            if len(clipped) < 3 or not keep(_area(clipped), whole):
                continue
            out.append(dict(extra, type="polygon", coordinates=[
                {"x": (px - tx) / tw, "y": (py - ty) / th} for px, py in clipped]))
        return out

    if kind == "landmark":
        coords = obj.get("coordinates") or {}
        try:
            px, py = float(coords["x"]) * width, float(coords["y"]) * height
        except (KeyError, TypeError, ValueError):
            return []
        if tx <= px < tx + tw and ty <= py < ty + th:
            return [dict(extra, type="landmark",
                         coordinates={"x": (px - tx) / tw, "y": (py - ty) / th})]
    return []


def to_parent(obj: Dict[str, Any], tile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A predicted object normalized to its tile, normalized to the parent."""
    x, y, w, h = tile["x"], tile["y"], tile["w"], tile["h"]
    width, height = float(tile["width"]), float(tile["height"])

    def point(p):
        return {"x": round((x + float(p["x"]) * w) / width, 6),
                "y": round((y + float(p["y"]) * h) / height, 6)}

    coords = obj.get("coordinates")
    out = dict(obj)
    try:
        if obj.get("type") == "bbox" and isinstance(coords, dict):
            corner = point(coords)
            out["coordinates"] = dict(corner, width=round(float(coords["width"]) * w / width, 6),
                                      height=round(float(coords["height"]) * h / height, 6))
        elif obj.get("type") in ("polygon", "polyline") and isinstance(coords, list):
            out["coordinates"] = [point(p) for p in coords]
        elif obj.get("type") == "landmark" and isinstance(coords, dict):
            out["coordinates"] = point(coords)
        elif obj.get("type") == "ellipse" and isinstance(coords, dict):
            centre = point({"x": coords["cx"], "y": coords["cy"]})
            out["coordinates"] = dict(coords, cx=centre["x"], cy=centre["y"],
                                      rx=float(coords["rx"]) * w / width,
                                      ry=float(coords["ry"]) * h / height)
        else:
            # A mask is in its tile's pixels; nothing the trainers here emit.
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return out


def _extent(obj: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    coords = obj.get("coordinates")
    if obj.get("type") == "bbox" and isinstance(coords, dict):
        x, y = float(coords["x"]), float(coords["y"])
        return x, y, x + float(coords["width"]), y + float(coords["height"])
    if isinstance(coords, list) and coords:
        return _box_of([(float(p["x"]), float(p["y"])) for p in coords])
    if isinstance(coords, dict) and "cx" in coords:
        return (coords["cx"] - coords["rx"], coords["cy"] - coords["ry"],
                coords["cx"] + coords["rx"], coords["cy"] + coords["ry"])
    if isinstance(coords, dict) and "x" in coords:
        x, y = float(coords["x"]), float(coords["y"])
        return x, y, x, y
    return None


#: Full-resolution pixels within which two tiles' points are one point.
_POINT_PIXELS = 4.0

#: How close, as a share of the tile, a box must come to an edge to be cut.
_EDGE = 0.005


def _touches_inner_edge(obj: Dict[str, Any], tile: Dict[str, Any]) -> bool:
    """Whether a shape, normalized to its tile, reaches an edge of the tile
    that another tile continues past (not the image's own border)."""
    extent = _extent(obj)
    if extent is None:
        return False
    x0, y0, x1, y1 = extent
    return ((x0 <= _EDGE and tile["x"] > 0)
            or (y0 <= _EDGE and tile["y"] > 0)
            or (x1 >= 1 - _EDGE and tile["x"] + tile["w"] < tile["width"])
            or (y1 >= 1 - _EDGE and tile["y"] + tile["h"] < tile["height"]))


def merge(objects: Iterable[Dict[str, Any]], iou: float = 0.5,
          contained: float = 0.8, point_tolerance: float = 0.0) -> List[Dict[str, Any]]:
    """Per label, most confident first: drop an object whose box overlaps a
    kept one at *iou* or more, and a point within *point_tolerance* of a
    kept one. When one box lies *contained* or more inside the other and the
    smaller was cut by its tile's inner edge (``_cut``, set by
    :func:`stitch_file`), it is the part of the object a neighbouring tile
    saw, so the larger one is kept, whichever was more confident, with the
    higher of the two confidences. An object inside another that was not cut
    is a real one (a nucleus in a cell) and stays."""
    def area(box):
        return max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)

    by_label: Dict[str, List[Tuple[Dict[str, Any], Tuple[float, ...]]]] = {}
    for obj in objects:
        extent = _extent(obj)
        if extent is not None:
            by_label.setdefault(str(obj.get("label")), []).append((obj, extent))
    kept: List[Dict[str, Any]] = []
    for entries in by_label.values():
        entries.sort(key=lambda e: -float(e[0].get("confidence") or 0.0))
        chosen: List[List[Any]] = []          # [object, box]
        for obj, box in entries:
            duplicate = False
            for slot in chosen:
                other = slot[1]
                ix = max(0.0, min(box[2], other[2]) - max(box[0], other[0]))
                iy = max(0.0, min(box[3], other[3]) - max(box[1], other[1]))
                inter = ix * iy
                union = area(box) + area(other) - inter
                smaller = min(area(box), area(other))
                # The epsilon: 4 px computed in normalized units came out
                # as 4.000000000000026 px, and the pair did not merge.
                same_point = area(box) == 0 and area(other) == 0 and math.hypot(
                    box[0] - other[0], box[1] - other[1]) <= point_tolerance + 1e-9
                cut = slot[0].get("_cut") if area(other) <= area(box) else obj.get("_cut")
                # Containment first: a cut piece half the size of the whole
                # overlaps it at IoU 0.5, and must not win as an overlap.
                if cut and smaller > 0 and inter / smaller >= contained:
                    duplicate = True
                    if area(box) > area(other):
                        best = max(float(obj.get("confidence") or 0.0),
                                   float(slot[0].get("confidence") or 0.0))
                        slot[0] = dict(obj, confidence=best) \
                            if obj.get("confidence") is not None else obj
                        slot[1] = box
                elif same_point or (union > 0 and inter / union >= iou):
                    duplicate = True
                if duplicate:
                    break
            if not duplicate:
                chosen.append([obj, box])
        kept.extend({k: v for k, v in slot[0].items() if k != "_cut"} for slot in chosen)
    kept.sort(key=lambda o: -float(o.get("confidence") or 0.0))
    return kept


# ------------------------------------------------------------------ bundle

def _tissue(reader: _Reader, tiles: Sequence[Tuple[int, int, int, int]],
            ) -> List[float]:
    """Share of each tile that is tissue, from a thumbnail: darker than
    Otsu's threshold on a slide's brightness. Everything else is all tissue."""
    if not reader.slide:
        return [1.0] * len(tiles)
    import numpy
    thumb = reader.thumbnail(1024).convert("L")
    gray = numpy.asarray(thumb, dtype="float64")
    hist, edges = numpy.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    best, threshold = -1.0, 200.0
    weight_sum = float((hist * numpy.arange(256)).sum())
    background_weight = background_sum = 0.0
    for level in range(256):
        background_weight += hist[level]
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += level * hist[level]
        mean_b = background_sum / background_weight
        mean_f = (weight_sum - background_sum) / foreground_weight
        between = background_weight * foreground_weight * (mean_b - mean_f) ** 2
        if between > best:
            best, threshold = between, level
    # Otsu puts the threshold at the darker class's top value: inclusive.
    mask = gray <= threshold
    sx = gray.shape[1] / float(reader.size[0])
    sy = gray.shape[0] / float(reader.size[1])
    out = []
    for x, y, w, h in tiles:
        x0, y0 = int(x * sx), int(y * sy)
        x1, y1 = max(x0 + 1, int(math.ceil((x + w) * sx))), max(y0 + 1, int(math.ceil((y + h) * sy)))
        window = mask[y0:y1, x0:x1]
        out.append(float(window.mean()) if window.size else 0.0)
    return out


def _downsample(reader: _Reader, opts: Dict[str, Any]) -> float:
    if opts.get("mpp") and reader.mpp:
        return max(1.0, float(opts["mpp"]) / reader.mpp)
    return float(opts["downsample"])


def tile_rows(rows: Sequence[Dict[str, Any]], split: str, bundle_root: str,
              media_dir: str, schema_names: Sequence[str], opts: Dict[str, Any],
              seed: int = 0, summary: Optional[Dict[str, Any]] = None
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Rows with each large image replaced by its tile rows, and the parents.

    *media_dir* is the bundle's media directory; tiles are written under
    ``<media_dir>/tiles/``. Rows whose image is not tiled pass through.
    """
    summary = summary if summary is not None else {}
    out: List[Dict[str, Any]] = []
    parents: List[Dict[str, Any]] = []
    rng = random.Random("%s:%s" % (seed, split))
    for row in rows:
        media = row.get("media")
        path = os.path.join(media_dir, media) if media and not str(media).startswith(
            ("http://", "https://")) else None
        if not path or not os.path.exists(path) or not wants_tiling(path, opts):
            out.append(row)
            continue
        try:
            reader = _open(path)
        except Exception as exc:  # noqa: BLE001
            summary.setdefault("unreadable", []).append(
                "%s: %s" % (row.get("instance_id"), exc))
            out.append(row)
            continue
        try:
            tiles, parent = _cut(row, reader, split, bundle_root, media_dir,
                                 schema_names, opts, rng, summary)
        finally:
            reader.close()
        out.extend(tiles)
        parents.append(parent)
    return out, parents


#: Most grid tiles one image may make. A 100,000-pixel slide at 1024 with
#: the default overlap is about 12,000.
MAX_GRID_TILES = 250_000


def _pixel_extent(obj: Dict[str, Any], width: int, height: int):
    """An object's box in full-resolution pixels, or None when it has none."""
    from potato.export.cv_utils import normalize_annotation_object
    try:
        canonical = normalize_annotation_object(obj, width, height) or {}
    except Exception:  # noqa: BLE001
        return None
    box = canonical.get("bbox")
    if not box:
        return None
    x, y, w, h = (float(v) for v in box[:4])
    return x, y, x + w, y + h


class _TileIndex:
    """The grid tiles a box overlaps, found by bisecting the tiles' starts
    (the grid is regular: one tile per (x start, y start))."""

    def __init__(self, tiles):
        self.at = {(t[0], t[1]): t for t in tiles}
        self.xs = sorted({t[0] for t in tiles})
        self.ys = sorted({t[1] for t in tiles})
        self.w = max((t[2] for t in tiles), default=0)
        self.h = max((t[3] for t in tiles), default=0)

    def over(self, reach):
        import bisect
        x0, y0, x1, y1 = reach
        xs = self.xs[bisect.bisect_right(self.xs, x0 - self.w):bisect.bisect_left(self.xs, x1)]
        ys = self.ys[bisect.bisect_right(self.ys, y0 - self.h):bisect.bisect_left(self.ys, y1)]
        return [self.at[(x, y)] for y in ys for x in xs if (x, y) in self.at]


def _most_tissue(tiles, fractions, limit: int):
    """The *limit* tiles with the most tissue, and among tiles with as much
    as each other, a seeded random sample over the image. Sorted by tissue
    alone, an ordinary image (every tile all tissue) kept its top strip.

    The cut-copy rule in :func:`merge` has one limit: a smaller object of the
    same label that touches an inner tile edge while lying inside a larger
    one is taken for a cut copy and merged into it."""
    ranked = sorted(zip(fractions, range(len(tiles))), key=lambda e: -e[0])
    cut = ranked[limit - 1][0]
    above = [i for f, i in ranked if f > cut]
    tied = sorted(i for f, i in ranked if f == cut)
    need = limit - len(above)
    # A seeded sample, not a stride: a stride equal to the number of grid
    # columns kept one column.
    spread = random.Random(len(tiles)).sample(tied, need)
    return sorted(tiles[i] for i in above + spread)


def _cut(row, reader, split, bundle_root, media_dir, schema_names, opts, rng, summary):
    width, height = reader.size
    downsample = _downsample(reader, opts)
    region = int(round(opts["tile_size"] * downsample))
    stride = int(round((opts["tile_size"] - opts["overlap"]) * downsample))
    tiles = grid(width, height, region, max(1, stride))
    targets = row.get("targets") or {}
    iid = str(row["instance_id"])

    if len(tiles) > MAX_GRID_TILES:
        raise TilingError(
            "%s would make %d tiles; raise model_training.tiling.downsample or "
            "tile_size, or lower overlap" % (iid, len(tiles)))
    # Each object is clipped only against the tiles its box reaches: all
    # against all was tiles x objects, 37 million clips on one large slide.
    pieces: Dict[Tuple[int, int, int, int], Dict[str, List[Dict[str, Any]]]] = {
        tile: {name: [] for name in schema_names if isinstance(targets.get(name), list)}
        for tile in tiles}
    index = _TileIndex(tiles)
    for name in schema_names:
        objects = targets.get(name)
        for obj in objects if isinstance(objects, list) else []:
            if not isinstance(obj, dict):
                continue
            reach = _pixel_extent(obj, width, height)
            for tile in (tiles if reach is None else index.over(reach)):
                pieces[tile][name].extend(
                    clip_object(obj, tile, width, height, opts["min_visible"]))

    if split == "train":
        with_objects = [t for t in tiles if any(pieces[t].values())]
        empty = [t for t in tiles if not any(pieces[t].values())]
        if empty and reader.slide:
            fractions = _tissue(reader, empty)
            empty = [t for t, f in zip(empty, fractions) if f >= opts["tissue_threshold"]]
        n_background = min(len(empty), int(math.ceil(len(with_objects) * opts["background"])))
        chosen = with_objects + rng.sample(empty, n_background)
    else:
        fractions = _tissue(reader, tiles)
        chosen = [t for t, f in zip(tiles, fractions) if f >= opts["tissue_threshold"]]
        if len(chosen) > opts["max_predict_tiles"]:
            chosen = _most_tissue(chosen, _tissue(reader, chosen), opts["max_predict_tiles"])
            summary.setdefault("capped", []).append(iid)

    folder = hashlib.sha1(iid.encode()).hexdigest()[:12]
    tile_dir = os.path.join(media_dir, "tiles", folder)
    os.makedirs(tile_dir, exist_ok=True)
    suffix = ".jpg" if reader.slide else ".png"
    tile_rows = []
    for x, y, w, h in chosen:
        name = "%d_%d%s" % (x, y, suffix)
        dest = os.path.join(tile_dir, name)
        out_w = max(1, int(round(w / downsample)))
        out_h = max(1, int(round(h / downsample)))
        if not os.path.exists(dest):
            image = reader.read(x, y, w, h, out_w, out_h)
            if suffix == ".jpg":
                image.save(dest, quality=92)
            else:
                image.save(dest)
        # Words are in the page's coordinates; a tile would need them cut too.
        tile_row = {k: v for k, v in row.items()
                    if k not in ("targets", "soft_targets", "media", "media_source",
                                 "instance_id", "prior", "words")}
        tile_row.update({
            "instance_id": "%s@%d,%d" % (iid, x, y), "parent_id": iid,
            "tile": {"x": x, "y": y, "w": w, "h": h, "width": width, "height": height},
            "media": os.path.join("tiles", folder, name)})
        if split != "unlabeled":
            tile_row["targets"] = {k: v for k, v in pieces[(x, y, w, h)].items()}
        if isinstance(row.get("prior"), list):
            clipped = [c for obj in row["prior"] if isinstance(obj, dict)
                       for c in clip_object(obj, (x, y, w, h), width, height,
                                            opts["min_visible"])]
            if clipped:
                tile_row["prior"] = clipped
            else:
                tile_row.pop("prior", None)
        tile_rows.append(tile_row)

    summary["n_items"] = summary.get("n_items", 0) + 1
    summary["n_tiles"] = summary.get("n_tiles", 0) + len(tile_rows)
    # The link to the whole image is pruned from the bundle; its tiles stand in.
    parent = {k: v for k, v in row.items() if k != "media"}
    parent.update(split=split, size=[width, height], downsample=downsample)
    return tile_rows, parent


# ------------------------------------------------------------------ worker

def _parents(bundle) -> Dict[str, Dict[str, Any]]:
    tiling = (getattr(bundle, "manifest", None) or {}).get("tiling") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if not tiling:
        return out
    path = os.path.join(bundle.root, tiling.get("parents", PARENTS_FILE))
    if not os.path.isfile(path):
        return out
    with open(path) as fh:
        for line in fh:
            if line.strip():
                parent = json.loads(line)
                out[str(parent["instance_id"])] = parent
    return out


def stitch_file(bundle, path: str) -> int:
    """Rewrite *path* (predictions.jsonl) with each tiled image's tile
    predictions merged into one record for the image. Returns the number of
    records written."""
    parents = _parents(bundle)
    if not parents or not os.path.isfile(path):
        return 0
    tiles: Dict[str, Dict[str, Any]] = {}
    for split in list((bundle.manifest.get("splits") or {})):
        for row in bundle.read_split(split):
            if row.get("parent_id"):
                tiles[str(row["instance_id"])] = row

    passthrough: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    heldout: set = set()
    sizes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            tile_row = tiles.get(str(record.get("instance_id")))
            if tile_row is None:
                passthrough.append(record)
                continue
            key = (str(tile_row["parent_id"]), str(record.get("schema_name")))
            if record.get("heldout_only"):
                heldout.add(key)
            payload = record.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = []
            for obj in payload if isinstance(payload, list) else []:
                if isinstance(obj, dict):
                    mapped = to_parent(obj, tile_row["tile"])
                    if mapped is not None:
                        if _touches_inner_edge(obj, tile_row["tile"]):
                            mapped["_cut"] = True
                        grouped.setdefault(key, []).append(mapped)
                        sizes[key] = tile_row["tile"]
            grouped.setdefault(key, grouped.get(key, []))

    records = list(passthrough)
    for (iid, schema), objects in grouped.items():
        tile = sizes.get((iid, schema)) or {"width": 1, "height": 1}
        # Two tiles' copies of one point land a few pixels apart, not on
        # the same pixel.
        kept = merge(objects, point_tolerance=_POINT_PIXELS / float(
            max(tile["width"], tile["height"]) or 1))
        if not kept:
            continue
        confidences = [float(o["confidence"]) for o in kept
                       if isinstance(o.get("confidence"), (int, float))]
        record = {"instance_id": iid, "schema_name": schema, "payload": kept,
                  "confidence": (round(sum(confidences) / len(confidences), 4)
                                 if confidences else None)}
        if (iid, schema) in heldout:
            record["heldout_only"] = True
        records.append(record)
    with open(path, "w") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def scoring_rows(bundle, split: str) -> Iterable[Dict[str, Any]]:
    """The rows a split is scored on: its untiled rows, and the parent of
    each tiled image in place of its tiles."""
    parents = _parents(bundle)
    if not parents:
        yield from bundle.read_split(split)
        return
    for row in bundle.read_split(split):
        if not row.get("parent_id"):
            yield row
    for parent in parents.values():
        if parent.get("split") == split:
            yield parent
