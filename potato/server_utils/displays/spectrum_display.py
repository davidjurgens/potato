"""
Spectrum display (``type: spectrum``): NMR, IR, Raman, UV-Vis and mass spectra.

The item field names a spectrum file in the media directory, or holds the
spectrum inline::

    "spectrum": "spectra/ethyl_acetate.jdx"
    "spectrum": {"file": "runs/sample1.mzML", "scan": 1043}
    "spectrum": {"file": "nmr/e1.jdx", "peaks": [4.12, 2.04, 1.26]}
    "spectrum": {"x": [...], "y": [...], "x_units": "PPM", "kind": "nmr"}

Files are parsed on the server (:mod:`potato.science.spectra`): JCAMP-DX
(``.jdx``, ``.dx``), mzML (``.mzML``, with the ``spectra`` extra) and
two-column CSV. The browser gets at most ``max_points`` points to draw;
zooming in fetches full-resolution points for the visible range from
``/api/spectrum/range``, which also integrates dragged regions on the
original data.

Drawn with Plotly 2.27.0 (MIT), committed at
``potato/static/vendor/plotly-2.27.0.min.js`` and loaded only on pages with a
spectrum. It draws SVG, so no WebGL is needed.

Selection (``window.potatoViewers[field]``), bound by a ``peak_picking``
scheme or a ``viewer_selection`` scheme::

    {"viewer": "spectrum",
     "items": [{"kind": "peak", "x": 2.04, "y": 3010.0, "source": "auto",
                "width": 0.003, "fields": {"assignment": "CH3CO"}},
               {"kind": "peak", "x": 7.26, "y": 310.0, "source": "manual"},
               {"kind": "region", "from": 1.19, "to": 1.33, "integral": 37.9}],
     "rejected": [0.92]}

``source`` is ``auto`` for an accepted suggestion and ``manual`` for a peak
the annotator added; ``rejected`` lists the x of suggestions turned down.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .viewer_display import (ViewerAsset, ViewerDataError, ViewerDisplay,
                             ViewerEngine, resolve_source)

logger = logging.getLogger(__name__)

SPECTRUM_TYPES = ("auto", "nmr", "ir", "raman", "uv", "ms", "other")
PREPICK_METHODS = ("auto", "detect", "file", "item")
PREPICK_KEYS = {"method", "prominence", "max_peaks", "min_distance"}
PREPICK_DEFAULTS = {"method": "auto", "prominence": 0.05, "max_peaks": 40, "min_distance": None}
ITEM_KEYS = {"file", "path", "scan", "index", "block", "peaks", "kind",
             "x", "y", "x_units", "y_units", "title", "sticks"}
MAX_DISPLAY_POINTS = 100_000


def prepick_settings(value: Any) -> Optional[Dict[str, Any]]:
    """The prepick option as settings, or None when pre-picking is off."""
    if value is None or value is False:
        return None
    settings = dict(PREPICK_DEFAULTS)
    if isinstance(value, dict):
        settings.update({k: v for k, v in value.items() if k in PREPICK_KEYS})
    return settings


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_spectrum(data: Any, options: Dict[str, Any], config: Optional[Dict[str, Any]] = None):
    """``(spectrum, item_peaks, source_name)`` for one item's field value.

    Raises ViewerDataError with a message an annotator can act on.
    """
    from potato.science.spectra import SpectrumError, from_inline, read_file
    item_peaks = None
    if isinstance(data, dict):
        extra = sorted(set(data) - ITEM_KEYS)
        if extra:
            raise ViewerDataError(f"The spectrum value has unknown key(s) {', '.join(extra)}; "
                                  f"it takes {', '.join(sorted(ITEM_KEYS))}.")
        item_peaks = data.get("peaks")
        if "x" in data or "y" in data:
            try:
                return from_inline(data), item_peaks, "inline"
            except SpectrumError as e:
                raise ViewerDataError(f"Cannot read this item's spectrum: {e}.")
        ref = data.get("file") or data.get("path")
        selector = {k: data.get(k, options.get(k)) for k in ("scan", "index", "block")}
    elif isinstance(data, str):
        ref = data
        selector = {k: options.get(k) for k in ("scan", "index", "block")}
    else:
        raise ViewerDataError("This item has no spectrum (the field is empty or not a file name).")
    if str(ref or "").strip().startswith(("http://", "https://", "//")):
        raise ViewerDataError(
            "The spectrum for this item is a URL. Spectra are read on the server and "
            "Potato does not download them: copy the file into the media directory.")
    _url, path = resolve_source(ref, False, "spectrum file", config=config)
    if path is None or not os.path.isfile(path):
        raise ViewerDataError(f"The spectrum file '{ref}' does not exist in the media directory.")
    try:
        spectrum = read_file(path, selector, max_file_mb=options.get("max_file_mb") or 50)
    except SpectrumError as e:
        raise ViewerDataError(f"Cannot read the spectrum file '{ref}': {e}.")
    except (OSError, UnicodeError) as e:
        raise ViewerDataError(f"Cannot open the spectrum file '{ref}': {e}.")
    return spectrum, item_peaks, os.path.basename(path)


def resolved_conventions(spectrum, options: Dict[str, Any]) -> Dict[str, Any]:
    """Kind, axis direction, peak direction, drawing mode and integration."""
    from potato.science.spectra import (axis_title, peaks_point_down,
                                        reversed_by_convention)
    kind = options.get("spectrum_type") or "auto"
    kind = spectrum.kind if kind == "auto" else kind
    rev = options.get("x_reversed", "auto")
    reversed_ = reversed_by_convention(kind, spectrum.x_units) if rev == "auto" else bool(rev)
    direction = options.get("peak_direction") or "auto"
    if direction == "auto":
        direction = "min" if peaks_point_down(spectrum.y_units) else "max"
    mode = options.get("mode") or "auto"
    sticks = spectrum.sticks if mode == "auto" else mode == "sticks"
    integrate = options.get("integrate", "auto")
    integrate = (kind == "nmr" and not sticks) if integrate == "auto" else bool(integrate)
    return {
        # Not "kind": the viewer base sets that to the display type.
        "spectrumType": kind, "reversed": reversed_, "direction": direction, "sticks": sticks,
        "integrate": integrate,
        "xLabel": options.get("x_label") or axis_title(spectrum.x_units, "x", kind),
        "yLabel": options.get("y_label") or axis_title(spectrum.y_units, "y", kind),
    }


def suggestions_for(spectrum, item_peaks, options: Dict[str, Any], direction: str
                    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Pre-picked peaks and where they came from (detect, file, item)."""
    import numpy as np
    from potato.science.spectra import detect_peaks, file_peaks
    settings = prepick_settings(options.get("prepick"))
    if settings is None:
        return [], None
    method = settings["method"]
    if method == "auto":
        method = "item" if item_peaks else ("file" if spectrum.peaks else "detect")
    max_peaks = int(settings["max_peaks"])
    if method == "item":
        out = []
        for p in (item_peaks or [])[:max_peaks]:
            if _is_number(p):
                x, label = float(p), None
            elif isinstance(p, dict) and _is_number(p.get("x")):
                x, label = float(p["x"]), p.get("label")
            else:
                continue
            y = p.get("y") if isinstance(p, dict) and _is_number(p.get("y")) else \
                float(np.interp(x, spectrum.x, spectrum.y))
            entry = {"x": x, "y": float(y)}
            if isinstance(label, str) and label:
                entry["label"] = label
            out.append(entry)
        return sorted(out, key=lambda e: e["x"]), "item"
    if method == "file":
        return file_peaks(spectrum, max_peaks), "file"
    return detect_peaks(spectrum, prominence=float(settings["prominence"]), max_peaks=max_peaks,
                        min_distance=settings.get("min_distance"), direction=direction), "detect"


class SpectrumDisplay(ViewerDisplay):
    name = "spectrum"
    description = "Spectrum (NMR, IR, MS) with zoom, peak picking and integration"
    required_fields = ["key"]
    optional_fields = {
        **ViewerDisplay.COMMON_OPTIONS,
        "engine": "plotly",
        "height": 380,
        "spectrum_type": "auto",
        "x_reversed": "auto",
        "x_label": None,
        "y_label": None,
        "mode": "auto",
        "peak_direction": "auto",
        "integrate": "auto",
        # None (off), true, or a mapping; None so the bool-default type check
        # does not flag the mapping form.
        "prepick": None,
        "snap": True,
        "max_points": 4000,
        "max_file_mb": 50,
        "scan": None,
        "index": None,
        "block": None,
    }
    default_engine = "plotly"
    engines = {
        "plotly": ViewerEngine(
            name="plotly", label="Plotly", webgl=None, licence="MIT",
            assets=(ViewerAsset("script", "vendor/plotly-2.27.0.min.js"),)),
    }
    selection_context = ("rejected",)

    # -- options --------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        errors = []

        def choice(key, allowed):
            if options.get(key) not in allowed:
                shown = ", ".join("true" if a is True else "false" if a is False else str(a)
                                  for a in allowed)
                errors.append(f"{path}.{key} must be one of: {shown}")

        choice("spectrum_type", SPECTRUM_TYPES)
        choice("x_reversed", ("auto", True, False))
        choice("mode", ("auto", "line", "sticks"))
        choice("peak_direction", ("auto", "max", "min"))
        choice("integrate", ("auto", True, False))
        if not isinstance(options.get("snap"), bool):
            errors.append(f"{path}.snap must be true or false")
        if options.get("allow_remote"):
            errors.append(f"{path}.allow_remote is not supported by the spectrum display: "
                          f"spectra are parsed on the server and never downloaded. Copy "
                          f"the files into the media directory.")
        for key in ("x_label", "y_label"):
            if options.get(key) is not None and not isinstance(options.get(key), str):
                errors.append(f"{path}.{key} must be text")
        mp = options.get("max_points")
        if not _is_int(mp) or not 200 <= mp <= MAX_DISPLAY_POINTS:
            errors.append(f"{path}.max_points must be a whole number from 200 to "
                          f"{MAX_DISPLAY_POINTS} (points sent to the browser)")
        mb = options.get("max_file_mb")
        if not _is_number(mb) or not 0 < mb <= 500:
            errors.append(f"{path}.max_file_mb must be a number of megabytes above 0 and at most 500")
        for key, low in (("scan", 1), ("index", 0), ("block", 0)):
            v = options.get(key)
            if v is not None and (not _is_int(v) or v < low):
                errors.append(f"{path}.{key} must be a whole number ({low} or more)")
        if options.get("scan") is not None and options.get("index") is not None:
            errors.append(f"{path}: give scan or index, not both")
        pp = options.get("prepick")
        if pp is not None and not isinstance(pp, (bool, dict)):
            errors.append(f"{path}.prepick must be true, false or a mapping "
                          f"({', '.join(sorted(PREPICK_KEYS))})")
        elif isinstance(pp, dict):
            extra = sorted(set(pp) - PREPICK_KEYS)
            if extra:
                errors.append(f"{path}.prepick has unknown key(s) {', '.join(extra)}; "
                              f"accepted: {', '.join(sorted(PREPICK_KEYS))}")
            if pp.get("method", "auto") not in PREPICK_METHODS:
                errors.append(f"{path}.prepick.method must be one of: {', '.join(PREPICK_METHODS)}")
            prom = pp.get("prominence", 0.05)
            if not _is_number(prom) or not 0 < prom < 1:
                errors.append(f"{path}.prepick.prominence must be a fraction of the y range "
                              f"above 0 and below 1 (0.05 = 5%)")
            mx = pp.get("max_peaks", 40)
            if not _is_int(mx) or not 1 <= mx <= 500:
                errors.append(f"{path}.prepick.max_peaks must be a whole number from 1 to 500")
            md = pp.get("min_distance")
            if md is not None and (not _is_number(md) or md < 0):
                errors.append(f"{path}.prepick.min_distance must be a distance in x units (0 or more)")
        return errors

    # -- rendering ------------------------------------------------------------------

    def client_config(self, field_config, data, options):
        from potato.science.spectra import decimals_for, downsample, round_sig
        spectrum, item_peaks, source = load_spectrum(data, options)
        conv = resolved_conventions(spectrum, options)
        try:
            suggestions, method = suggestions_for(spectrum, item_peaks, options, conv["direction"])
        except Exception as e:      # a detector failure must not hide the spectrum
            logger.warning("peak suggestions failed for %s: %s", source, e)
            suggestions, method = [], None
        xs, ys = downsample(spectrum.x, spectrum.y, int(options.get("max_points") or 4000),
                            sticks=conv["sticks"])
        span = float(spectrum.x[-1] - spectrum.x[0])
        for s in suggestions:
            for k in ("x", "y", "width", "prominence"):
                if k in s:
                    s[k] = round_sig([s[k]])[0]
        return {
            **conv,
            "x": round_sig(xs),
            "y": round_sig(ys),
            "xRange": round_sig([spectrum.x[0], spectrum.x[-1]]),
            "totalPoints": len(spectrum),
            "shownPoints": len(xs),
            "decimals": decimals_for(span),
            "xUnits": spectrum.x_units,
            "yUnits": spectrum.y_units,
            "title": spectrum.title,
            "source": source,
            "suggestions": suggestions,
            "suggestionMethod": method,
            "snap": bool(options.get("snap", True)),
            "rangeUrl": "/api/spectrum/range",
        }

    # -- selection shape -------------------------------------------------------------

    def validate_item(self, item, where):
        errors = []
        kind = item.get("kind")
        if kind == "peak":
            allowed = {"kind", "x", "y", "source", "width", "label", "fields"}
            if not _is_number(item.get("x")):
                errors.append(f"{where}.x must be a number")
            if "y" in item and not _is_number(item["y"]):
                errors.append(f"{where}.y must be a number")
            if "width" in item and (not _is_number(item["width"]) or item["width"] < 0):
                errors.append(f"{where}.width must be a number (0 or more)")
            if item.get("source") not in ("auto", "manual"):
                errors.append(f"{where}.source must be auto or manual")
        elif kind == "region":
            allowed = {"kind", "from", "to", "integral", "label", "fields"}
            a, b = item.get("from"), item.get("to")
            if not _is_number(a) or not _is_number(b):
                errors.append(f"{where}.from and .to must be numbers")
            elif b <= a:
                errors.append(f"{where}.to must be above .from")
            if "integral" in item and not _is_number(item["integral"]):
                errors.append(f"{where}.integral must be a number")
        else:
            return [f"{where}.kind must be peak or region"]
        extra = sorted(set(item) - allowed)
        if extra:
            errors.append(f"{where} has unexpected key(s) {', '.join(extra)}")
        fields = item.get("fields")
        if fields is not None:
            if not isinstance(fields, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
                errors.append(f"{where}.fields must map field names to text")
        return errors

    def validate_context(self, selection):
        rejected = selection.get("rejected")
        if rejected is None:
            return []
        if not isinstance(rejected, list) or not all(_is_number(v) for v in rejected):
            return ["rejected must be a list of x positions"]
        return []
