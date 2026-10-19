"""
Whole-slide images (SVS, NDPI, MRXS, ...) served as deep-zoom tiles.

A 40x pathology scan is about 100,000 x 80,000 pixels. The flat-image path in
`tiles.py` builds each level by decoding the whole source, which for a slide
means tens of gigabytes per level, so it refuses. A slide already carries its
own pyramid, and openslide reads any region of any level directly; this module
serves DZI tiles and IIIF regions from that pyramid through openslide's
`DeepZoomGenerator`, one tile at a time, caching each tile it makes.

The geometry is the same DZI pyramid as everywhere else (`tiles.PyramidSpec`),
with ``limit_bounds=False`` so that tile and annotation coordinates are in the
slide's full-resolution pixels, as `tiles.PyramidSpec` assumes. A test checks
that the spec and openslide's generator agree at every level.

openslide is optional: ``pip install potato-annotation[wsi]`` installs
openslide-python and openslide-bin, which bundles the C library. Without it a
slide is refused with that instruction rather than handed to Pillow, which
would decode the full-resolution level.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from potato.media.tiles import (DEFAULT_OVERLAP, DEFAULT_TILE_SIZE, JPEG_QUALITY,
                                PyramidSpec, TileError)

logger = logging.getLogger(__name__)

#: Formats that are always slides. A `.tif`/`.tiff` is a slide only when
#: openslide recognises it (see `is_slide`).
SLIDE_EXTENSIONS = frozenset({
    ".svs", ".ndpi", ".mrxs", ".scn", ".vms", ".vmu", ".bif", ".svslide",
})

INSTALL_HINT = ("Whole-slide images need openslide: "
                "`pip install potato-annotation[wsi]` "
                "(openslide-python and openslide-bin).")

#: Open slide handles, most recently used last. Opening reads the slide's
#: index (for MRXS, several files), so it is kept rather than repeated per tile.
_HANDLES: "OrderedDict[str, Any]" = OrderedDict()
_HANDLES_LOCK = threading.Lock()
MAX_OPEN_SLIDES = 8


def _openslide():
    try:
        import openslide  # noqa: F401
        from openslide import deepzoom  # noqa: F401
    except (ImportError, OSError) as exc:
        # OSError: openslide-python is installed but the C library is not.
        raise TileError(f"{INSTALL_HINT} ({exc})")
    return openslide


def openslide_available() -> bool:
    try:
        _openslide()
        return True
    except TileError:
        return False


def is_slide(path: str) -> bool:
    """True when ``path`` should be read through openslide."""
    suffix = Path(path).suffix.lower()
    if suffix in SLIDE_EXTENSIONS:
        return True
    if suffix not in (".tif", ".tiff") or not openslide_available():
        return False
    import openslide
    try:
        vendor = openslide.OpenSlide.detect_format(str(path))
    except Exception:  # noqa: BLE001 - an unreadable file is not a slide
        return False
    if vendor is None:
        return False
    if vendor != "generic-tiff":
        return True
    # A generic tiled TIFF is worth openslide only when it has its own
    # pyramid; a single-level one is an ordinary large image.
    try:
        return _handle(str(path)).level_count > 1
    except TileError:
        return False


def _handle(path: str):
    """An open OpenSlide for ``path``, shared across requests."""
    openslide = _openslide()
    key = str(Path(path).resolve())
    with _HANDLES_LOCK:
        slide = _HANDLES.get(key)
        if slide is not None:
            _HANDLES.move_to_end(key)
            return slide
    try:
        slide = openslide.OpenSlide(key)
    except openslide.OpenSlideError as exc:
        raise TileError(f"{Path(path).name} could not be read as a slide: {exc}")
    except openslide.OpenSlideUnsupportedFormatError:
        raise TileError(f"{Path(path).name} is not a slide format openslide reads.")
    with _HANDLES_LOCK:
        _HANDLES[key] = slide
        while len(_HANDLES) > MAX_OPEN_SLIDES:
            _old_key, old = _HANDLES.popitem(last=False)
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
    return slide


def _generator(path: str, tile_size: int, overlap: int):
    from openslide.deepzoom import DeepZoomGenerator
    return DeepZoomGenerator(_handle(path), tile_size=tile_size, overlap=overlap,
                             limit_bounds=False)


def describe_slide(path: str, tile_size: int = DEFAULT_TILE_SIZE,
                   overlap: int = DEFAULT_OVERLAP) -> PyramidSpec:
    """The slide's DZI pyramid. Reads the slide's header only."""
    if not Path(path).exists():
        raise TileError(f"{Path(path).name} does not exist.")
    slide = _handle(path)
    width, height = slide.dimensions
    return PyramidSpec(width, height, tile_size=tile_size, overlap=overlap, fmt="jpg")


def slide_metadata(path: str) -> Dict[str, Any]:
    """Vendor, microns per pixel and objective power, where the slide says."""
    import openslide
    props = _handle(path).properties

    def number(key):
        try:
            return float(props[key])
        except (KeyError, TypeError, ValueError):
            return None
    return {
        "vendor": props.get(openslide.PROPERTY_NAME_VENDOR),
        "mpp_x": number(openslide.PROPERTY_NAME_MPP_X),
        "mpp_y": number(openslide.PROPERTY_NAME_MPP_Y),
        "objective_power": number(openslide.PROPERTY_NAME_OBJECTIVE_POWER),
        "levels": _handle(path).level_count,
    }


def slide_tile(cache_dir: Path, source: Path, spec: PyramidSpec, level: int,
               column: int, row: int) -> Path:
    """The file for one tile, read from the slide on first request."""
    from potato.media.tiles import tile_dir

    spec.tile_box(level, column, row)          # validates the coordinates
    directory = tile_dir(cache_dir, source, spec, level)
    target = directory / f"{column}_{row}.jpg"
    if target.exists():
        return target
    tile = _generator(str(source), spec.tile_size, spec.overlap).get_tile(
        int(level), (int(column), int(row)))
    directory.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and renamed, so a concurrent request never
    # serves a half-written tile.
    partial = directory / f".{column}_{row}.{os.getpid()}.{threading.get_ident()}.jpg"
    tile.convert("RGB").save(partial, "JPEG", quality=JPEG_QUALITY, optimize=True)
    os.replace(partial, target)
    return target


def slide_region(source: Path, spec: PyramidSpec, box: Tuple[int, int, int, int],
                 out_size: Tuple[int, int]):
    """A PIL image of ``box`` (full-resolution pixels) at ``out_size``.

    Read from the slide level closest to, and not coarser than, the requested
    downsample, so a thumbnail of a whole slide reads its smallest level.
    """
    from PIL import Image

    slide = _handle(str(source))
    left, top, right, bottom = box
    out_width, out_height = out_size
    downsample = max((right - left) / max(out_width, 1), (bottom - top) / max(out_height, 1))
    level = slide.get_best_level_for_downsample(max(1.0, downsample))
    factor = slide.level_downsamples[level]
    size = (max(1, int(math.ceil((right - left) / factor))),
            max(1, int(math.ceil((bottom - top) / factor))))
    region = slide.read_region((int(left), int(top)), level, size)
    # read_region returns RGBA with transparent padding outside the slide;
    # composite on white, as slide viewers show background.
    flat = Image.new("RGB", region.size, (255, 255, 255))
    flat.paste(region, mask=region.split()[3])
    if flat.size != (out_width, out_height):
        flat = flat.resize((out_width, out_height), Image.LANCZOS)
    return flat


def close_all() -> None:
    """Close every cached handle (tests, and server shutdown)."""
    with _HANDLES_LOCK:
        while _HANDLES:
            _key, slide = _HANDLES.popitem()
            try:
                slide.close()
            except Exception:  # noqa: BLE001
                pass


def _spec_matches_generator(path: str, spec: PyramidSpec) -> Optional[str]:
    """None when the spec and openslide's generator agree; else the difference."""
    dz = _generator(path, spec.tile_size, spec.overlap)
    if dz.level_count != spec.levels:
        return f"{dz.level_count} levels from openslide, {spec.levels} from the spec"
    for level in range(spec.levels):
        if tuple(dz.level_dimensions[level]) != spec.level_size(level):
            return f"level {level}: {dz.level_dimensions[level]} vs {spec.level_size(level)}"
        if tuple(dz.level_tiles[level]) != spec.grid(level):
            return f"level {level} grid: {dz.level_tiles[level]} vs {spec.grid(level)}"
    return None
