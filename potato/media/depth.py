"""
Depth maps: read them, make them legible, and turn them into geometry.

## Why this is not just another image

A depth map opened as an image is a black rectangle. The values are distances,
not brightness, and they live in whatever unit the capture rig chose —
millimetres for most RGB-D sensors, 1/256 m for KITTI, metres for anything
written from a float array. A browser shown the raw file renders 30,000
millimetres as "brighter than white" and 0 as "no data" indistinguishably from
"touching the lens".

So three things have to happen server-side, and each of them is a place a
depth pipeline usually goes quietly wrong:

1. **Scale.** The file says nothing about its unit. ``depth_scale`` is a config
   value, and :func:`describe` reports the resulting range precisely so a wrong
   one is *visible* — "far plane 32,000 m" is obviously not a room.
2. **Invalid pixels.** Zero means "no return", not "zero metres". Treating them
   as near depth paints a bright wall across every hole in the sensor's
   coverage. They are carried as NaN and rendered as a distinct colour.
3. **Windowing.** The interesting range is almost never the full range. The
   default window is percentile-based for the same reason the point cloud's
   colour ramp is: one stray return otherwise compresses everything else into a
   single colour.

## And then it becomes 3D

:func:`unproject` turns depth plus intrinsics into a
:class:`~potato.media.pointcloud.PointCloud`, which means a depth item is
annotatable in the **existing** 3D viewer with the existing cuboid tools. That
is deliberately the whole integration: a depth display that could only be
looked at would be a second, weaker image viewer.
"""

from __future__ import annotations

import json
import logging
import math
import re
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEPTH_MAGIC = b"DPT1"

#: Extensions this module can read. ``.exr`` needs an optional dependency and
#: says so at read time rather than being absent from the list, because "we do
#: not support EXR" and "install imageio" are different answers.
DEPTH_SUFFIXES = (".png", ".tif", ".tiff", ".npy", ".npz", ".pfm", ".exr")

#: Metres per stored unit, when the config does not say. Millimetres: the
#: convention of every consumer RGB-D sensor (RealSense, Azure Kinect) and of
#: NYU-Depth. KITTI's completion benchmark uses 1/256 and Middlebury PFM is
#: already in metres, so both of those must be set explicitly.
DEFAULT_DEPTH_SCALE = 0.001

#: Percentiles the default window clips to.
DEFAULT_LOW_PERCENTILE = 2.0
DEFAULT_HIGH_PERCENTILE = 98.0

#: Above this many pixels the percentiles come from a stride sample. The window
#: only has to be approximately right and a full sort of a 12-megapixel map
#: costs more than the render it is preparing for.
PERCENTILE_SAMPLE_LIMIT = 400_000


class DepthError(RuntimeError):
    """A depth map could not be read. The message names the next action."""


@dataclass
class DepthMap:
    """
    Depth in **metres**, row-major, with NaN for "no measurement".

    NaN rather than 0 or -1 because it propagates: an invalid pixel that takes
    part in an average makes the average invalid, which is the correct answer.
    A sentinel of 0 silently contributes a real number to every statistic.
    """

    values: array           # 'f', length width * height
    width: int
    height: int
    source_format: str = ""
    #: Metres per stored unit that was applied. Recorded so a render can say so.
    scale: float = 1.0

    @property
    def count(self) -> int:
        return self.width * self.height

    def finite(self) -> List[float]:
        return [v for v in self.values if _is_finite(v)]


def _is_finite(v: float) -> bool:
    return v == v and v not in (float("inf"), float("-inf"))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def detect_format(path: str | Path) -> str:
    """Which reader handles this file. Content first, extension second."""
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(8)
    except OSError as err:
        raise DepthError(f"cannot read {p}: {err}") from err

    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:2] in (b"II", b"MM"):
        return "tiff"
    if head.startswith(b"\x93NUMPY"):
        return "npy"
    if head.startswith(b"PK"):
        # .npz is a zip of .npy members.
        return "npz"
    if head.startswith(b"Pf") or head.startswith(b"PF"):
        return "pfm"
    if head.startswith(b"\x76\x2f\x31\x01"):
        return "exr"

    suffix = p.suffix.lower()
    mapping = {".png": "png", ".tif": "tiff", ".tiff": "tiff",
               ".npy": "npy", ".npz": "npz", ".pfm": "pfm", ".exr": "exr"}
    if suffix in mapping:
        return mapping[suffix]
    raise DepthError(
        f"unrecognised depth format for {p.name}. Supported: 16-bit PNG and "
        f"TIFF, NumPy .npy/.npz, PFM, and EXR.")


def read_depth(path: str | Path,
               scale: Optional[float] = None,
               *,
               invalid_below: float = 0.0) -> DepthMap:
    """
    Read a depth map and convert it to metres.

    ``scale`` is metres per stored unit. Float formats (NPY, PFM, EXR) are
    assumed to be in metres already and default to ``1.0``; integer formats
    default to :data:`DEFAULT_DEPTH_SCALE`. Passing ``scale`` explicitly
    overrides both, and doing so is strongly encouraged — the file does not
    know its own unit and neither can we.

    ``invalid_below`` marks non-measurements. Zero is the near-universal
    "no return" code in integer depth; a value of exactly zero metres would
    mean the sensor is touching the surface.
    """
    fmt = detect_format(path)
    p = Path(path)

    if fmt in ("png", "tiff"):
        values, width, height = _read_raster(p)
        applied = DEFAULT_DEPTH_SCALE if scale is None else float(scale)
    elif fmt in ("npy", "npz"):
        values, width, height = _read_numpy(p, fmt)
        applied = 1.0 if scale is None else float(scale)
    elif fmt == "pfm":
        values, width, height = _read_pfm(p)
        applied = 1.0 if scale is None else float(scale)
    elif fmt == "exr":
        values, width, height = _read_exr(p)
        applied = 1.0 if scale is None else float(scale)
    else:  # pragma: no cover - detect_format raises first
        raise DepthError(f"no reader for {fmt}")

    nan = float("nan")
    out = array("f", [nan] * len(values))
    for i, v in enumerate(values):
        if v <= invalid_below or not _is_finite(v):
            continue
        out[i] = v * applied

    return DepthMap(values=out, width=width, height=height,
                    source_format=fmt, scale=applied)


def _require_pillow():
    try:
        from PIL import Image
    except ImportError as err:
        raise DepthError(
            "Reading depth from PNG or TIFF needs Pillow. Install it with "
            "`pip install pillow`, or export the depth as .npy instead."
        ) from err
    return Image


def _read_raster(path: Path):
    """
    16-bit PNG or TIFF.

    Pillow opens 16-bit greyscale PNG as mode ``I`` (32-bit signed) and 16-bit
    TIFF as ``I;16``. Both are read through ``getdata()`` rather than
    ``convert("F")``, because ``convert`` on mode ``I`` divides by 256 — the
    same silent 8-bit crush that makes a raw depth PNG look empty.
    """
    Image = _require_pillow()
    try:
        with Image.open(path) as img:
            img.load()
            if img.mode in ("RGB", "RGBA", "P"):
                raise DepthError(
                    f"{path.name} is a colour image, not a depth map. A depth "
                    f"map is single-channel; if this is a colourised preview, "
                    f"the original values are already gone.")
            width, height = img.size
            # Pillow 11 deprecates getdata() in favour of get_flattened_data();
            # Potato supports both, so prefer the new name where it exists
            # rather than emitting a DeprecationWarning per pixel-read.
            reader = getattr(img, "get_flattened_data", None) or img.getdata
            data = list(reader())
    except DepthError:
        raise
    except (OSError, ValueError) as err:
        raise DepthError(f"cannot decode {path.name}: {err}") from err

    if data and isinstance(data[0], (tuple, list)):
        data = [d[0] for d in data]
    return [float(v) for v in data], width, height


def _read_numpy(path: Path, fmt: str):
    try:
        import numpy as np
    except ImportError as err:  # pragma: no cover - numpy is a hard dependency
        raise DepthError("Reading .npy depth needs numpy.") from err

    try:
        if fmt == "npz":
            with np.load(path) as bundle:
                keys = list(bundle.keys())
                if not keys:
                    raise DepthError(f"{path.name} contains no arrays")
                # First array, named or not. An .npz with several arrays is
                # ambiguous, so the choice is stated in the log rather than
                # silently taken.
                if len(keys) > 1:
                    logger.info(
                        "%s holds %d arrays (%s); reading '%s' as the depth "
                        "channel.", path.name, len(keys), ", ".join(keys),
                        keys[0])
                arr = bundle[keys[0]]
        else:
            arr = np.load(path)
    except DepthError:
        raise
    except (OSError, ValueError) as err:
        raise DepthError(f"cannot read {path.name}: {err}") from err

    return _as_depth_grid(np, np.asarray(arr), path.name)


def _as_depth_grid(np, arr, name):
    """
    An (H, W) grid out of whatever shape the array arrived in.

    Deliberately **not** ``np.squeeze``: that also collapses a leading spatial
    axis, so a single-row depth map — a laser profile, a cropped strip — became
    1-D and was rejected as "not 2-D". Only batch and channel axes are stripped,
    and only where they are unambiguous.
    """
    while arr.ndim > 2 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim == 3:
        if arr.shape[2] > 1:
            logger.info(
                "%s has %d channels; reading the first as depth.",
                name, arr.shape[2])
        arr = arr[:, :, 0]
    if arr.ndim != 2:
        raise DepthError(
            f"{name} holds a {arr.ndim}-dimensional array; a depth map "
            f"must be 2-D (height x width).")
    height, width = arr.shape
    return [float(v) for v in arr.reshape(-1)], int(width), int(height)


def _read_pfm(path: Path):
    """
    Portable Float Map, the Middlebury and optical-flow convention.

    PFM stores rows **bottom-up**, which is the detail that gets missed: a
    vertically mirrored depth map looks plausible and unprojects into a scene
    that is upside down for no visible reason.
    """
    with open(path, "rb") as fh:
        header = fh.readline().strip()
        if header not in (b"Pf", b"PF"):
            raise DepthError(f"{path.name} is not a PFM file")
        channels = 3 if header == b"PF" else 1

        dims = _pfm_token(fh)
        try:
            width, height = (int(t) for t in dims.split())
        except ValueError as err:
            raise DepthError(f"{path.name} has a malformed size line") from err

        try:
            scale = float(_pfm_token(fh))
        except ValueError as err:
            raise DepthError(f"{path.name} has a malformed scale line") from err
        endian = "<" if scale < 0 else ">"

        count = width * height * channels
        raw = fh.read(count * 4)
    if len(raw) < count * 4:
        raise DepthError(f"{path.name} is truncated")

    values = list(struct.unpack(f"{endian}{count}f", raw))
    if channels == 3:
        values = values[0::3]

    rows = [values[r * width:(r + 1) * width] for r in range(height)]
    rows.reverse()
    flat = [v for row in rows for v in row]
    return flat, width, height


def _pfm_token(fh) -> str:
    """Next non-comment line of a PFM header."""
    while True:
        line = fh.readline()
        if not line:
            raise DepthError("PFM header ended early")
        text = line.strip()
        if text and not text.startswith(b"#"):
            return text.decode("ascii", "replace")


def _read_exr(path: Path):
    try:
        import imageio.v3 as iio
    except ImportError as err:
        raise DepthError(
            "Reading EXR depth needs imageio with its OpenEXR plugin: "
            "`pip install imageio[openexr]`. Or convert first: "
            "`python -c \"import imageio.v3 as i, numpy as n; "
            "n.save('depth.npy', i.imread('depth.exr'))\"`."
        ) from err

    try:
        import numpy as np
        arr = np.asarray(iio.imread(path))
    except Exception as err:  # imageio raises a wide variety
        raise DepthError(f"cannot decode {path.name}: {err}") from err

    return _as_depth_grid(np, arr, path.name)


# ---------------------------------------------------------------------------
# Describing and windowing
# ---------------------------------------------------------------------------

def describe(depth: DepthMap) -> Dict[str, Any]:
    """
    Stats the viewer needs before its first render.

    ``invalid_fraction`` is reported rather than hidden: a map that is 80%
    holes is a real and common state (a stereo rig on a textureless wall), and
    an annotator who cannot see that will read the holes as geometry.
    """
    finite = depth.finite()
    if not finite:
        return {
            "width": depth.width, "height": depth.height,
            "source_format": depth.source_format, "scale": depth.scale,
            "min": None, "max": None, "p2": None, "p98": None,
            "invalid_fraction": 1.0,
            "note": "every pixel is a non-measurement — check depth_scale and "
                    "whether this file really holds depth.",
        }

    low, high = percentile_window(depth)
    return {
        "width": depth.width,
        "height": depth.height,
        "source_format": depth.source_format,
        "scale": depth.scale,
        "min": min(finite),
        "max": max(finite),
        "p2": low,
        "p98": high,
        "invalid_fraction": 1.0 - len(finite) / float(depth.count or 1),
    }


def percentile_window(depth: DepthMap) -> Tuple[float, float]:
    """The default [near, far], clipping the tails. Invalid pixels excluded."""
    finite = depth.finite()
    if not finite:
        return 0.0, 1.0
    if len(finite) > PERCENTILE_SAMPLE_LIMIT:
        stride = len(finite) // PERCENTILE_SAMPLE_LIMIT + 1
        finite = finite[::stride]
    finite.sort()
    last = len(finite) - 1

    def at(pct):
        return float(finite[max(0, min(last, int(round(last * pct / 100.0))))])

    low, high = at(DEFAULT_LOW_PERCENTILE), at(DEFAULT_HIGH_PERCENTILE)
    if high <= low:
        return float(finite[0]), float(finite[-1]) + 1e-6
    return low, high


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

#: Anchor stops for each colormap, linearly interpolated in sRGB.
#:
#: These are **approximations** of the matplotlib maps, not the exact 256-entry
#: tables. Ten stops through a map designed to be perceptually linear is close
#: enough that the difference is invisible at 8-bit output, and it avoids
#: carrying 768 numbers per map — or a matplotlib dependency — for a lookup.
#: "turbo" is the default because depth is a ratio quantity being read for
#: relative distance, and a rainbow map is genuinely easier to read distances
#: off than a luminance ramp. It is a poor choice for anything being read
#: quantitatively, which is why the cursor reports metres.
COLORMAPS: Dict[str, List[Tuple[float, Tuple[int, int, int]]]] = {
    "turbo": [
        (0.00, (48, 18, 59)), (0.125, (70, 107, 227)), (0.25, (54, 168, 249)),
        (0.375, (25, 217, 191)), (0.50, (91, 246, 108)), (0.625, (181, 250, 47)),
        (0.75, (246, 199, 34)), (0.875, (250, 118, 20)), (1.00, (122, 4, 3)),
    ],
    "viridis": [
        (0.00, (68, 1, 84)), (0.125, (72, 40, 120)), (0.25, (62, 74, 137)),
        (0.375, (49, 104, 142)), (0.50, (38, 130, 142)), (0.625, (31, 158, 137)),
        (0.75, (53, 183, 121)), (0.875, (109, 205, 89)), (1.00, (253, 231, 37)),
    ],
    "magma": [
        (0.00, (0, 0, 4)), (0.125, (28, 16, 68)), (0.25, (79, 18, 123)),
        (0.375, (129, 37, 129)), (0.50, (181, 54, 122)), (0.625, (229, 80, 100)),
        (0.75, (251, 135, 97)), (0.875, (254, 194, 135)), (1.00, (252, 253, 191)),
    ],
    "gray": [(0.00, (0, 0, 0)), (1.00, (255, 255, 255))],
}

#: What an invalid pixel is painted. Not black and not white: both occur in
#: every colormap, so a hole would be indistinguishable from real near or far
#: depth. Magenta occurs in none of them.
INVALID_COLOR = (255, 0, 220)

DEFAULT_COLORMAP = "turbo"


def sample_colormap(name: str, t: float) -> Tuple[int, int, int]:
    """Colour at ``t`` in [0, 1], by linear interpolation between stops."""
    stops = COLORMAPS.get(name) or COLORMAPS[DEFAULT_COLORMAP]
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    for i in range(1, len(stops)):
        t1, c1 = stops[i]
        if t <= t1:
            t0, c0 = stops[i - 1]
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(round(c0[k] + (c1[k] - c0[k]) * f))
                         for k in range(3))
    return stops[-1][1]


def colorize(depth: DepthMap,
             window: Optional[Tuple[float, float]] = None,
             colormap: str = DEFAULT_COLORMAP,
             *,
             invert: bool = False) -> bytes:
    """
    RGB bytes, 3 per pixel, row-major.

    ``invert`` puts near at the bright end, which is what a "closer is hotter"
    reading expects. Off by default: with turbo, low-to-high runs dark-blue to
    dark-red and near-is-blue matches every published depth figure.
    """
    lo, hi = window if window else percentile_window(depth)
    span = (hi - lo) or 1.0
    lut = [sample_colormap(colormap, i / 255.0) for i in range(256)]

    out = bytearray(depth.count * 3)
    for i, v in enumerate(depth.values):
        if not _is_finite(v):
            out[i * 3:i * 3 + 3] = bytes(INVALID_COLOR)
            continue
        t = (v - lo) / span
        if invert:
            t = 1.0 - t
        index = int(round(255 * (0.0 if t < 0 else (1.0 if t > 1 else t))))
        out[i * 3:i * 3 + 3] = bytes(lut[index])
    return bytes(out)


def to_png(depth: DepthMap,
           window: Optional[Tuple[float, float]] = None,
           colormap: str = DEFAULT_COLORMAP,
           *,
           invert: bool = False) -> bytes:
    """A colourised PNG the browser can display."""
    Image = _require_pillow()
    import io

    rgb = colorize(depth, window, colormap, invert=invert)
    img = Image.frombytes("RGB", (depth.width, depth.height), rgb)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The wire format for raw values
# ---------------------------------------------------------------------------

def to_wire(depth: DepthMap, extra: Optional[Dict[str, Any]] = None) -> bytes:
    """
    ``DPT1``: header JSON then float32 metres, row-major.

    The client needs the real values, not the colours, to report the depth
    under the cursor. A colourmapped PNG cannot be inverted back to metres —
    the map is not injective at 8 bits — so the numbers travel separately.

        magic       4 bytes  b"DPT1"
        header_len  uint32 LE
        header      JSON
        values      float32 * width * height   (NaN = no measurement)
    """
    header: Dict[str, Any] = {
        "version": 1,
        "width": depth.width,
        "height": depth.height,
        "source_format": depth.source_format,
        "scale": depth.scale,
        "units": "m",
    }
    if extra:
        header.update(extra)
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")

    out = bytearray(DEPTH_MAGIC)
    out += struct.pack("<I", len(blob))
    out += blob
    out += _le_floats(depth.values)
    return bytes(out)


def from_wire(data: bytes) -> Tuple[Dict[str, Any], DepthMap]:
    """Inverse of :func:`to_wire`, so the format has a round-trip test."""
    if len(data) < 8 or data[:4] != DEPTH_MAGIC:
        raise DepthError("not a DPT1 depth buffer")
    (header_len,) = struct.unpack("<I", data[4:8])
    header = json.loads(data[8:8 + header_len].decode("utf-8"))
    offset = 8 + header_len
    count = int(header["width"]) * int(header["height"])

    values = array("f")
    values.frombytes(data[offset:offset + count * 4])
    import sys
    if sys.byteorder != "little":
        values.byteswap()
    return header, DepthMap(values=values, width=int(header["width"]),
                            height=int(header["height"]),
                            source_format=header.get("source_format", ""),
                            scale=float(header.get("scale", 1.0)))


def _le_floats(values: array) -> bytes:
    import sys
    if sys.byteorder == "little":
        return values.tobytes()
    copy = array(values.typecode, values)
    copy.byteswap()
    return copy.tobytes()


# ---------------------------------------------------------------------------
# Depth -> geometry
# ---------------------------------------------------------------------------

def unproject(depth: DepthMap,
              intrinsics: Sequence[float],
              *,
              stride: int = 1,
              max_points: int = 500_000,
              frame: str = "z_up",
              extrinsic: Optional[Sequence[Sequence[float]]] = None,
              colors: Optional[bytes] = None):
    """
    Depth plus intrinsics into a :class:`~potato.media.pointcloud.PointCloud`.

    ``intrinsics`` is ``(fx, fy, cx, cy)``.

    ``frame`` selects the output axes:

    - ``"camera"`` — the optical frame: X right, Y **down**, Z forward.
    - ``"z_up"`` (default) — X forward, Y left, Z up, which is the convention
      every lidar format we read uses and the one the viewer assumes. Handing
      the viewer a camera-frame cloud would render the scene lying on its side
      with the ground vertical, and nothing would say why.

    ``extrinsic`` is an optional 4x4 camera-to-world matrix, applied instead of
    the axis permutation when the rig's real pose is known.

    Points carry their **pixel index** in the source image as the source index,
    so a ``segment_3d`` drawn on the unprojected cloud maps back to pixels.
    """
    from potato.media.pointcloud import U32, PointCloud

    fx, fy, cx, cy = (float(v) for v in intrinsics)
    if fx == 0 or fy == 0:
        raise DepthError(
            "focal length is zero; check the calibration's fx/fy. Unprojecting "
            "with it would put every point on the optical axis.")

    step = max(1, int(stride))
    positions = array("f")
    indices = array(U32)
    rgb = bytearray() if colors else None

    for row in range(0, depth.height, step):
        base = row * depth.width
        for col in range(0, depth.width, step):
            z = depth.values[base + col]
            if not _is_finite(z) or z <= 0:
                continue
            x = (col - cx) * z / fx
            y = (row - cy) * z / fy
            point = _to_frame(x, y, z, frame, extrinsic)
            positions.extend(point)
            indices.append(base + col)
            if rgb is not None:
                rgb += colors[(base + col) * 3:(base + col) * 3 + 3]
            if max_points and len(indices) >= max_points:
                logger.info(
                    "Unprojection stopped at %d points; raise max_points or "
                    "raise stride to cover the whole map.", max_points)
                return PointCloud(positions=positions, colors=rgb,
                                  source_format="depth",
                                  original_count=len(indices),
                                  indices=indices)

    return PointCloud(positions=positions, colors=rgb, source_format="depth",
                      original_count=len(indices), indices=indices)


def _to_frame(x, y, z, frame, extrinsic):
    if extrinsic is not None:
        m = extrinsic
        return (
            m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
        )
    if frame == "camera":
        return (x, y, z)
    # z_up: forward becomes X, left becomes Y, up becomes Z. The negations are
    # not cosmetic -- the optical frame has Y pointing DOWN, so a missing sign
    # puts the sky underground and the fitted box heights come out negative.
    return (z, -x, -y)


def pixel_of(depth: DepthMap, index: int) -> Tuple[int, int]:
    """``(column, row)`` for a flat index. The inverse of the unprojection key."""
    if depth.width <= 0:
        return (0, 0)
    return (index % depth.width, index // depth.width)
