"""
Readers for multichannel microscopy: OME-Zarr and OME-TIFF.

Both formats hold an N-dimensional image (some of ``t``, ``c``, ``z`` plus
``y`` and ``x``) at several resolutions. This module reads them into one
interface, :class:`OmeImage`, which the microscopy schema uses to composite
tiles on the server (``potato/science/microscopy.py``):

* ``axes`` -- the axis letters in storage order, lower case (``"tczyx"``);
* ``levels`` -- the shape of every pyramid level, full resolution first;
* ``channels`` -- name, colour and display window per channel, from the
  ``omero`` block (OME-Zarr) or the OME-XML ``Channel`` elements (OME-TIFF);
* ``read_region(level, c, z, t, y0, y1, x0, x1)`` -- one 2D plane region;
* ``labels`` and ``read_label_region(...)`` -- integer label images: the
  OME-Zarr ``labels/`` group, or a separate label TIFF for an OME-TIFF.

## What is read

OME-Zarr 0.4 (Zarr v2, attributes in ``.zattrs``) and 0.5 (Zarr v3,
attributes under the ``ome`` key of ``zarr.json``), through zarr-python. A
multiscale that lists its axes under ``coordinateSystems`` rather than
``axes`` (the shape the current NGFF development specification uses) is read
too: the first coordinate system's axes are taken. Downsampling factors come
from the level shapes, which every version agrees on, rather than from the
``scale`` transforms, which changed form between versions. Physical pixel
sizes come from the level-0 ``scale`` transform when there is one.

OME-TIFF through tifffile, including pyramids stored as SubIFDs. tifffile
reads the OME-XML into the series' axes; channel names and colours are read
from the XML here.

zarr-python and tifffile are optional (``pip install
potato-annotation[microscopy]``) and imported only when a file is opened.

## Limits

A Zarr array is read a region at a time, so a large OME-Zarr costs only the
chunks a tile touches. TIFF pages are decoded whole, so a plane above
``max_pixels`` (default 64 megapixels) is refused with a message rather than
decoded; a large OME-TIFF should be pyramidal, in which case the coarse levels
serve the zoomed-out views. Decoded TIFF planes are kept in a small LRU cache.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Above this many pixels a single TIFF page is not decoded.
DEFAULT_MAX_PIXELS = 64_000_000

#: Decoded TIFF planes kept in memory, in bytes, across all open files.
PLANE_CACHE_BYTES = 256 * 1024 * 1024

#: Default colours when a file names none: the usual order of a
#: fluorescence panel (blue nuclear stain first, then green, red, ...).
DEFAULT_COLOURS = ("0000ff", "00ff00", "ff0000", "ff00ff", "00ffff", "ffff00",
                   "ffffff", "ff8000")

_AXES = "tczyx"


class OmeError(RuntimeError):
    """Raised with a message the annotation page can show as it is."""


def _require(module: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise OmeError(
            f"Reading this microscopy file needs {module}, which is not installed. "
            "Install it with: pip install 'potato-annotation[microscopy]'") from exc


@dataclass
class Channel:
    index: int
    name: str
    color: str                  # six hex digits, no '#'
    start: float                # display window (contrast limits)
    end: float
    min: float                  # the range the window may move in
    max: float
    visible: bool = True

    def to_json(self) -> Dict[str, Any]:
        return {"index": self.index, "name": self.name, "color": "#" + self.color,
                "start": self.start, "end": self.end, "min": self.min,
                "max": self.max, "visible": self.visible}


@dataclass
class LabelImage:
    name: str
    axes: str
    levels: List[Tuple[int, ...]]
    arrays: List[Any] = field(default_factory=list, repr=False)
    colors: Dict[int, str] = field(default_factory=dict)


def _hex_colour(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lstrip("#").lower()
    if len(text) == 6 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return fallback


def _ome_xml_colour(value: Any, fallback: str) -> str:
    """OME-XML stores a colour as a signed 32-bit RGBA integer."""
    try:
        number = int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return fallback
    r, g, b = (number >> 24) & 255, (number >> 16) & 255, (number >> 8) & 255
    if r == g == b == 255 and fallback != "ffffff":
        # -1 (opaque white) is what many writers emit when no colour was set.
        return fallback
    return f"{r:02x}{g:02x}{b:02x}"


def _dtype_range(dtype) -> Tuple[float, float]:
    np = _require("numpy")
    dtype = np.dtype(dtype)
    if dtype.kind in "ui":
        info = np.iinfo(dtype)
        return float(info.min), float(info.max)
    if dtype.kind == "b":
        return 0.0, 1.0
    return 0.0, 1.0


class OmeImage:
    """One opened OME-Zarr or OME-TIFF image. See the module docstring."""

    kind = ""

    def __init__(self, path: str):
        self.path = str(path)
        self.axes = ""
        self.levels: List[Tuple[int, ...]] = []
        self.dtype = None
        self.channels: List[Channel] = []
        self.physical: Dict[str, Dict[str, Any]] = {}
        self.label_images: Dict[str, LabelImage] = {}
        self.max_pixels = DEFAULT_MAX_PIXELS

    # -- geometry ---------------------------------------------------------

    def _size(self, axis: str, level: int = 0) -> int:
        if axis not in self.axes:
            return 1
        return int(self.levels[level][self.axes.index(axis)])

    @property
    def size_x(self) -> int:
        return self._size("x")

    @property
    def size_y(self) -> int:
        return self._size("y")

    @property
    def size_c(self) -> int:
        return self._size("c")

    @property
    def size_z(self) -> int:
        return self._size("z")

    @property
    def size_t(self) -> int:
        return self._size("t")

    def level_factor(self, level: int) -> Tuple[float, float]:
        """``(fy, fx)``: how many level-0 pixels one pixel of ``level`` covers."""
        return (self.size_y / self._size("y", level),
                self.size_x / self._size("x", level))

    @property
    def labels(self) -> List[str]:
        return list(self.label_images)

    def check_plane(self, c: int, z: int, t: int) -> None:
        for axis, value, size in (("c", c, self.size_c), ("z", z, self.size_z),
                                  ("t", t, self.size_t)):
            if not (0 <= int(value) < size):
                raise OmeError(f"{axis}={value} is outside this image, which has "
                               f"{size} along {axis}.")

    # -- reading ----------------------------------------------------------

    def read_region(self, level: int, c: int, z: int, t: int,
                    y0: int, y1: int, x0: int, x1: int):
        raise NotImplementedError

    def read_label_region(self, name: str, level: int, z: int, t: int,
                          y0: int, y1: int, x0: int, x1: int, step: int = 1):
        label = self.label_images.get(name)
        if label is None:
            raise OmeError(f"This image has no label image named {name!r}. "
                           f"It has: {', '.join(self.labels) or 'none'}.")
        if not 0 <= level < len(label.levels):
            raise OmeError(f"Label image {name!r} has no level {level}.")
        return _index(label.arrays[level], label.axes, label.levels[level],
                      0, z, t, y0, y1, x0, x1, step)

    def label_factor(self, name: str, level: int) -> Tuple[float, float]:
        label = self.label_images[name]
        shape = label.levels[level]
        return (self.size_y / shape[label.axes.index("y")],
                self.size_x / shape[label.axes.index("x")])

    # -- defaults ---------------------------------------------------------

    def _fill_channel_defaults(self, named: Sequence[Dict[str, Any]]) -> None:
        """Build :attr:`channels` from what the file named, estimating windows
        the file left out from the coarsest level."""
        lo, hi = _dtype_range(self.dtype)
        channels = []
        for index in range(self.size_c):
            meta = named[index] if index < len(named) else {}
            colour = _hex_colour(meta.get("color"), DEFAULT_COLOURS[index % len(DEFAULT_COLOURS)])
            name = str(meta.get("name") or f"Channel {index + 1}")
            start, end = meta.get("start"), meta.get("end")
            rmin, rmax = meta.get("min"), meta.get("max")
            range_lo, range_hi = lo, hi
            if (start is None or end is None or not float(end) > float(start)
                    or rmax is None):
                est_start, est_end, data_lo, data_hi = self._estimate_window(index)
                if start is None or end is None or not float(end) > float(start):
                    start, end = est_start, est_end
                kind = _require("numpy").dtype(self.dtype).kind if self.dtype is not None else "u"
                if kind == "f":
                    range_lo, range_hi = data_lo, data_hi
                elif kind == "u" and data_hi >= 1:
                    # A 12-bit camera stores into uint16; a slider running to
                    # 65535 would leave the whole signal in its first 6%. The
                    # smallest bit depth that holds the data is the range.
                    range_hi = min(hi, float(2 ** math.ceil(math.log2(data_hi + 1)) - 1))
            rmin = float(rmin) if rmin is not None else range_lo
            rmax = float(rmax) if rmax is not None else range_hi
            channels.append(Channel(index=index, name=name, color=colour,
                                    start=float(start), end=float(end),
                                    min=min(rmin, float(start)), max=max(rmax, float(end)),
                                    visible=bool(meta.get("active", True))))
        self.channels = channels

    def _estimate_window(self, c: int) -> Tuple[float, float, float, float]:
        """Contrast limits from the 0.5th and 99.8th percentiles of the
        coarsest level's middle plane: the usual auto-contrast, which ignores
        a few hot pixels."""
        np = _require("numpy")
        level = len(self.levels) - 1
        try:
            plane = self.read_region(level, c, self.size_z // 2, 0, 0,
                                     self._size("y", level), 0, self._size("x", level))
            data = np.asarray(plane, dtype="float64").ravel()
        except OmeError:
            raise
        except Exception as exc:  # noqa: BLE001 - the window is a nicety
            logger.warning("Could not estimate a display window for channel %d of %s: %s",
                           c, os.path.basename(self.path), exc)
            lo, hi = _dtype_range(self.dtype)
            return lo, hi, lo, hi
        if data.size == 0:
            return 0.0, 1.0, 0.0, 1.0
        p_lo, p_hi = (float(v) for v in np.percentile(data, [0.5, 99.8]))
        d_lo, d_hi = float(data.min()), float(data.max())
        if not p_hi > p_lo:
            p_lo, p_hi = d_lo, d_hi if d_hi > d_lo else d_lo + 1.0
        return p_lo, p_hi, d_lo, d_hi

    def describe(self) -> Dict[str, Any]:
        return {
            "format": self.kind,
            "axes": self.axes,
            "width": self.size_x, "height": self.size_y,
            "size_c": self.size_c, "size_z": self.size_z, "size_t": self.size_t,
            "dtype": str(self.dtype),
            "pyramid": [{"level": i, "width": self._size("x", i),
                         "height": self._size("y", i)} for i in range(len(self.levels))],
            "channels": [c.to_json() for c in self.channels],
            "physical": self.physical,
            "labels": self.labels,
        }


def _index(array, axes: str, shape: Sequence[int], c: int, z: int, t: int,
           y0: int, y1: int, x0: int, x1: int, step: int = 1):
    """Read one 2D region of an ``axes``-ordered array."""
    np = _require("numpy")
    ny, nx = shape[axes.index("y")], shape[axes.index("x")]
    y0, y1 = max(0, int(y0)), min(int(ny), int(y1))
    x0, x1 = max(0, int(x0)), min(int(nx), int(x1))
    if y1 <= y0 or x1 <= x0:
        return np.zeros((0, 0), dtype=getattr(array, "dtype", "uint16"))
    step = max(1, int(step))
    selection = []
    for axis, size in zip(axes, shape):
        if axis == "y":
            selection.append(slice(y0, y1, step))
        elif axis == "x":
            selection.append(slice(x0, x1, step))
        else:
            value = {"c": c, "z": z, "t": t}.get(axis, 0)
            selection.append(min(int(value), int(size) - 1))
    return np.asarray(array[tuple(selection)])


# ---------------------------------------------------------------------------
# OME-Zarr
# ---------------------------------------------------------------------------

def _ngff(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """The NGFF block: under ``ome`` from 0.5 on, at the top level before."""
    if isinstance(attrs.get("ome"), dict):
        return attrs["ome"]
    return attrs


def _axis_names(multiscale: Dict[str, Any]) -> List[str]:
    axes = multiscale.get("axes")
    if not axes:
        systems = multiscale.get("coordinateSystems") or []
        if systems and isinstance(systems[0], dict):
            axes = systems[0].get("axes")
    if not axes:
        return []
    names = []
    for axis in axes:
        names.append(str(axis.get("name") if isinstance(axis, dict) else axis).lower())
    return names


def _axis_units(multiscale: Dict[str, Any]) -> Dict[str, str]:
    axes = multiscale.get("axes")
    if not axes:
        systems = multiscale.get("coordinateSystems") or []
        axes = systems[0].get("axes") if systems and isinstance(systems[0], dict) else []
    return {str(a.get("name")).lower(): str(a.get("unit"))
            for a in axes or [] if isinstance(a, dict) and a.get("unit")}


def _scale_of(dataset: Dict[str, Any]) -> Optional[List[float]]:
    for transform in dataset.get("coordinateTransformations") or []:
        if not isinstance(transform, dict):
            continue
        if transform.get("type") == "scale" and isinstance(transform.get("scale"), list):
            return [float(v) for v in transform["scale"]]
        if transform.get("type") == "sequence":
            for inner in transform.get("transformations") or []:
                if isinstance(inner, dict) and inner.get("type") == "scale":
                    return [float(v) for v in inner.get("scale") or []]
    return None


def _multiscale(group, what: str):
    """``(axes, [arrays], [shapes], multiscale dict)`` of a multiscale group."""
    attrs = _ngff(dict(group.attrs))
    multiscales = attrs.get("multiscales")
    if not multiscales or not isinstance(multiscales, list):
        raise OmeError(f"{what} has no 'multiscales' metadata, so it is not an "
                       "OME-Zarr image.")
    multiscale = multiscales[0]
    names = _axis_names(multiscale)
    datasets = multiscale.get("datasets") or []
    if not datasets:
        raise OmeError(f"{what} lists no resolution levels (multiscales.datasets).")
    arrays, shapes = [], []
    for dataset in datasets:
        path = str(dataset.get("path", ""))
        try:
            array = group[path]
        except KeyError:
            raise OmeError(f"{what} names a level '{path}' that is not in the store.")
        arrays.append(array)
        shapes.append(tuple(int(s) for s in array.shape))
    ndim = len(shapes[0])
    if not names:
        # 0.1-0.3 had no axes: the dimensions were always (t, c, z, y, x).
        names = list(_AXES[-ndim:])
    if len(names) != ndim:
        raise OmeError(f"{what} names {len(names)} axes but its arrays have {ndim} "
                       "dimensions.")
    unknown = [n for n in names if n not in _AXES]
    if unknown:
        raise OmeError(f"{what} has axes {', '.join(unknown)}; only t, c, z, y and x "
                       "are supported.")
    if "y" not in names or "x" not in names:
        raise OmeError(f"{what} has no y and x axes.")
    return "".join(names), arrays, shapes, multiscale


class OmeZarrImage(OmeImage):
    kind = "ome-zarr"

    def __init__(self, path: str):
        super().__init__(path)
        zarr = _require("zarr")
        name = os.path.basename(os.path.normpath(path))
        try:
            root = zarr.open_group(store=str(path), mode="r")
        except Exception as exc:  # noqa: BLE001 - zarr raises many types
            raise OmeError(f"{name} could not be opened as a Zarr group ({exc}). "
                           "An OME-Zarr 0.5 image needs zarr-python 3.") from exc
        self._root = root
        attrs = _ngff(dict(root.attrs))
        if "plate" in attrs or "bioformats2raw.layout" in attrs:
            raise OmeError(f"{name} is an HCS plate or a bioformats2raw container. Point "
                           "the item at one image inside it (for example "
                           f"{name}/0 or {name}/A/1/0).")
        self.axes, self._arrays, self.levels, multiscale = _multiscale(root, name)
        self.dtype = self._arrays[0].dtype
        units = _axis_units(multiscale)
        scale = _scale_of(multiscale["datasets"][0]) or []
        for axis, value in zip(self.axes, scale):
            if axis in "zyx":
                self.physical[axis] = {"size": value, "unit": units.get(axis, "")}

        named = []
        omero = attrs.get("omero") or {}
        for channel in omero.get("channels") or []:
            window = channel.get("window") or {}
            named.append({"name": channel.get("label"), "color": channel.get("color"),
                          "start": window.get("start"), "end": window.get("end"),
                          "min": window.get("min"), "max": window.get("max"),
                          "active": channel.get("active", True)})
        self._fill_channel_defaults(named)
        self._read_labels(root, name)

    def _read_labels(self, root, name: str) -> None:
        try:
            labels_group = root["labels"]
        except KeyError:
            return
        except Exception:  # noqa: BLE001
            return
        listed = _ngff(dict(labels_group.attrs)).get("labels") or []
        for label_name in listed:
            try:
                group = labels_group[str(label_name)]
                axes, arrays, shapes, _ms = _multiscale(group, f"{name}/labels/{label_name}")
            except (KeyError, OmeError) as exc:
                logger.warning("Skipping label image %s of %s: %s", label_name, name, exc)
                continue
            if "c" in axes and shapes[0][axes.index("c")] > 1:
                logger.warning("Skipping label image %s of %s: it has several channels.",
                               label_name, name)
                continue
            colors = {}
            image_label = _ngff(dict(group.attrs)).get("image-label") or {}
            for entry in image_label.get("colors") or []:
                try:
                    rgba = entry.get("rgba") or []
                    colors[int(entry["label-value"])] = "{:02x}{:02x}{:02x}".format(*rgba[:3])
                except (KeyError, TypeError, ValueError):
                    continue
            self.label_images[str(label_name)] = LabelImage(
                name=str(label_name), axes=axes, levels=shapes, arrays=arrays, colors=colors)

    def read_region(self, level, c, z, t, y0, y1, x0, x1, step: int = 1):
        if not 0 <= level < len(self.levels):
            raise OmeError(f"This image has no pyramid level {level}.")
        return _index(self._arrays[level], self.axes, self.levels[level],
                      c, z, t, y0, y1, x0, x1, step)


# ---------------------------------------------------------------------------
# OME-TIFF
# ---------------------------------------------------------------------------

class _PlaneCache:
    """Decoded TIFF pages, least recently used first out, bounded in bytes."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0
        self._items: "OrderedDict[tuple, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key, value) -> None:
        size = int(getattr(value, "nbytes", 0))
        if size > self.limit:
            return
        with self._lock:
            if key in self._items:
                return
            self._items[key] = value
            self.used += size
            while self.used > self.limit and self._items:
                _old, dropped = self._items.popitem(last=False)
                self.used -= int(getattr(dropped, "nbytes", 0))


_PLANES = _PlaneCache(PLANE_CACHE_BYTES)


def _tiff_axes(series_axes: str, page_axes: str) -> Tuple[str, str, Dict[str, str]]:
    """Map tifffile axis letters to ours. Returns (outer, page, rename)."""
    rename = {"T": "t", "C": "c", "Z": "z", "Y": "y", "X": "x"}
    if "C" not in series_axes and "S" in series_axes:
        rename["S"] = "c"
    outer = series_axes[: len(series_axes) - len(page_axes)]
    return outer, page_axes, rename


class OmeTiffImage(OmeImage):
    kind = "ome-tiff"

    def __init__(self, path: str, max_pixels: int = DEFAULT_MAX_PIXELS):
        super().__init__(path)
        self.max_pixels = int(max_pixels)
        tifffile = _require("tifffile")
        name = os.path.basename(path)
        try:
            self._tif = tifffile.TiffFile(str(path))
        except Exception as exc:  # noqa: BLE001
            raise OmeError(f"{name} could not be read as a TIFF ({exc}).") from exc
        self._lock = threading.Lock()
        series = self._tif.series[0]
        self._series = series
        series_axes = series.axes.upper()
        page_axes = series.keyframe.axes.upper()
        if not series_axes.endswith(page_axes):
            raise OmeError(f"{name} stores its planes in an order this reader does not "
                           f"support ({series_axes} with pages of {page_axes}).")
        outer, page, rename = _tiff_axes(series_axes, page_axes)
        shape = tuple(int(s) for s in series.shape)
        names = []
        kept_shape = []
        for letter, size in zip(series_axes, shape):
            ours = rename.get(letter)
            if ours is None:
                if size == 1:
                    continue
                raise OmeError(f"{name} has an axis '{letter}' of size {size}; only T, C, "
                               "Z, Y and X are supported.")
            names.append(ours)
            kept_shape.append(size)
        if "y" not in names or "x" not in names:
            raise OmeError(f"{name} has no Y and X axes.")
        self._outer_letters = outer
        self._outer_shape = shape[: len(outer)]
        self._page_letters = page
        self._rename = rename
        self.axes = "".join(names)
        self.levels = []
        for level in series.levels:
            level_shape = dict(zip(series.axes.upper(), level.shape))
            self.levels.append(tuple(int(level_shape[ltr]) for ltr, size
                                     in zip(series_axes, shape) if ltr in rename or size != 1))
        self.dtype = series.dtype
        named = self._ome_channels()
        self._fill_channel_defaults(named)

    def _ome_channels(self) -> List[Dict[str, Any]]:
        xml = self._tif.ome_metadata
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}", 1)[0] + "}"
        pixels = root.find(f".//{ns}Pixels")
        if pixels is None:
            return []
        for axis, attr in (("x", "PhysicalSizeX"), ("y", "PhysicalSizeY"), ("z", "PhysicalSizeZ")):
            if pixels.get(attr):
                try:
                    self.physical[axis] = {"size": float(pixels.get(attr)),
                                           "unit": pixels.get(attr + "Unit", "µm")}
                except ValueError:
                    pass
        out = []
        for index, channel in enumerate(pixels.findall(f"{ns}Channel")):
            fallback = DEFAULT_COLOURS[index % len(DEFAULT_COLOURS)]
            out.append({"name": channel.get("Name"),
                        "color": _ome_xml_colour(channel.get("Color"), fallback)
                        if channel.get("Color") is not None else fallback})
        return out

    def _page_index(self, c: int, z: int, t: int) -> int:
        np = _require("numpy")
        if not self._outer_letters:
            return 0
        index = []
        for letter, size in zip(self._outer_letters, self._outer_shape):
            ours = self._rename.get(letter)
            value = {"c": c, "z": z, "t": t}.get(ours, 0)
            index.append(min(int(value), int(size) - 1))
        return int(np.ravel_multi_index(tuple(index), tuple(self._outer_shape)))

    def _page(self, level: int, c: int, z: int, t: int):
        if not 0 <= level < len(self.levels):
            raise OmeError(f"This image has no pyramid level {level}.")
        key_index = self._page_index(c, z, t)
        cache_key = (self.path, os.path.getmtime(self.path), level, key_index)
        plane = _PLANES.get(cache_key)
        if plane is None:
            pixels = self._size("y", level) * self._size("x", level)
            if pixels > self.max_pixels:
                raise OmeError(
                    f"Level {level} of {os.path.basename(self.path)} is "
                    f"{self._size('x', level)}x{self._size('y', level)} pixels, above the "
                    f"{self.max_pixels / 1e6:.0f} MP limit for decoding a TIFF plane. Save it "
                    "as a pyramidal (tiled) OME-TIFF or as OME-Zarr, or raise the schema's "
                    "max_pixels.")
            with self._lock:
                plane = self._tif.asarray(key=key_index, series=0, level=level)
            _PLANES.put(cache_key, plane)
        return plane

    def read_region(self, level, c, z, t, y0, y1, x0, x1, step: int = 1):
        np = _require("numpy")
        plane = self._page(level, c, z, t)
        page = self._page_letters
        # Reduce the page to (y, x): pick the channel from a samples axis.
        selection = []
        for letter in page:
            ours = self._rename.get(letter)
            if letter == "Y":
                selection.append(slice(max(0, y0), max(0, y1), max(1, step)))
            elif letter == "X":
                selection.append(slice(max(0, x0), max(0, x1), max(1, step)))
            elif ours == "c":
                selection.append(min(int(c), plane.shape[len(selection)] - 1))
            else:
                selection.append(0)
        return np.asarray(plane[tuple(selection)])

    def attach_label_tiff(self, name: str, path: str) -> None:
        """Use a separate integer TIFF as this image's label image."""
        self.label_images[name] = _label_tiff(name, path, self, self.max_pixels)


def _label_tiff(name: str, path: str, image: OmeImage, max_pixels: int) -> LabelImage:
    np = _require("numpy")
    tifffile = _require("tifffile")
    base = os.path.basename(path)
    with tifffile.TiffFile(str(path)) as tif:
        series = tif.series[0]
        if int(np.prod(series.shape)) > max_pixels * max(1, image.size_z * image.size_t):
            raise OmeError(f"The label image {base} is larger than the image it labels "
                           "allows; it was not read.")
        data = series.asarray()
        letters = series.axes.upper()
    if np.dtype(data.dtype).kind not in "ui":
        raise OmeError(f"The label image {base} holds {data.dtype} values; a label image "
                       "must hold integers (one id per cell, 0 for background).")
    keep = [i for i, ltr in enumerate(letters) if ltr in "TZYX" or data.shape[i] != 1]
    letters = "".join(letters[i] for i in keep)
    data = data.reshape(tuple(data.shape[i] for i in keep))
    if any(ltr not in "TZYX" for ltr in letters):
        raise OmeError(f"The label image {base} has axes {letters}; use T, Z, Y and X only.")
    axes = letters.lower()
    if (data.shape[axes.index("y")], data.shape[axes.index("x")]) != (image.size_y, image.size_x):
        raise OmeError(f"The label image {base} is {data.shape[axes.index('x')]}x"
                       f"{data.shape[axes.index('y')]} but the image is "
                       f"{image.size_x}x{image.size_y}; they must match.")
    return LabelImage(name=name, axes=axes, levels=[tuple(data.shape)], arrays=[data])


# ---------------------------------------------------------------------------
# Opening, with a cache
# ---------------------------------------------------------------------------

_OPEN: "OrderedDict[tuple, OmeImage]" = OrderedDict()
_OPEN_LOCK = threading.Lock()
_OPEN_LIMIT = 16


def is_ome_zarr(path: str) -> bool:
    name = os.path.basename(os.path.normpath(str(path))).lower()
    return name.endswith(".zarr") or (
        os.path.isdir(path) and (os.path.exists(os.path.join(path, "zarr.json"))
                                 or os.path.exists(os.path.join(path, ".zattrs"))))


def is_ome_tiff(path: str) -> bool:
    name = os.path.basename(str(path)).lower()
    return name.endswith((".ome.tif", ".ome.tiff", ".ome.tf2", ".ome.tf8", ".ome.btf",
                          ".tif", ".tiff"))


def _stamp(path: str) -> float:
    if os.path.isdir(path):
        newest = os.path.getmtime(path)
        for meta in ("zarr.json", ".zattrs", ".zgroup"):
            candidate = os.path.join(path, meta)
            if os.path.exists(candidate):
                newest = max(newest, os.path.getmtime(candidate))
        return newest
    return os.path.getmtime(path)


def open_ome(path: str, label_path: Optional[str] = None,
             max_pixels: int = DEFAULT_MAX_PIXELS) -> OmeImage:
    """
    Open an OME-Zarr directory or an OME-TIFF file, cached by path and
    modification time.

    ``label_path`` names a separate integer label TIFF (used as the label
    image named ``"cells"``); OME-Zarr label images come from the store's own
    ``labels/`` group.
    """
    path = str(path)
    if not os.path.exists(path):
        raise OmeError(f"{os.path.basename(path)} does not exist.")
    key = (os.path.realpath(path), _stamp(path),
           os.path.realpath(label_path) if label_path else None,
           _stamp(label_path) if label_path and os.path.exists(label_path) else None,
           int(max_pixels))
    with _OPEN_LOCK:
        cached = _OPEN.get(key)
        if cached is not None:
            _OPEN.move_to_end(key)
            return cached
    if os.path.isdir(path) or is_ome_zarr(path):
        image: OmeImage = OmeZarrImage(path)
        image.max_pixels = int(max_pixels)
    elif is_ome_tiff(path):
        image = OmeTiffImage(path, max_pixels=max_pixels)
    else:
        raise OmeError(f"{os.path.basename(path)} is not an OME-Zarr directory or an "
                       "OME-TIFF file.")
    if label_path:
        if not os.path.isfile(label_path):
            raise OmeError(f"The label image {os.path.basename(label_path)} does not exist.")
        image.label_images["cells"] = _label_tiff("cells", label_path, image, max_pixels)
    with _OPEN_LOCK:
        _OPEN[key] = image
        while len(_OPEN) > _OPEN_LIMIT:
            _OPEN.popitem(last=False)
    return image


def clear_cache() -> None:
    with _OPEN_LOCK:
        _OPEN.clear()


# ---------------------------------------------------------------------------
# Writing (example data and the label-array export)
# ---------------------------------------------------------------------------

def _create_array(group, name: str, data, chunks):
    """zarr 2 and 3 name the call differently."""
    if hasattr(group, "create_array"):
        array = group.create_array(name, shape=data.shape, dtype=data.dtype, chunks=chunks)
        array[...] = data
        return array
    return group.create_dataset(name, data=data, chunks=chunks)


def zarr_format_of(path: str) -> int:
    """2 for a Zarr v2 store (OME-Zarr 0.4), 3 for v3 (0.5 and later)."""
    return 3 if os.path.exists(os.path.join(str(path), "zarr.json")) else 2


def write_multiscale(group, levels: Sequence[Any], axes: str, zarr_format: int,
                     scale: Optional[Dict[str, float]] = None, units: Optional[Dict[str, str]] = None,
                     chunk: int = 256, extra: Optional[Dict[str, Any]] = None,
                     name: str = "image") -> None:
    """Write ``levels`` (full resolution first) into ``group`` as an NGFF
    multiscale image, with 0.4 metadata for Zarr v2 and 0.5 for v3."""
    scale = scale or {}
    units = units or {}
    types = {"t": "time", "c": "channel", "z": "space", "y": "space", "x": "space"}
    axes_meta = []
    for axis in axes:
        entry = {"name": axis, "type": types[axis]}
        if axis in units:
            entry["unit"] = units[axis]
        axes_meta.append(entry)
    datasets = []
    base_y = levels[0].shape[axes.index("y")]
    for index, data in enumerate(levels):
        factor = base_y / data.shape[axes.index("y")]
        level_scale = [float(scale.get(a, 1.0)) * (factor if a in "yx" else 1.0) for a in axes]
        chunks = tuple(min(chunk, s) if a in "yx" else 1 for a, s in zip(axes, data.shape))
        _create_array(group, str(index), data, chunks)
        datasets.append({"path": str(index), "coordinateTransformations": [
            {"type": "scale", "scale": level_scale}]})
    multiscale = {"name": name, "axes": axes_meta, "datasets": datasets}
    if zarr_format == 2:
        multiscale["version"] = "0.4"
        attrs = {"multiscales": [multiscale]}
        attrs.update(extra or {})
    else:
        attrs = {"ome": {"version": "0.5", "multiscales": [multiscale], **(extra or {})}}
    group.attrs.update(attrs)


def downsample_levels(data, axes: str, count: int, labels: bool = False) -> List[Any]:
    """A pyramid by 2x2 halving: means for intensities, the top-left sample
    for labels (averaging label ids would invent ids)."""
    np = _require("numpy")
    levels = [data]
    yi, xi = axes.index("y"), axes.index("x")
    for _ in range(max(0, count - 1)):
        prev = levels[-1]
        if prev.shape[yi] < 2 or prev.shape[xi] < 2:
            break
        if labels:
            index = [slice(None)] * prev.ndim
            index[yi] = slice(0, None, 2)
            index[xi] = slice(0, None, 2)
            levels.append(np.ascontiguousarray(prev[tuple(index)]))
            continue
        ny, nx = prev.shape[yi] // 2 * 2, prev.shape[xi] // 2 * 2
        index = [slice(None)] * prev.ndim
        index[yi] = slice(0, ny)
        index[xi] = slice(0, nx)
        cropped = prev[tuple(index)].astype("float64")
        shape = list(cropped.shape)
        shape[yi:yi + 1] = [ny // 2, 2]
        xi2 = xi + 1
        shape[xi2:xi2 + 1] = [nx // 2, 2]
        reduced = cropped.reshape(shape).mean(axis=(yi + 1, xi2 + 1))
        levels.append(reduced.astype(data.dtype))
    return levels


def label_metadata(colors: Dict[int, str], properties: Optional[List[Dict[str, Any]]] = None,
                   zarr_format: int = 3) -> Dict[str, Any]:
    """The ``image-label`` block for a label image."""
    entries = []
    for value, colour in sorted(colors.items()):
        colour = _hex_colour(colour, "808080")
        entries.append({"label-value": int(value),
                        "rgba": [int(colour[0:2], 16), int(colour[2:4], 16),
                                 int(colour[4:6], 16), 255]})
    block: Dict[str, Any] = {"colors": entries, "source": {"image": "../../"}}
    if properties:
        block["properties"] = properties
    if zarr_format == 2:
        block["version"] = "0.4"
    return {"image-label": block}


def write_labels_group(root, labels: Dict[str, Any], axes: str, zarr_format: int,
                       colors: Optional[Dict[str, Dict[int, str]]] = None,
                       properties: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                       scale: Optional[Dict[str, float]] = None, levels: int = 1,
                       chunk: int = 256) -> None:
    """Write ``labels/<name>`` images into an open root group."""
    group = root.require_group("labels")
    names = list(labels)
    if zarr_format == 2:
        group.attrs.update({"labels": names})
    else:
        group.attrs.update({"ome": {"version": "0.5", "labels": names}})
    for name, data in labels.items():
        sub = group.require_group(name)
        extra = label_metadata((colors or {}).get(name, {}),
                               (properties or {}).get(name), zarr_format)
        write_multiscale(sub, downsample_levels(data, axes, levels, labels=True), axes,
                         zarr_format, scale=scale, chunk=chunk, extra=extra, name=name)


def open_zarr_for_writing(path: str, zarr_format: int):
    zarr = _require("zarr")
    try:
        return zarr.open_group(store=str(path), mode="w", zarr_format=zarr_format)
    except TypeError:
        if zarr_format != 2:
            raise OmeError("Writing OME-Zarr 0.5 needs zarr-python 3.")
        return zarr.open_group(store=str(path), mode="w")


def omero_block(channels: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {"omero": {"channels": [
        {"label": c["name"], "color": _hex_colour(c.get("color"), "ffffff").upper(),
         "active": bool(c.get("active", True)),
         "window": {"start": c["start"], "end": c["end"], "min": c.get("min", 0),
                    "max": c.get("max", 65535)}} for c in channels]}}

