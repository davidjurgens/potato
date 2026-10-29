"""
Server-side compositing for the ``microscopy`` schema.

The browser asks for deep-zoom tiles of a *rendering*: which channels are on,
their colours, their contrast limits, and the z-slice and time point. Each
tile is composited here from the raw channel data and sent as a JPEG, so the
page needs only OpenSeadragon (already vendored) and no WebGL.

## Why on the server

The obvious client for OME-Zarr is Viv (MIT), which composites channels on the
GPU in WebGL2. It is not used because it ships as ES modules on top of deck.gl
and luma.gl with no self-contained browser build, and Potato has no JavaScript
build step and serves no CDN assets. Bundling it ourselves would mean
committing several megabytes of generated code. The trade-offs of doing it here
instead are written up in docs/annotation-types/science/microscopy.md: every
contrast change is a round trip for the visible tiles (Viv's is a shader
uniform), but there is no WebGL requirement, it works air-gapped, and the
browser never receives the raw data.

## Geometry

Tiles follow the DZI arithmetic of :class:`potato.media.tiles.PyramidSpec`
(level 0 is 1 px, the top level is full resolution). A DZI level at scale
``s`` (one tile pixel covers ``s`` source pixels) is cut from the coarsest
pyramid level of the file whose downsampling factor is at most ``s``, so a
zoomed-out view reads a coarse level and only a close-up touches level 0.
"""

from __future__ import annotations

import gzip
import io
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.science.converters.ome import OmeError, OmeImage, _require

#: Longest accepted rendering string (``?ch=...``).
MAX_SPEC_LENGTH = 4000

#: The label raster sent to the browser is at most this many pixels a side.
DEFAULT_LABEL_MAX_SIDE = 2048

#: More cells than this in one label image is refused for the cell table.
MAX_CELLS = 50_000

JPEG_QUALITY = 90

_HEX = re.compile(r"^[0-9a-fA-F]{6}$")


@dataclass
class RenderChannel:
    index: int
    rgb: Tuple[float, float, float]
    start: float
    end: float


def parse_channel_spec(text: str, image: OmeImage) -> List[RenderChannel]:
    """
    Parse ``"0:3b6cff:150:3200;2:ff3b3b:100:2600"`` -- the visible channels,
    each ``index:colour:start:end``. An empty string means nothing visible
    (a black tile), which is a legitimate view, not an error.
    """
    text = (text or "").strip()
    if len(text) > MAX_SPEC_LENGTH:
        raise OmeError("The channel settings are too long.")
    out: List[RenderChannel] = []
    seen = set()
    if not text:
        return out
    for part in text.split(";"):
        bits = part.split(":")
        if len(bits) != 4:
            raise OmeError(f"'{part}' is not index:colour:start:end.")
        try:
            index = int(bits[0])
            start, end = float(bits[2]), float(bits[3])
        except ValueError:
            raise OmeError(f"'{part}' has a non-numeric index or limit.")
        if not 0 <= index < image.size_c:
            raise OmeError(f"Channel {index} is not in this image, which has "
                           f"{image.size_c} channels.")
        if index in seen:
            raise OmeError(f"Channel {index} is listed twice.")
        if not _HEX.match(bits[1]):
            raise OmeError(f"'{bits[1]}' is not a six-digit hex colour.")
        if not (math.isfinite(start) and math.isfinite(end)):
            raise OmeError(f"Channel {index} has a limit that is not a number.")
        if end <= start:
            end = start + 1e-6
        seen.add(index)
        colour = bits[1]
        out.append(RenderChannel(index=index, start=start, end=end,
                                 rgb=(int(colour[0:2], 16) / 255.0, int(colour[2:4], 16) / 255.0,
                                      int(colour[4:6], 16) / 255.0)))
    return out


def default_channel_spec(image: OmeImage) -> str:
    return ";".join(f"{c.index}:{c.color}:{c.start:g}:{c.end:g}"
                    for c in image.channels if c.visible)


def pick_level(image: OmeImage, scale: float) -> int:
    """The coarsest pyramid level whose downsampling is at most ``scale``."""
    best = 0
    for level in range(len(image.levels)):
        fy, fx = image.level_factor(level)
        if min(fy, fx) <= scale * 1.0001:
            best = level
    return best


def composite(image: OmeImage, level: int, box: Tuple[int, int, int, int],
              channels: Sequence[RenderChannel], z: int, t: int):
    """RGB uint8 of ``box`` = (x0, y0, x1, y1) in ``level``'s pixels."""
    np = _require("numpy")
    x0, y0, x1, y1 = box
    height, width = max(0, y1 - y0), max(0, x1 - x0)
    out = np.zeros((height, width, 3), dtype="float32")
    for channel in channels:
        data = image.read_region(level, channel.index, z, t, y0, y1, x0, x1)
        if data.shape != (height, width):
            # A read clipped at the image edge; pad so channels line up.
            padded = np.zeros((height, width), dtype="float32")
            padded[:data.shape[0], :data.shape[1]] = data
            data = padded
        value = (data.astype("float32") - channel.start) / (channel.end - channel.start)
        np.clip(value, 0.0, 1.0, out=value)
        out += value[..., None] * np.asarray(channel.rgb, dtype="float32")
    np.clip(out, 0.0, 1.0, out=out)
    return (out * 255.0 + 0.5).astype("uint8")


def render_tile(image: OmeImage, spec, level: int, column: int, row: int,
                channels: Sequence[RenderChannel], z: int = 0, t: int = 0,
                quality: int = JPEG_QUALITY) -> bytes:
    """One DZI tile of the rendering, as JPEG bytes."""
    from PIL import Image

    image.check_plane(0, z, t)
    if not 0 <= int(level) <= spec.max_level:
        raise OmeError(f"Level {level} is not in this image's tile pyramid "
                       f"(0 to {spec.max_level}).")
    left, top, right, bottom = spec.tile_box(level, column, row)
    scale = 2 ** (spec.max_level - int(level))
    # The tile in full-resolution pixels.
    fx0, fy0 = left * scale, top * scale
    fx1, fy1 = min(image.size_x, right * scale), min(image.size_y, bottom * scale)
    source_level = pick_level(image, scale)
    ly, lx = image.level_factor(source_level)
    box = (int(fx0 // lx), int(fy0 // ly),
           int(math.ceil(fx1 / lx)), int(math.ceil(fy1 / ly)))
    rgb = composite(image, source_level, box, channels, z, t)
    tile = Image.fromarray(rgb, "RGB")
    size = (right - left, bottom - top)
    if tile.size != size and tile.size[0] > 0 and tile.size[1] > 0:
        tile = tile.resize(size, Image.BILINEAR)
    buffer = io.BytesIO()
    # 4:4:4, not JPEG's default 4:2:0: a pure blue or red channel has little
    # luminance, so halving the chroma resolution blurs and dims exactly the
    # colours a fluorescence overlay is made of.
    tile.save(buffer, "JPEG", quality=int(quality), subsampling=0)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Label images
# ---------------------------------------------------------------------------

def label_raster(image: OmeImage, name: str, z: int = 0, t: int = 0,
                 max_side: int = DEFAULT_LABEL_MAX_SIDE):
    """
    ``(raster, factor)``: the label image at the finest level no larger than
    ``max_side`` a side (nearest-neighbour strided further if every level is
    larger), and how many full-resolution pixels one raster pixel covers.

    This is what the page hit-tests clicks against and draws cell overlays
    from, so a click picks the same id the export will name.
    """
    np = _require("numpy")
    if name not in image.label_images:
        raise OmeError(f"This image has no label image named {name!r}.")
    label = image.label_images[name]
    image.check_plane(0, z, t)
    chosen = len(label.levels) - 1
    for level in range(len(label.levels)):
        shape = label.levels[level]
        side = max(shape[label.axes.index("y")], shape[label.axes.index("x")])
        if side <= max_side:
            chosen = level
            break
    shape = label.levels[chosen]
    ny, nx = shape[label.axes.index("y")], shape[label.axes.index("x")]
    step = max(1, int(math.ceil(max(ny, nx) / max_side)))
    raster = image.read_label_region(name, chosen, z, t, 0, ny, 0, nx, step=step)
    if np.dtype(raster.dtype).kind not in "ui":
        raise OmeError(f"Label image {name!r} holds {raster.dtype} values, not integers.")
    fy, fx = image.label_factor(name, chosen)
    return np.ascontiguousarray(raster), fx * step


def encode_raster(raster) -> Tuple[bytes, int]:
    """Gzipped little-endian raw ids and the bytes per id (2 or 4)."""
    np = _require("numpy")
    peak = int(raster.max()) if raster.size else 0
    if peak >= 2 ** 32:
        raise OmeError("Label ids above 2^32 are not supported.")
    if int(raster.min() if raster.size else 0) < 0:
        raise OmeError("Label ids must not be negative.")
    width = 2 if peak < 65536 else 4
    data = raster.astype("<u2" if width == 2 else "<u4").tobytes()
    return gzip.compress(data, compresslevel=6), width


def cell_table(raster, factor: float) -> List[Dict[str, Any]]:
    """Every non-zero id with its centroid and area in full-resolution pixels."""
    np = _require("numpy")
    flat = raster.ravel().astype("int64")
    if flat.size == 0:
        return []
    ids = np.unique(flat)
    ids = ids[ids != 0]
    if ids.size > MAX_CELLS:
        raise OmeError(f"The label image has {ids.size} cells, more than the "
                       f"{MAX_CELLS} the cell list supports.")
    if ids.size == 0:
        return []
    inverse = np.searchsorted(ids, flat)
    mask = flat != 0
    counts = np.bincount(inverse[mask], minlength=ids.size)
    ys, xs = np.divmod(np.arange(flat.size), raster.shape[1])
    sum_y = np.bincount(inverse[mask], weights=ys[mask], minlength=ids.size)
    sum_x = np.bincount(inverse[mask], weights=xs[mask], minlength=ids.size)
    out = []
    for i, label_id in enumerate(ids.tolist()):
        n = int(counts[i])
        if not n:
            continue
        out.append({"id": int(label_id),
                    "x": round((sum_x[i] / n + 0.5) * factor, 2),
                    "y": round((sum_y[i] / n + 0.5) * factor, 2),
                    "area": round(n * factor * factor, 1)})
    return out


def class_image(image: OmeImage, name: str, assignments: Dict[int, int],
                z: int = 0, t: int = 0):
    """
    The label image at full resolution with every cell's id replaced by its
    class value (0 for unassigned cells and background).

    Read whole from level 0, so bounded by the image's ``max_pixels``.
    """
    np = _require("numpy")
    label = image.label_images.get(name)
    if label is None:
        raise OmeError(f"This image has no label image named {name!r}.")
    shape = label.levels[0]
    ny, nx = shape[label.axes.index("y")], shape[label.axes.index("x")]
    if ny * nx > image.max_pixels:
        raise OmeError(f"The label image is {nx}x{ny}, above the "
                       f"{image.max_pixels / 1e6:.0f} MP limit for export.")
    ids = image.read_label_region(name, 0, z, t, 0, ny, 0, nx).astype("int64")
    if not assignments:
        return np.zeros(ids.shape, dtype="uint16")
    keys = np.asarray(sorted(assignments), dtype="int64")
    values = np.asarray([assignments[k] for k in sorted(assignments)], dtype="int64")
    position = np.searchsorted(keys, ids)
    position = np.clip(position, 0, len(keys) - 1)
    hit = keys[position] == ids
    out = np.where(hit, values[position], 0)
    dtype = "uint8" if out.max() < 256 else "uint16"
    return out.astype(dtype)


def class_volume(image: OmeImage, name: str, assignments: Dict[int, int]):
    """
    ``(array, axes)``: the whole label image (every z-slice and time point it
    has) at full resolution, with each cell id replaced by its class value.
    A cell's class applies to its id on every plane, as it does on the page.
    """
    np = _require("numpy")
    label = image.label_images.get(name)
    if label is None:
        raise OmeError(f"This image has no label image named {name!r}.")
    axes = "".join(a for a in label.axes if a in "tzyx")
    shape = dict(zip(label.axes, label.levels[0]))
    size_t, size_z = int(shape.get("t", 1)), int(shape.get("z", 1))
    planes = []
    for t in range(size_t):
        for z in range(size_z):
            planes.append(class_image(image, name, assignments, z=z, t=t))
    dtype = "uint8" if all(p.dtype == np.uint8 for p in planes) else "uint16"
    stack = np.stack([p.astype(dtype) for p in planes])
    out_shape = tuple(int(shape[a]) for a in axes)
    return stack.reshape(out_shape), axes


def decode_answer(raw: Any) -> Optional[Dict[str, Any]]:
    """The stored answer as a dict, from the JSON string or dict forms."""
    import json

    if isinstance(raw, dict) and len(raw) == 1 and isinstance(next(iter(raw.values())), str):
        raw = next(iter(raw.values()))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None
