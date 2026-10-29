"""FITS images to PNG cutouts, with the WCS described as JSON.

:func:`fits_cutout` reads one image HDU of a FITS file (``.fits``, ``.fit``,
``.fts``, or any of them gzipped), takes a cutout around a position given in
pixels or in sky coordinates, scales it with an interval (min/max, zscale,
percentile) and a stretch (linear, sqrt, log, asinh), and returns:

* ``png``: 8-bit grey PNG bytes, north up as the file stores it (FITS row 1
  is the bottom row), blank (NaN) pixels transparent;
* ``wcs``: what a browser needs to show sky coordinates under the cursor: a
  grid of unit vectors sampled across the cutout (interpolated client-side,
  so any projection astropy reads, SIP included, is honoured), the cutout's
  own linear WCS keywords, the pixel scale and the north and east directions;
* ``meta``: the region read, the scaling limits and a few header values.

astropy (BSD-3-Clause) does the reading and the WCS work. It is imported when
a FITS file is first read, never at server boot, and a missing install
raises ``ConverterUnavailable`` naming the ``astro`` extra.

Pixel positions follow the FITS convention: the centre of the first pixel is
``(1, 1)``, as in ds9 and in a header's ``CRPIX``. astropy's own functions
count from 0; the conversion happens here and nowhere else.
"""

from __future__ import annotations

import math
import os
import re
import warnings
from typing import Any, Dict, List, Optional, Tuple

from potato.science.converters import ConverterUnavailable

STRETCHES = ("linear", "sqrt", "log", "asinh")
INTERVALS = ("minmax", "zscale", "percentile")

#: Defaults; the display passes its own options over these.
DEFAULTS: Dict[str, Any] = {
    "stretch": "linear",
    "interval": "zscale",
    "percentile": 99.5,
    "asinh_a": 0.1,
    "log_a": 1000.0,
    "invert": False,
}

#: Largest FITS file read at all (bytes on disk, compressed or not).
MAX_FILE_BYTES = 100 * 1024 * 1024
#: Largest image plane read when no cutout position is given.
MAX_IMAGE_PIXELS = 25_000_000
#: Largest cutout side, in pixels.
MAX_CUTOUT_SIDE = 4096
#: A whole image wider or taller than this is block-averaged down to it.
MAX_OUTPUT_SIDE = 1024
#: Output pixels per grid cell of the coordinate grid.
GRID_CELL = 16

_ANGLE = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\s*"
                    r"(arcsec|arcmin|deg|px|pix|pixels?|\"|'|″|′|°)?\s*$")
_ANGLE_UNITS = {"arcsec": 1 / 3600, '"': 1 / 3600, "″": 1 / 3600,
                "arcmin": 1 / 60, "'": 1 / 60, "′": 1 / 60, "deg": 1.0, "°": 1.0}


class FitsError(ValueError):
    """The file cannot be shown: not FITS, no image, too large, position off
    the image. The message is written for the person who set up the project."""


def _astropy():
    try:
        import numpy as np
        from astropy.io import fits
        from astropy.wcs import WCS
        from astropy.wcs import FITSFixedWarning
    except ImportError as e:
        raise ConverterUnavailable(
            f"Reading FITS files needs astropy, which is not installed ({e}). "
            f"Install it with: pip install 'potato-annotation[astro]'") from e
    return np, fits, WCS, FITSFixedWarning


def astropy_available() -> bool:
    """Whether astropy can be imported, checked without importing it."""
    import importlib.util
    return importlib.util.find_spec("astropy") is not None


# ---------------------------------------------------------------------------
# Option parsing (no astropy needed; used by config validation too)
# ---------------------------------------------------------------------------

def parse_size(value: Any) -> Optional[Tuple[str, float]]:
    """``("px", n)`` or ``("deg", angle)`` for a cutout size, or None.

    A number is pixels; text may carry a unit: ``"30 arcsec"``, ``"1.5'"``,
    ``"0.01 deg"``, ``"64 px"``. Raises ValueError for anything else.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("a size is a number of pixels or an angle such as '30 arcsec'")
    if isinstance(value, (int, float)):
        if not value > 0 or value != value:
            raise ValueError("a size must be greater than 0")
        return ("px", float(value))
    m = _ANGLE.match(str(value))
    if not m:
        raise ValueError(f"'{value}' is not a size; give pixels (64) or an angle "
                         f"('30 arcsec', '0.5 arcmin', '0.01 deg')")
    number, unit = float(m.group(1)), (m.group(2) or "px")
    if not number > 0:
        raise ValueError("a size must be greater than 0")
    if unit in _ANGLE_UNITS:
        return ("deg", number * _ANGLE_UNITS[unit])
    return ("px", number)


def parse_center(value: Any) -> Optional[Dict[str, Any]]:
    """A cutout centre: ``{"x": .., "y": ..}`` (FITS pixels, 1-based) or
    ``{"ra": .., "dec": ..}`` (degrees, or sexagesimal text such as
    ``"10:00:28.6"`` / ``"+02:12:21"``). Returns a normalised dict, or None.
    Raises ValueError for anything else."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("a position is a mapping with x and y, or ra and dec")
    has_px = "x" in value or "y" in value
    has_sky = "ra" in value or "dec" in value
    if has_px and has_sky:
        raise ValueError("give a position as x and y, or as ra and dec, not both")
    if has_px:
        out = {}
        for k in ("x", "y"):
            v = value.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise ValueError(f"{k} must be a pixel number (FITS convention: the first pixel is 1)")
            out[k] = float(v)
        return out
    if has_sky:
        ra, dec = value.get("ra"), value.get("dec")
        if ra is None or dec is None:
            raise ValueError("a sky position needs both ra and dec")
        ra_deg = _sky_number(ra, hours=True, what="ra")
        dec_deg = _sky_number(dec, hours=False, what="dec")
        if not -90.0 <= dec_deg <= 90.0:
            raise ValueError(f"dec {dec} is outside -90 to +90 degrees")
        return {"ra": ra_deg % 360.0, "dec": dec_deg}
    return None


def _sky_number(value: Any, hours: bool, what: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number of degrees or sexagesimal text")
    if isinstance(value, (int, float)):
        if value != value:
            raise ValueError(f"{what} is not a number")
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = re.split(r"[\s:hdms°′″'\"]+", text.strip().lstrip("+"))
    parts = [p for p in parts if p]
    sign = -1.0 if text.startswith("-") else 1.0
    try:
        nums = [abs(float(p)) for p in parts]
    except ValueError:
        raise ValueError(f"{what} '{value}' is neither degrees nor sexagesimal "
                         f"({'hh:mm:ss.s' if hours else '+dd:mm:ss.s'})") from None
    if not 1 <= len(nums) <= 3:
        raise ValueError(f"{what} '{value}' has {len(nums)} fields; write "
                         f"{'hh:mm:ss.s' if hours else '+dd:mm:ss.s'}")
    while len(nums) < 3:
        nums.append(0.0)
    deg = nums[0] + nums[1] / 60.0 + nums[2] / 3600.0
    return sign * deg * (15.0 if hours else 1.0)


def scaling_errors(opts: Dict[str, Any], where: str) -> List[str]:
    """Problems with stretch/interval options (display, panel or item)."""
    errors = []
    if "stretch" in opts and opts["stretch"] not in STRETCHES:
        errors.append(f"{where}.stretch '{opts['stretch']}' is not one of {', '.join(STRETCHES)}")
    if "interval" in opts and opts["interval"] not in INTERVALS:
        errors.append(f"{where}.interval '{opts['interval']}' is not one of {', '.join(INTERVALS)}")
    if "percentile" in opts:
        p = opts["percentile"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 < p <= 100:
            errors.append(f"{where}.percentile must be a number above 0 and at most 100")
    for key in ("asinh_a", "log_a"):
        if key in opts:
            v = opts[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
                errors.append(f"{where}.{key} must be a number greater than 0")
    if "invert" in opts and not isinstance(opts["invert"], bool):
        errors.append(f"{where}.invert must be true or false")
    if "hdu" in opts and opts["hdu"] is not None:
        h = opts["hdu"]
        if isinstance(h, bool) or not isinstance(h, (int, str)) or (isinstance(h, int) and h < 0):
            errors.append(f"{where}.hdu must be an HDU number (0 is the primary) or an EXTNAME")
    return errors


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _describe_hdus(hdul) -> str:
    parts = []
    for i, h in enumerate(hdul):
        name = h.name or f"HDU {i}"
        naxis = h.header.get("NAXIS", 0)
        if type(h).__name__ in ("BinTableHDU", "TableHDU"):
            kind = "table"
        elif naxis == 0:
            kind = "no data"
        else:
            dims = "x".join(str(h.header.get(f"NAXIS{n}", "?")) for n in range(1, naxis + 1))
            kind = f"{naxis}-D {dims}"
        parts.append(f"{i} {name} ({kind})")
    return "; ".join(parts) or "no HDUs"


def _is_image(h) -> bool:
    if not getattr(h, "is_image", False):
        return False
    naxis = int(h.header.get("NAXIS", 0) or 0)
    if naxis < 2:
        return False
    return all(int(h.header.get(f"NAXIS{n}", 0) or 0) > 0 for n in range(1, naxis + 1))


def _pick_hdu(hdul, wanted, label):
    if wanted is not None:
        try:
            h = hdul[wanted]
        except (KeyError, IndexError):
            raise FitsError(f"{label} has no HDU {wanted!r}. Its HDUs: {_describe_hdus(hdul)}.") from None
        if not _is_image(h):
            raise FitsError(f"HDU {wanted!r} of {label} is not a 2-D (or larger) image. "
                            f"Its HDUs: {_describe_hdus(hdul)}.")
        index = wanted if isinstance(wanted, int) else hdul.index_of(wanted)
        return index, h
    for i, h in enumerate(hdul):
        if _is_image(h):
            return i, h
    raise FitsError(f"{label} has no image HDU, so there is nothing to draw. "
                    f"Its HDUs: {_describe_hdus(hdul)}.")


def fits_cutout(path: str, *, center: Optional[Dict[str, Any]] = None,
                size: Any = None, hdu: Any = None,
                stretch: str = DEFAULTS["stretch"], interval: str = DEFAULTS["interval"],
                percentile: float = DEFAULTS["percentile"],
                asinh_a: float = DEFAULTS["asinh_a"], log_a: float = DEFAULTS["log_a"],
                invert: bool = False,
                max_file_bytes: int = MAX_FILE_BYTES,
                max_image_pixels: int = MAX_IMAGE_PIXELS,
                max_output_side: int = MAX_OUTPUT_SIDE) -> Dict[str, Any]:
    """Cut out, scale and encode one FITS image. See the module docstring."""
    label = os.path.basename(str(path))
    errors = scaling_errors({"stretch": stretch, "interval": interval, "percentile": percentile,
                             "asinh_a": asinh_a, "log_a": log_a, "invert": invert,
                             "hdu": hdu}, "fits")
    if errors:
        raise ValueError("; ".join(errors))
    center = parse_center(center)
    size_spec = parse_size(size)

    try:
        nbytes = os.path.getsize(path)
    except OSError as e:
        raise FitsError(f"{label} cannot be read: {e.strerror or e}") from None
    if nbytes > max_file_bytes:
        raise FitsError(f"{label} is {nbytes / 1e6:.1f} MB, over the {max_file_bytes / 1e6:.0f} MB "
                        f"limit for FITS files (max_file_mb). Cut it down first, or raise the limit.")

    np, fits, WCS, FITSFixedWarning = _astropy()
    try:
        hdul = fits.open(path, lazy_load_hdus=False)
    except Exception as e:     # astropy raises OSError, ValueError, TypeError...
        raise FitsError(f"{label} is not a readable FITS file ({e}).") from None
    try:
        return _cutout(np, WCS, FITSFixedWarning, hdul, label, center, size_spec, hdu,
                       stretch, interval, float(percentile), float(asinh_a), float(log_a),
                       bool(invert), max_image_pixels, max_output_side)
    finally:
        hdul.close()


def _cutout(np, WCS, FITSFixedWarning, hdul, label, center, size_spec, hdu,
            stretch, interval, percentile, asinh_a, log_a, invert,
            max_image_pixels, max_output_side):
    index, h = _pick_hdu(hdul, hdu, label)
    header = h.header
    naxis = int(header.get("NAXIS", 2))
    nx, ny = int(header["NAXIS1"]), int(header["NAXIS2"])
    notes: List[str] = []
    if naxis > 2:
        extra = [int(header.get(f"NAXIS{n}", 1)) for n in range(3, naxis + 1)]
        if any(n > 1 for n in extra):
            notes.append(f"HDU {index} is {naxis}-D; showing its first plane")

    # --- WCS -----------------------------------------------------------------
    celestial = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        warnings.simplefilter("ignore", UserWarning)
        try:
            w = WCS(header)
            if w.has_celestial and w.wcs.lng in (0, 1) and w.wcs.lat in (0, 1):
                celestial = w.celestial
            elif w.has_celestial:
                notes.append("the celestial axes are not the image's first two axes; "
                             "no sky coordinates")
        except Exception as e:     # malformed WCS keywords
            notes.append(f"the WCS could not be read ({e}); no sky coordinates")

    # --- region ----------------------------------------------------------------
    if center is not None and "ra" in center:
        if celestial is None:
            raise FitsError(f"{label} has no celestial WCS, so a position in ra/dec cannot be "
                            f"found on it. Give the position in pixels (x, y) instead.")
        cx, cy = _world_to_pixel(np, celestial, center["ra"], center["dec"])
        if not (math.isfinite(cx) and math.isfinite(cy)):
            raise FitsError(f"ra {center['ra']:.6f}, dec {center['dec']:.6f} does not project "
                            f"onto {label}.")
    elif center is not None:
        cx, cy = center["x"] - 1.0, center["y"] - 1.0      # FITS -> 0-based
    else:
        cx = cy = None

    step = 1
    if cx is None:
        if size_spec is not None:
            raise FitsError("a cutout size was given without a position (x, y or ra, dec)")
        if nx * ny > max_image_pixels:
            raise FitsError(f"{label} is {nx} x {ny} pixels, more than the {max_image_pixels:,} "
                            f"pixel limit for showing a whole image (max_image_pixels). Give a "
                            f"position and size to cut out the part to show.")
        x0, y0, x1, y1 = 0, 0, nx, ny
        long_side = max(nx, ny)
        if long_side > max_output_side:
            step = int(math.ceil(long_side / max_output_side))
            notes.append(f"shown at 1/{step} scale (block-averaged)")
    else:
        if size_spec is None:
            side_x = side_y = 64
        elif size_spec[0] == "px":
            side_x = side_y = int(round(size_spec[1]))
        else:
            if celestial is None:
                raise FitsError(f"{label} has no celestial WCS, so an angular size cannot be "
                                f"turned into pixels. Give the size in pixels.")
            sx, sy = _pixel_scales_deg(np, celestial)
            side_x = int(round(size_spec[1] / sx))
            side_y = int(round(size_spec[1] / sy))
        side_x, side_y = max(1, side_x), max(1, side_y)
        if max(side_x, side_y) > MAX_CUTOUT_SIDE:
            raise FitsError(f"a cutout {side_x} x {side_y} pixels is larger than the "
                            f"{MAX_CUTOUT_SIDE}-pixel limit; give a smaller size")
        # Pixel i covers [i - 0.5, i + 0.5); a window of side n centred on c
        # starts at round(c - (n - 1) / 2).
        x0 = int(math.floor(cx - (side_x - 1) / 2.0 + 0.5))
        y0 = int(math.floor(cy - (side_y - 1) / 2.0 + 0.5))
        x1, y1 = x0 + side_x, y0 + side_y
        if x1 <= 0 or y1 <= 0 or x0 >= nx or y0 >= ny:
            where = (f"ra/dec ({center['ra']:.5f}, {center['dec']:.5f}) falls at pixel "
                     f"({cx + 1:.1f}, {cy + 1:.1f}), which"
                     if "ra" in center else f"pixel ({cx + 1:.1f}, {cy + 1:.1f})")
            raise FitsError(f"The cutout position {where} is outside {label} "
                            f"({nx} x {ny} pixels).")
        if x0 < 0 or y0 < 0 or x1 > nx or y1 > ny:
            notes.append("the cutout runs off the edge of the image; the missing part is blank")

    data = _read_window(np, h, naxis, nx, ny, x0, y0, x1, y1)
    if step > 1:
        data = _block_mean(np, data, step)
    out_h, out_w = data.shape

    # --- scaling --------------------------------------------------------------
    finite = np.isfinite(data)
    limits = None
    gray = np.zeros(data.shape, dtype=np.uint8)
    if finite.any():
        values = data[finite]
        vmin, vmax = _interval_limits(np, values, interval, percentile)
        if not vmax > vmin:
            vmax = vmin + 1.0
        limits = [float(vmin), float(vmax)]
        scaled = np.clip((np.where(finite, data, vmin) - vmin) / (vmax - vmin), 0.0, 1.0)
        scaled = _stretch(np, scaled, stretch, asinh_a, log_a)
        if invert:
            scaled = 1.0 - scaled
        gray = np.round(scaled * 255.0).astype(np.uint8)
    else:
        notes.append("every pixel in this cutout is blank")

    rgba = np.empty((out_h, out_w, 4), dtype=np.uint8)
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = gray
    rgba[..., 3] = np.where(finite, 255, 0).astype(np.uint8)
    # Row 0 of a FITS array is the bottom of the picture.
    from potato.geo.png import encode_png
    png = encode_png(rgba[::-1])

    wcs_json = _wcs_json(np, celestial, x0, y0, step, out_w, out_h) if celestial is not None else None

    meta = {
        "file": label,
        "hdu": index,
        "hdu_name": h.name or None,
        "image_shape": [ny, nx],
        "region": {"x0": x0 + 1, "y0": y0 + 1, "x1": x1, "y1": y1, "step": step},
        "width": out_w,
        "height": out_h,
        "stretch": stretch,
        "interval": interval,
        "limits": limits,
        "notes": notes,
    }
    if interval == "percentile":
        meta["percentile"] = percentile
    for key, name in (("BUNIT", "bunit"), ("OBJECT", "object"), ("FILTER", "filter"),
                      ("DATE-OBS", "date_obs"), ("MJD-OBS", "mjd_obs"),
                      ("EXPTIME", "exptime"), ("TELESCOP", "telescope")):
        v = header.get(key)
        if v is None and index != 0 and len(hdul) and key in hdul[0].header:
            v = hdul[0].header.get(key)
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            meta[name] = v.strip() if isinstance(v, str) else v
    return {"png": png, "wcs": wcs_json, "meta": meta}


def _read_window(np, h, naxis, nx, ny, x0, y0, x1, y1):
    """The pixels in [x0, x1) x [y0, y1) as float64, NaN outside the image.
    Reads through ``section`` so only the rows needed come off disk."""
    out = np.full((y1 - y0, x1 - x0), np.nan, dtype=np.float64)
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(nx, x1), min(ny, y1)
    if sx1 <= sx0 or sy1 <= sy0:
        return out
    lead = (0,) * (naxis - 2)
    try:
        block = h.section[lead + (slice(sy0, sy1), slice(sx0, sx1))]
    except Exception:          # pragma: no cover - very old astropy without section
        block = h.data[lead + (slice(sy0, sy1), slice(sx0, sx1))]
    block = np.asarray(block, dtype=np.float64)
    # BLANK for integer images: astropy applies BSCALE/BZERO but leaves BLANK.
    blank = h.header.get("BLANK")
    if blank is not None and int(h.header.get("BITPIX", -32)) > 0:
        bscale = float(h.header.get("BSCALE", 1.0))
        bzero = float(h.header.get("BZERO", 0.0))
        block = np.where(block == blank * bscale + bzero, np.nan, block)
    out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = block
    return out


def _block_mean(np, data, step):
    h, w = data.shape
    ph, pw = (-h) % step, (-w) % step
    if ph or pw:
        data = np.pad(data, ((0, ph), (0, pw)), constant_values=np.nan)
    hh, ww = data.shape
    blocks = data.reshape(hh // step, step, ww // step, step)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # all-NaN blocks
        return np.nanmean(blocks, axis=(1, 3))


def _interval_limits(np, values, interval, percentile):
    from astropy.visualization import MinMaxInterval, PercentileInterval, ZScaleInterval
    if interval == "minmax":
        iv = MinMaxInterval()
    elif interval == "percentile":
        iv = PercentileInterval(percentile)
    else:
        iv = ZScaleInterval()
    vmin, vmax = iv.get_limits(values)
    return float(vmin), float(vmax)


def _stretch(np, scaled, name, asinh_a, log_a):
    from astropy.visualization import AsinhStretch, LinearStretch, LogStretch, SqrtStretch
    if name == "sqrt":
        s = SqrtStretch()
    elif name == "log":
        s = LogStretch(a=log_a)
    elif name == "asinh":
        s = AsinhStretch(a=asinh_a)
    else:
        s = LinearStretch()
    return np.clip(np.asarray(s(scaled, clip=True), dtype=np.float64), 0.0, 1.0)


# ---------------------------------------------------------------------------
# WCS
# ---------------------------------------------------------------------------

def _world_to_pixel(np, celestial, ra, dec):
    """0-based pixel position of an ICRS ra/dec, transformed into the image's
    own frame (FK5, galactic...) when it is not ICRS."""
    try:
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        from astropy.wcs.utils import skycoord_to_pixel
        x, y = skycoord_to_pixel(SkyCoord(ra * u.deg, dec * u.deg, frame="icrs"), celestial, origin=0)
        return float(x), float(y)
    except Exception:
        x, y = celestial.all_world2pix([[ra, dec]], 0)[0]
        return float(x), float(y)


def _pixel_scales_deg(np, celestial):
    from astropy.wcs.utils import proj_plane_pixel_scales
    sx, sy = proj_plane_pixel_scales(celestial)
    return abs(float(sx)), abs(float(sy))


def _frame_name(celestial) -> str:
    try:
        from astropy.wcs.utils import wcs_to_celestial_frame
        return wcs_to_celestial_frame(celestial).name
    except Exception:
        return "unknown"


def _unit_vectors(np, lon_deg, lat_deg):
    lon, lat = np.radians(lon_deg), np.radians(lat_deg)
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)


def _wcs_json(np, celestial, x0, y0, step, out_w, out_h) -> Dict[str, Any]:
    """Coordinates for the browser readout.

    ``grid`` samples the cutout at ``nx`` x ``ny`` points from its left/bottom
    edge to its right/top edge (output pixel edges, not centres) and stores the
    unit vector of each sky position. Interpolating unit vectors, then
    normalising, has no trouble at RA 0/360 or at the poles, which
    interpolating RA and Dec would.

    Screen position (u, v) in [0, 1] from the top-left corner of the drawn
    image maps to FITS pixel ``x = x0 + u * width * step + 0.5`` and
    ``y = y0 + (1 - v) * height * step + 0.5`` (``x0``, ``y0`` 0-based).
    """
    gx = max(2, min(65, int(math.ceil(out_w / GRID_CELL)) + 1))
    gy = max(2, min(65, int(math.ceil(out_h / GRID_CELL)) + 1))
    us = np.linspace(0.0, out_w, gx)
    vs = np.linspace(0.0, out_h, gy)
    px = x0 + us * step - 0.5
    py = y0 + vs * step - 0.5
    PX, PY = np.meshgrid(px, py)          # rows: bottom -> top
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lon, lat = celestial.all_pix2world(PX.ravel(), PY.ravel(), 0)
    xyz = _unit_vectors(np, np.asarray(lon), np.asarray(lat))
    ok = bool(np.all(np.isfinite(xyz)))

    # Centre, scale and the north/east directions on screen (x right, y down).
    ccx = x0 + out_w * step / 2.0 - 0.5
    ccy = y0 + out_h * step / 2.0 - 0.5
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clon, clat = (float(v) for v in celestial.all_pix2world([[ccx, ccy]], 0)[0])
    sx, sy = _pixel_scales_deg(np, celestial)
    north = east = None
    try:
        d = min(sx, sy) * 5.0
        nx_, ny_ = celestial.all_world2pix([[clon, min(89.9999, clat + d)]], 0)[0]
        cosd = max(1e-6, math.cos(math.radians(clat)))
        ex_, ey_ = celestial.all_world2pix([[clon + d / cosd, clat]], 0)[0]
        north = _screen_dir(nx_ - ccx, ny_ - ccy)
        east = _screen_dir(ex_ - ccx, ey_ - ccy)
    except Exception:
        pass

    ctype = [str(c) for c in celestial.wcs.ctype]
    lon_name, lat_name = ("RA", "Dec")
    if ctype and ctype[0].upper().startswith("GLON"):
        lon_name, lat_name = ("l", "b")
    elif ctype and ctype[0].upper().startswith("ELON"):
        lon_name, lat_name = ("λ", "β")

    # The cutout's own linear WCS: CRPIX moved to the cutout's pixel grid and
    # the CD matrix scaled by the block size. Distortion terms (SIP) are not
    # carried over here; the grid above includes them.
    crpix = [(float(celestial.wcs.crpix[0]) - 0.5 - x0) / step + 0.5,
             (float(celestial.wcs.crpix[1]) - 0.5 - y0) / step + 0.5]
    try:
        cd = (np.asarray(celestial.wcs.cd) if celestial.wcs.has_cd()
              else np.diag(celestial.wcs.cdelt) @ celestial.wcs.get_pc()) * step
        cd = [[float(v) for v in row] for row in cd]
    except Exception:
        cd = None
    return {
        "frame": _frame_name(celestial),
        "axes": [lon_name, lat_name],
        "sexagesimal": lon_name == "RA",
        "ctype": ctype,
        "crval": [float(v) for v in celestial.wcs.crval],
        "crpix": crpix,
        "cd": cd,
        "pixel_scale_arcsec": [sx * 3600.0, sy * 3600.0],
        "center": [clon % 360.0, clat],
        "north": north,
        "east": east,
        "origin": {"x0": x0, "y0": y0, "step": step},
        "grid": {"nx": gx, "ny": gy, "xyz": [round(float(v), 10) for v in xyz.ravel()]} if ok else None,
    }


def _screen_dir(dx, dy):
    """A pixel-space direction (FITS y up) as a unit vector on screen (y down)."""
    n = math.hypot(dx, dy)
    if not n or not math.isfinite(n):
        return None
    return [round(dx / n, 6), round(-dy / n, 6)]
