"""
Deep-zoom tile pyramids, so an image larger than a screen is annotatable.

A 200-megapixel aerial survey or a stitched microscopy mosaic cannot be sent to
a browser as one file. `<img src>` on a 2 GB TIFF is not slow — it is a tab
that dies. The standard answer is a pyramid: the image at a sequence of
halvings, each cut into small tiles, of which the viewer fetches only the ones
currently on screen.

## Levels, and the one indexing decision everything else follows

DZI numbers levels from **0 = smallest**, where level 0 is a single tile of at
most `tile_size` pixels, and each level doubles until the top level is the image
at full resolution. So a 40000x30000 image has ceil(log2(40000)) = 16 levels,
level 16 being full size and level 0 being 1x1 px.

That convention comes from the format, not from us, and it is inverted from how
most people describe zoom ("level 1 = the overview"). It is stated here because
every off-by-one in a tile server is this.

## Why levels are generated whole, and lazily

Two obvious designs are both wrong for this workload:

- **Pre-generate everything on first request.** A 4-gigapixel source is ~60,000
  tiles and several minutes during which the annotator sees nothing. Most of
  those tiles are for magnifications nobody will look at.
- **Generate each tile on demand from the source.** Pillow has no cheap random
  access into most formats; cropping one 254 px tile decodes the whole image.
  A screenful is ~30 tiles, so a single view decodes the source 30 times.

So a level is generated **as a unit, the first time any of its tiles is asked
for**: the source is decoded once, resized to that level, and every tile of the
level is written out in one pass. Zooming to a magnification costs one decode;
panning around at that magnification costs nothing. A level nobody visits is
never built.

## The pixel ceiling is a refusal, not a silent downgrade

Building a level means holding that level's image in memory. Above
:data:`DEFAULT_MAX_PIXELS` this refuses with a message naming the limit and the
setting, because the alternative — quietly serving a lower level and letting the
annotator draw on a blurred approximation — produces coordinates that are wrong
in a way nothing downstream can detect.

Whole-slide formats (SVS, NDPI) carry their own pyramids and should be read
through `openslide` rather than rebuilt here; that is the deferred medical
track, and this module says so rather than pretending a 40 GB slide will work.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TileError(RuntimeError):
    """Raised with a message the UI can show verbatim."""


#: DZI's default. 254 rather than 256 so that with 1 px of overlap on each side
#: a tile is exactly 256 — the size the format was designed around.
DEFAULT_TILE_SIZE = 254

#: Pixels of neighbouring image included on each side of a tile. Without it,
#: bilinear filtering at tile edges samples beyond the tile and draws a visible
#: grid over the image; annotators read that grid as image content.
DEFAULT_OVERLAP = 1

#: Above this, building a level is refused. 640 megapixels is a 32000x20000
#: image — comfortably past any ordinary photographic or satellite source and
#: short of a whole-slide scan, which needs a different reader entirely.
DEFAULT_MAX_PIXELS = 640_000_000

#: JPEG unless the source has alpha. Tiles are viewed, not measured, and PNG
#: tiles of a photographic source are several times the bytes for no visible
#: difference; an image with transparency has to keep it or the viewer shows
#: black where the image is meant to show through.
JPEG_QUALITY = 82


def _require_pillow():
    try:
        from PIL import Image
    except ImportError:
        raise TileError(
            "Deep zoom needs Pillow to build tiles. Install it with "
            "`pip install Pillow`, or set `viewer: fabric` on the schema to "
            "use the single-image viewer.")
    # A 200-megapixel source trips Pillow's decompression-bomb guard, which
    # exists for untrusted uploads. These files are the project's own data and
    # are exactly what this module is for, so the guard is lifted here rather
    # than globally.
    Image.MAX_IMAGE_PIXELS = None
    return Image


class PyramidSpec:
    """The geometry of one image's pyramid. Pure arithmetic, no I/O."""

    def __init__(self, width: int, height: int,
                 tile_size: int = DEFAULT_TILE_SIZE,
                 overlap: int = DEFAULT_OVERLAP,
                 fmt: str = "jpg"):
        if width <= 0 or height <= 0:
            raise TileError(f"An image of {width}x{height} has no pyramid.")
        self.width = int(width)
        self.height = int(height)
        self.tile_size = int(tile_size)
        self.overlap = int(overlap)
        self.format = fmt

    @property
    def max_level(self) -> int:
        """The level at which the image is full size."""
        return int(math.ceil(math.log2(max(self.width, self.height, 1))))

    @property
    def levels(self) -> int:
        return self.max_level + 1

    def level_size(self, level: int) -> Tuple[int, int]:
        """
        The image's dimensions at ``level``.

        Rounded **up**, per the DZI specification: a 3-pixel dimension halves
        to 2, not to 1. Rounding down loses the last row or column of the
        image at odd sizes, which shows up as a sliver of missing content at
        one edge and only at some zoom levels.
        """
        scale = 2 ** (self.max_level - int(level))
        return (max(1, int(math.ceil(self.width / scale))),
                max(1, int(math.ceil(self.height / scale))))

    def grid(self, level: int) -> Tuple[int, int]:
        """``(columns, rows)`` of tiles at ``level``."""
        width, height = self.level_size(level)
        return (int(math.ceil(width / self.tile_size)),
                int(math.ceil(height / self.tile_size)))

    def tile_box(self, level: int, column: int, row: int) -> Tuple[int, int, int, int]:
        """
        The ``(left, top, right, bottom)`` crop of the level image for a tile.

        Overlap is added on the sides that have a neighbour and not on the
        outer edges, which is what makes the assembled tiles line up: an edge
        tile that included phantom overlap would be shifted by one pixel
        against its neighbours for the whole of that row.
        """
        width, height = self.level_size(level)
        columns, rows = self.grid(level)
        if not (0 <= column < columns and 0 <= row < rows):
            raise TileError(
                f"Tile {column}_{row} is outside level {level}, which is "
                f"{columns}x{rows} tiles.")

        left = column * self.tile_size - (self.overlap if column > 0 else 0)
        top = row * self.tile_size - (self.overlap if row > 0 else 0)
        right = min(width, (column + 1) * self.tile_size
                    + (self.overlap if column < columns - 1 else 0))
        bottom = min(height, (row + 1) * self.tile_size
                     + (self.overlap if row < rows - 1 else 0))
        return (left, top, right, bottom)

    def to_json(self) -> Dict[str, Any]:
        return {"width": self.width, "height": self.height,
                "tile_size": self.tile_size, "overlap": self.overlap,
                "format": self.format, "levels": self.levels,
                "max_level": self.max_level}

    def dzi(self) -> str:
        """
        The DZI descriptor OpenSeadragon reads.

        Emitted rather than templated so the numbers come from the same
        arithmetic the tile route uses; a descriptor that disagreed with the
        tiles by one pixel produces a viewer that renders correctly until the
        last column and then tiles a 404 across it.
        """
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008"\n'
            f'       Format="{self.format}"\n'
            f'       Overlap="{self.overlap}"\n'
            f'       TileSize="{self.tile_size}">\n'
            f'  <Size Width="{self.width}" Height="{self.height}"/>\n'
            '</Image>\n')

    def iiif_info(self, identifier: str, base_url: str) -> Dict[str, Any]:
        """
        An IIIF Image API 3.0 ``info.json`` describing the same pyramid.

        Both descriptions exist because both clients exist: OpenSeadragon
        defaults to DZI, and libraries, museums and the Mirador viewer speak
        IIIF. They describe *the same tiles* — the scale factors below are the
        DZI levels expressed the way IIIF names them — so adding IIIF costs a
        second descriptor and no second pyramid.
        """
        scales = [2 ** (self.max_level - level)
                  for level in range(self.levels)]
        return {
            "@context": "http://iiif.io/api/image/3/context.json",
            "id": f"{base_url.rstrip('/')}/{identifier}",
            "type": "ImageService3",
            "protocol": "http://iiif.io/api/image",
            "profile": "level1",
            "width": self.width,
            "height": self.height,
            "tiles": [{"width": self.tile_size,
                       "scaleFactors": sorted(scales)}],
            "sizes": [{"width": self.level_size(level)[0],
                       "height": self.level_size(level)[1]}
                      for level in range(self.levels)],
        }


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

#: One lock per (cache dir, source, level). Two annotators opening the same
#: huge image at the same moment would otherwise both decode it and race each
#: other writing the same tiles.
_LEVEL_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _level_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LEVEL_LOCKS.get(key)
        if lock is None:
            lock = _LEVEL_LOCKS[key] = threading.Lock()
        return lock


def describe(source: str, tile_size: int = DEFAULT_TILE_SIZE,
             overlap: int = DEFAULT_OVERLAP,
             page: int = 0) -> PyramidSpec:
    """
    Read the source's dimensions and return its pyramid geometry.

    Opens the header only — Pillow reports ``size`` without decoding pixels —
    so describing a 2 GB image is as cheap as describing a thumbnail. That is
    what lets the viewer be configured before any tile exists.
    """
    from potato.media import images

    path = Path(source)
    if not path.exists():
        raise TileError(f"{path.name} does not exist.")
    _require_pillow()
    try:
        image = images._open(path, page=page)
    except images.ImageTranscodeError as exc:
        raise TileError(str(exc))
    width, height = image.size
    fmt = "png" if _has_alpha(image) else "jpg"
    try:
        image.close()
    except Exception:  # noqa: BLE001 - closing is best-effort
        pass
    return PyramidSpec(width, height, tile_size=tile_size, overlap=overlap,
                       fmt=fmt)


def _has_alpha(image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in getattr(image, "info", {}))


def tile_dir(cache_dir: Path, source: Path, spec: PyramidSpec,
             level: int, page: int = 0) -> Path:
    """Where one level's tiles live. Keyed like every other media cache entry."""
    from potato.media.cache import cache_key

    key = cache_key(source, ".tiles", tile_size=spec.tile_size,
                    overlap=spec.overlap, fmt=spec.format, page=page)
    return Path(cache_dir) / f"{key}_files" / str(int(level))


def ensure_level(cache_dir: Path, source: Path, spec: PyramidSpec, level: int,
                 page: int = 0, max_pixels: int = DEFAULT_MAX_PIXELS) -> Path:
    """
    Build every tile of ``level`` if they are not already on disk.

    Whole-level generation is the point: see the module docstring. The marker
    file is written **last**, so a run interrupted halfway leaves the level
    unmarked and it is rebuilt rather than served with holes.

    ``max_pixels`` governs **building**, not serving: a level already on disk
    is returned even if the ceiling has since been lowered. The ceiling exists
    to bound the memory of a decode, and there is no decode to bound once the
    tiles exist — refusing there would invalidate work already done for no
    benefit.
    """
    from potato.media import images

    directory = tile_dir(cache_dir, source, spec, level, page=page)
    marker = directory / ".complete"
    if marker.exists():
        return directory

    with _level_lock(str(directory)):
        if marker.exists():
            return directory

        width, height = spec.level_size(level)
        if width * height > max_pixels:
            raise TileError(
                f"Level {level} of {source.name} is {width}x{height} "
                f"({width * height / 1e6:.0f} MP), above the "
                f"{max_pixels / 1e6:.0f} MP ceiling for building a tile level. "
                f"Raise `image_annotation.tiles.max_pixels`, or use a source "
                f"with its own pyramid (SVS/NDPI via openslide).")

        Image = _require_pillow()
        try:
            image = images._open(source, page=page)
            image = image.convert("RGBA" if spec.format == "png" else "RGB")
        except images.ImageTranscodeError as exc:
            raise TileError(str(exc))

        if (width, height) != image.size:
            # LANCZOS, not the default. A halved satellite or text-bearing
            # image resampled with NEAREST aliases into moire that annotators
            # reasonably report as image artifacts.
            image = image.resize((width, height), Image.LANCZOS)

        directory.mkdir(parents=True, exist_ok=True)
        columns, rows = spec.grid(level)
        written = 0
        for column in range(columns):
            for row in range(rows):
                box = spec.tile_box(level, column, row)
                tile = image.crop(box)
                target = directory / f"{column}_{row}.{spec.format}"
                if spec.format == "jpg":
                    tile.save(target, "JPEG", quality=JPEG_QUALITY,
                              optimize=True)
                else:
                    tile.save(target, "PNG", optimize=True)
                written += 1
        try:
            image.close()
        except Exception:  # noqa: BLE001
            pass

        marker.write_text(f"{columns}x{rows}\n", encoding="utf-8")
        logger.info("Built level %d of %s: %d tiles at %dx%d",
                    level, source.name, written, width, height)
        return directory


def tile_file(cache_dir: Path, source: Path, spec: PyramidSpec, level: int,
              column: int, row: int, page: int = 0,
              max_pixels: int = DEFAULT_MAX_PIXELS) -> Path:
    """The file for one tile, building its level if needed."""
    spec.tile_box(level, column, row)   # validates the coordinates first
    directory = ensure_level(cache_dir, source, spec, level, page=page,
                             max_pixels=max_pixels)
    path = directory / f"{column}_{row}.{spec.format}"
    if not path.exists():
        raise TileError(
            f"Tile {level}/{column}_{row} is missing from a level that "
            f"reported complete. Delete {directory.parent} to rebuild.")
    return path


def iiif_region(cache_dir: Path, source: Path, spec: PyramidSpec,
                region: str, size: str, rotation: str, quality: str,
                fmt: str, page: int = 0,
                max_pixels: int = DEFAULT_MAX_PIXELS):
    """
    Serve one IIIF Image API request, returning ``(bytes, mimetype)``.

    Implemented over the same level images the DZI tiles come from: the request
    is satisfied at the smallest level that is at least as large as the output,
    so a thumbnail is cut from a small level rather than from the full-size
    source. That is the whole reason IIIF is cheap to add here — without the
    pyramid, every ``/full/!200,200/`` would decode the original.
    """
    from io import BytesIO

    from potato.media import images

    Image = _require_pillow()
    left, top, right, bottom = _iiif_region_box(spec, region)
    out_width, out_height = _iiif_size(size, right - left, bottom - top)

    if out_width <= 0 or out_height <= 0:
        raise TileError(f"A size of '{size}' asks for an empty image.")

    # The smallest level whose scale still covers the requested output.
    level = spec.max_level
    for candidate in range(spec.levels):
        scale = 2 ** (spec.max_level - candidate)
        if (right - left) / scale >= out_width:
            level = candidate
            break

    scale = 2 ** (spec.max_level - level)
    level_width, level_height = spec.level_size(level)
    box = (max(0, int(left / scale)), max(0, int(top / scale)),
           min(level_width, int(math.ceil(right / scale))),
           min(level_height, int(math.ceil(bottom / scale))))

    if level_width * level_height > max_pixels:
        raise TileError(
            f"Level {level} of {source.name} is above the "
            f"{max_pixels / 1e6:.0f} MP ceiling.")

    try:
        image = images._open(source, page=page)
        image = image.convert("RGBA" if fmt == "png" else "RGB")
    except images.ImageTranscodeError as exc:
        raise TileError(str(exc))
    if (level_width, level_height) != image.size:
        image = image.resize((level_width, level_height), Image.LANCZOS)
    crop = image.crop(box)
    if (out_width, out_height) != crop.size:
        crop = crop.resize((out_width, out_height), Image.LANCZOS)

    if rotation not in ("0", "", None):
        try:
            crop = crop.rotate(-float(rotation), expand=True)
        except ValueError:
            raise TileError(f"'{rotation}' is not a rotation in degrees.")
    if quality == "gray":
        crop = crop.convert("L")
    elif quality == "bitonal":
        crop = crop.convert("1")

    buffer = BytesIO()
    if fmt == "png":
        crop.save(buffer, "PNG", optimize=True)
        return buffer.getvalue(), "image/png"
    crop.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY,
                             optimize=True)
    return buffer.getvalue(), "image/jpeg"


def _iiif_region_box(spec: PyramidSpec, region: str) -> Tuple[int, int, int, int]:
    """``full``, ``square``, ``x,y,w,h`` or ``pct:x,y,w,h`` in full-size pixels."""
    region = (region or "full").strip()
    if region == "full":
        return (0, 0, spec.width, spec.height)
    if region == "square":
        side = min(spec.width, spec.height)
        left = (spec.width - side) // 2
        top = (spec.height - side) // 2
        return (left, top, left + side, top + side)

    percent = region.startswith("pct:")
    parts = (region[4:] if percent else region).split(",")
    if len(parts) != 4:
        raise TileError(
            f"'{region}' is not a IIIF region. Use full, square, x,y,w,h or "
            f"pct:x,y,w,h.")
    try:
        values = [float(p) for p in parts]
    except ValueError:
        raise TileError(f"'{region}' has a non-numeric coordinate.")
    if percent:
        values = [values[0] / 100 * spec.width, values[1] / 100 * spec.height,
                  values[2] / 100 * spec.width, values[3] / 100 * spec.height]
    left, top, width, height = (int(v) for v in values)
    return (max(0, left), max(0, top),
            min(spec.width, left + width), min(spec.height, top + height))


def _iiif_size(size: str, region_width: int, region_height: int) -> Tuple[int, int]:
    """``max``/``full``, ``w,``, ``,h``, ``w,h``, ``!w,h`` or ``pct:n``."""
    size = (size or "max").strip()
    if size in ("max", "full"):
        return (region_width, region_height)
    if size.startswith("pct:"):
        try:
            fraction = float(size[4:]) / 100
        except ValueError:
            raise TileError(f"'{size}' is not a IIIF size.")
        return (max(1, int(region_width * fraction)),
                max(1, int(region_height * fraction)))

    best_fit = size.startswith("!")
    parts = (size[1:] if best_fit else size).split(",")
    if len(parts) != 2:
        raise TileError(
            f"'{size}' is not a IIIF size. Use max, w,, ,h, w,h, !w,h or pct:n.")
    try:
        width = int(parts[0]) if parts[0] else 0
        height = int(parts[1]) if parts[1] else 0
    except ValueError:
        raise TileError(f"'{size}' has a non-integer dimension.")

    if width and not height:
        return (width, max(1, round(region_height * width / region_width)))
    if height and not width:
        return (max(1, round(region_width * height / region_height)), height)
    if best_fit:
        # "!w,h" means fit inside the box while keeping the aspect ratio,
        # rather than stretching to it.
        ratio = min(width / region_width, height / region_height)
        return (max(1, round(region_width * ratio)),
                max(1, round(region_height * ratio)))
    return (width, height)


def tiles_enabled(scheme: Dict[str, Any]) -> bool:
    """True when a schema asks for the deep-zoom viewer."""
    return str((scheme or {}).get("viewer") or "fabric").lower() == "deepzoom"


def tile_settings(scheme: Dict[str, Any]) -> Dict[str, Any]:
    """The schema's tile options, defaulted."""
    settings = ((scheme or {}).get("tiles") or {})
    return {
        "tile_size": int(settings.get("tile_size") or DEFAULT_TILE_SIZE),
        "overlap": int(settings.get("overlap")
                       if settings.get("overlap") is not None
                       else DEFAULT_OVERLAP),
        "max_pixels": int(settings.get("max_pixels") or DEFAULT_MAX_PIXELS),
    }
