"""Spectra for the ``spectrum`` display: loading, downsampling, peaks, integrals.

A :class:`Spectrum` is one x/y trace with its units and kind (NMR, IR, MS, ...).
It is read on the server from a JCAMP-DX file (:mod:`.converters.jcamp`), an
mzML run (:mod:`.converters.mzml`, needs the ``spectra`` extra), a two-column
CSV (:mod:`.converters.spectrum_csv`), or arrays written inline in the item.

The browser never parses a spectrum file. It gets a downsampled copy for
drawing (:func:`downsample`), asks ``/api/spectrum/range`` for full-resolution
points when the annotator zooms in, and asks the same route for the integral
of a dragged region, which is computed here on every point of the original.

Peak suggestions come from :func:`detect_peaks` (``scipy.signal.find_peaks``
with a prominence threshold; scipy is a core dependency) or from the peak
table a JCAMP-DX file carries.
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Spectrum kinds the display knows conventions for.
KINDS = ("nmr", "ir", "raman", "uv", "ms", "other")

#: Hard ceilings, whatever a config asks for.
MAX_FILE_MB_CEILING = 500
MAX_POINTS_CEILING = 5_000_000

DEFAULT_MAX_FILE_MB = 50
DEFAULT_MAX_POINTS = 2_000_000


class SpectrumError(ValueError):
    """The file cannot be read as a spectrum (format error, too large, ...)."""


@dataclass
class Spectrum:
    """One spectrum, x ascending.

    ``x_units`` / ``y_units`` are the file's spellings upper-cased (``PPM``,
    ``1/CM``, ``TRANSMITTANCE``); :func:`axis_title` turns them into labels.
    ``sticks`` marks a peak list or centroided MS scan drawn as vertical lines.
    ``peaks`` is the file's own peak table, ``[(x, y), ...]``.
    """
    x: Any
    y: Any
    x_units: str = ""
    y_units: str = ""
    kind: str = "other"
    title: str = ""
    sticks: bool = False
    peaks: List[Tuple[float, float]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        import numpy as np
        x = np.asarray(self.x, dtype=float)
        y = np.asarray(self.y, dtype=float)
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
            raise SpectrumError(f"x and y must be lists of the same length "
                                f"(got {x.size} and {y.size} values)")
        keep = np.isfinite(x) & np.isfinite(y)
        x, y = x[keep], y[keep]
        if len(x) == 0:
            raise SpectrumError("the spectrum has no data points")
        order = np.argsort(x, kind="stable")
        if not np.all(order == np.arange(len(x))):
            x, y = x[order], y[order]
        self.x, self.y = x, y
        self.kind = self.kind if self.kind in KINDS else infer_kind("", self.x_units)

    def __len__(self):
        return len(self.x)


# ---------------------------------------------------------------------------
# Kinds, units, conventions
# ---------------------------------------------------------------------------

def infer_kind(data_type: str, x_units: str) -> str:
    """Spectrum kind from a JCAMP ``DATA TYPE`` and/or the x units."""
    t = (data_type or "").upper()
    if "NMR" in t:
        return "nmr"
    if "RAMAN" in t:
        return "raman"
    if "INFRARED" in t or t.startswith("IR") or " IR " in f" {t} " or "FTIR" in t:
        return "ir"
    if "MASS" in t:
        return "ms"
    if "UV" in t or "VIS" in t or "ULTRAVIOLET" in t:
        return "uv"
    u = (x_units or "").upper().replace(" ", "")
    if u == "PPM":
        return "nmr"
    if u in ("1/CM", "CM-1", "CM^-1"):
        return "ir"
    if u in ("M/Z", "MZ"):
        return "ms"
    if u in ("NANOMETERS", "NM"):
        return "uv"
    return "other"


_X_TITLES = {
    "PPM": "Chemical shift (ppm)",
    "HZ": "Frequency (Hz)",
    "1/CM": "Wavenumber (cm⁻¹)",
    "CM-1": "Wavenumber (cm⁻¹)",
    "M/Z": "m/z",
    "MZ": "m/z",
    "NANOMETERS": "Wavelength (nm)",
    "NM": "Wavelength (nm)",
    "MICROMETERS": "Wavelength (µm)",
    "UM": "Wavelength (µm)",
    "SECONDS": "Time (s)",
}
_Y_TITLES = {
    "TRANSMITTANCE": "Transmittance",
    "REFLECTANCE": "Reflectance",
    "ABSORBANCE": "Absorbance",
    "KUBELKA-MUNK": "Kubelka-Munk",
    "ARBITRARYUNITS": "Intensity (arb. units)",
    "RELATIVEABUNDANCE": "Relative abundance",
    "COUNTS": "Counts",
    "INTENSITY": "Intensity",
}


def axis_title(units: str, axis: str, kind: str = "other") -> str:
    """A readable axis title for a units string (``1/CM`` -> ``Wavenumber (cm⁻¹)``)."""
    u = (units or "").strip()
    key = u.upper().replace(" ", "")
    table = _X_TITLES if axis == "x" else _Y_TITLES
    if key in table:
        return table[key]
    if not u:
        if axis == "x":
            return {"nmr": "Chemical shift", "ir": "Wavenumber", "ms": "m/z",
                    "uv": "Wavelength", "raman": "Raman shift"}.get(kind, "x")
        return "Intensity"
    return u


def reversed_by_convention(kind: str, x_units: str) -> bool:
    """NMR shifts and IR wavenumbers are drawn high-to-low, left to right."""
    u = (x_units or "").upper().replace(" ", "")
    if kind == "nmr":
        return u in ("PPM", "HZ", "")
    if kind == "ir":
        return u in ("1/CM", "CM-1", "")
    return False


def peaks_point_down(y_units: str) -> bool:
    """Transmittance and reflectance spectra have their bands as minima."""
    u = (y_units or "").upper()
    return "TRANSMITTANCE" in u or "REFLECTANCE" in u


def decimals_for(span: float) -> int:
    """Decimal places for x values over ``span`` (10 ppm -> 3, 3600 cm⁻¹ -> 1)."""
    if not span or not math.isfinite(span) or span <= 0:
        return 3
    return int(min(4, max(0, 4 - math.floor(math.log10(span)))))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

_CACHE: "OrderedDict[tuple, Spectrum]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 16


def check_size(path: str, max_file_mb: float) -> None:
    limit = min(float(max_file_mb or DEFAULT_MAX_FILE_MB), MAX_FILE_MB_CEILING)
    size = os.path.getsize(path)
    if size > limit * 1024 * 1024:
        raise SpectrumError(
            f"{os.path.basename(path)} is {size / 1048576:.1f} MB, over the "
            f"{limit:g} MB limit for spectrum files (max_file_mb)")


def read_file(path: str, selector: Optional[Dict[str, Any]] = None,
              max_file_mb: float = DEFAULT_MAX_FILE_MB,
              max_points: int = DEFAULT_MAX_POINTS) -> Spectrum:
    """Read ``path`` (already resolved and checked by the caller) as a spectrum.

    ``selector`` picks a part of a multi-spectrum file: ``block`` (JCAMP-DX
    compound file), ``index`` or ``scan`` (mzML). Results are cached by path,
    modification time and selector.
    """
    selector = {k: v for k, v in (selector or {}).items() if v is not None}
    check_size(path, max_file_mb)
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_mtime_ns, st.st_size,
           tuple(sorted(selector.items())), int(max_points))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    spectrum = _read_uncached(path, selector, max_points)
    with _CACHE_LOCK:
        _CACHE[key] = spectrum
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return spectrum


def _read_uncached(path: str, selector: Dict[str, Any], max_points: int) -> Spectrum:
    from potato.science.converters import ConverterUnavailable, converter_for
    name = os.path.basename(path).lower()
    limit = min(int(max_points or DEFAULT_MAX_POINTS), MAX_POINTS_CEILING)
    if name.endswith((".csv", ".tsv", ".txt", ".xy")):
        # Not in the shared converter table: ".csv" is too generic to claim
        # for spectra across every display.
        from potato.science.converters.spectrum_csv import read_spectrum_csv
        return read_spectrum_csv(path, max_points=limit)
    try:
        reader = converter_for(path)
    except ConverterUnavailable as e:
        raise SpectrumError(str(e)) from e
    if reader is None or getattr(reader, "__module__", "") not in _SPECTRUM_READERS:
        raise SpectrumError(
            f"{os.path.basename(path)}: not a spectrum format Potato reads. Use "
            f"JCAMP-DX (.jdx, .dx), mzML (.mzML) or a two-column CSV (x,y).")
    try:
        return reader(path, max_points=limit, **selector)
    except ConverterUnavailable as e:
        raise SpectrumError(str(e)) from e


_SPECTRUM_READERS = {
    "potato.science.converters.jcamp",
    "potato.science.converters.mzml",
}


def from_inline(value: Dict[str, Any], max_points: int = DEFAULT_MAX_POINTS) -> Spectrum:
    """A spectrum written in the item: ``{x: [...], y: [...], x_units, y_units, kind}``."""
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, list) or not isinstance(y, list):
        raise SpectrumError("an inline spectrum needs x and y lists")
    if len(x) > min(int(max_points), MAX_POINTS_CEILING):
        raise SpectrumError(f"the inline spectrum has {len(x)} points, over the "
                            f"{max_points} limit")
    try:
        return Spectrum(x=x, y=y, x_units=str(value.get("x_units") or "").upper(),
                        y_units=str(value.get("y_units") or "").upper(),
                        kind=str(value.get("kind") or "") or infer_kind("", str(value.get("x_units") or "")),
                        title=str(value.get("title") or ""),
                        sticks=bool(value.get("sticks", False)))
    except (TypeError, ValueError) as e:
        raise SpectrumError(f"the inline spectrum is not numeric: {e}") from e


# ---------------------------------------------------------------------------
# Downsampling and ranges
# ---------------------------------------------------------------------------

def downsample(x, y, max_points: int, sticks: bool = False):
    """At most ``max_points`` points that keep every peak's height.

    A line is cut into ``max_points // 2`` buckets and each bucket keeps its
    lowest and highest point, in x order (so a narrow NMR line is still drawn
    at full height). Sticks keep the ``max_points`` tallest.
    """
    import numpy as np
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n <= max_points:
        return x, y
    if sticks:
        keep = np.sort(np.argsort(np.abs(y))[-max_points:])
        return x[keep], y[keep]
    buckets = max(1, max_points // 2)
    edges = np.linspace(0, n, buckets + 1).astype(int)
    idx = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        lo, hi = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        idx.extend(sorted({lo, hi}))
    idx = np.asarray(idx, dtype=int)
    return x[idx], y[idx]


def window(spectrum: Spectrum, x0: float, x1: float):
    """Indices ``(a, b)`` of the points with ``x0 <= x <= x1``."""
    import numpy as np
    lo, hi = min(x0, x1), max(x0, x1)
    a = int(np.searchsorted(spectrum.x, lo, side="left"))
    b = int(np.searchsorted(spectrum.x, hi, side="right"))
    return a, b


def integrate(spectrum: Spectrum, x0: float, x1: float) -> float:
    """Trapezoid integral of y over ``[x0, x1]`` on every original point.

    The ends are interpolated, so the result does not jump as the region edge
    crosses a sample. Always integrated with x ascending: a region dragged
    right-to-left on a reversed ppm axis has the same, positive area.
    """
    import numpy as np
    lo, hi = min(x0, x1), max(x0, x1)
    xs, ys = spectrum.x, spectrum.y
    if hi <= xs[0] or lo >= xs[-1] or hi == lo:
        return 0.0
    lo, hi = max(lo, float(xs[0])), min(hi, float(xs[-1]))
    a, b = window(spectrum, lo, hi)
    inner_x, inner_y = xs[a:b], ys[a:b]
    px = np.concatenate(([lo], inner_x, [hi]))
    py = np.concatenate(([np.interp(lo, xs, ys)], inner_y, [np.interp(hi, xs, ys)]))
    trapz = getattr(np, "trapezoid", None) or np.trapz
    return float(trapz(py, px))


# ---------------------------------------------------------------------------
# Peak suggestions
# ---------------------------------------------------------------------------

def detect_peaks(spectrum: Spectrum, prominence: float = 0.05, max_peaks: int = 40,
                 min_distance: Optional[float] = None, direction: str = "max"
                 ) -> List[Dict[str, float]]:
    """Suggested peaks: ``[{x, y, width, prominence}, ...]`` sorted by x.

    ``prominence`` is a fraction of the spectrum's y range (0.05 = 5%).
    ``min_distance`` is in x units. ``direction`` "min" finds bands that point
    down (transmittance). ``width`` is the full width at half prominence, in x
    units. Sticks (a peak list) are suggested by height instead.
    """
    import numpy as np
    xs, ys = spectrum.x, spectrum.y
    if len(xs) < 3:
        return []
    sign = -1.0 if direction == "min" else 1.0
    if spectrum.sticks:
        signal = sign * ys
        top = signal.max()
        if top <= 0:
            return []
        keep = np.where(signal >= prominence * top)[0]
        keep = keep[np.argsort(signal[keep])[::-1][:max_peaks]]
        return [{"x": float(xs[i]), "y": float(ys[i])} for i in sorted(keep)]

    from scipy.signal import find_peaks, peak_widths
    signal = sign * ys
    span = float(signal.max() - signal.min())
    if span <= 0:
        return []
    distance = None
    if min_distance:
        step = float(np.median(np.diff(xs))) or 1.0
        distance = max(1, int(round(float(min_distance) / step)))
    idx, props = find_peaks(signal, prominence=prominence * span, distance=distance)
    if len(idx) == 0:
        return []
    order = np.argsort(props["prominences"])[::-1][:max_peaks]
    idx, prom = idx[order], props["prominences"][order]
    widths, _h, left, right = peak_widths(signal, idx, rel_height=0.5)
    positions = np.arange(len(xs), dtype=float)
    left_x = np.interp(left, positions, xs)
    right_x = np.interp(right, positions, xs)
    out = [{"x": float(xs[i]), "y": float(ys[i]),
            "width": float(abs(rx - lx)), "prominence": float(p)}
           for i, p, lx, rx in zip(idx, prom, left_x, right_x)]
    return sorted(out, key=lambda p: p["x"])


def file_peaks(spectrum: Spectrum, max_peaks: int = 40) -> List[Dict[str, float]]:
    """The file's own peak table as suggestions (tallest ``max_peaks``)."""
    peaks = sorted(spectrum.peaks, key=lambda p: abs(p[1]), reverse=True)[:max_peaks]
    return sorted(({"x": float(px), "y": float(py)} for px, py in peaks), key=lambda p: p["x"])


def round_sig(values: Sequence[float], digits: int = 7) -> List[float]:
    """Floats rounded to ``digits`` significant digits, for compact JSON."""
    out = []
    for v in values:
        v = float(v)
        out.append(float(f"{v:.{digits}g}") if math.isfinite(v) else 0.0)
    return out
