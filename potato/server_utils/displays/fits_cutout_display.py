"""
FITS cutout display (``type: fits_cutout``).

Shows one or more astronomical images side by side: a single image for
morphology work, or the science / reference / difference triplet used to vet
transient candidates, with an optional light curve underneath. The server
reads the FITS files (astropy, ``pip install 'potato-annotation[astro]'``),
cuts out the region around the item's position, scales it, and caches a PNG
under ``<task_dir>/.potato_cache/fits/``; the browser receives the PNG plus a
JSON description of the WCS, so it can show RA/Dec under the cursor without
reading FITS itself.

Item value, either a path::

    "image": "cutouts/ngc1234.fits"

or a mapping::

    "candidate": {
        "science": "cutouts/c1_sci.fits",
        "reference": "cutouts/c1_ref.fits",
        "difference": "cutouts/c1_diff.fits",
        "ra": 150.1192, "dec": 2.20583,     # or "x": 48, "y": 48 (FITS pixels)
        "size": 48,                          # pixels, or "40 arcsec"
        "stretch": "asinh",                  # per-item scaling (optional)
        "light_curve": "lightcurves/c1.csv"  # or a list of {mjd, band, mag, magerr}
    }

A panel value may itself be a mapping (``{"path": ..., "stretch": ...}``) to
scale one image differently. Precedence, lowest first: display options, the
``panels`` entry, the item, the item's panel mapping.

The panels share zoom, pan and a crosshair (``static/viewers/fits-cutout.js``).
The light curve is drawn with the vendored Plotly, loaded only when an item
has one.
"""

from __future__ import annotations

import html
import json
import math
import os
from typing import Any, Dict, List, Optional

from .base import css_length
from .viewer_display import ViewerDataError, ViewerDisplay, ViewerEngine, resolve_source

DEFAULT_PANELS = (("science", "Science"), ("reference", "Reference"), ("difference", "Difference"))
SCALING_KEYS = ("stretch", "interval", "percentile", "asinh_a", "log_a", "invert", "hdu")
PANEL_KEYS = {"key", "label"} | set(SCALING_KEYS)
LIGHT_CURVE_ROLES = ("time", "mag", "err", "band", "limit")
PLOTLY_SRC = "/static/vendor/plotly-2.27.0.min.js"
MAX_PANELS = 6


class FitsCutoutDisplay(ViewerDisplay):
    name = "fits_cutout"
    description = "FITS image cutouts (single or science/reference/difference) with RA/Dec readout and a light curve"
    required_fields = ["key"]
    optional_fields = {
        "engine": None,
        "allow_remote": False,
        "panels": None,
        "stretch": "linear",
        "interval": "zscale",
        "percentile": 99.5,
        "asinh_a": 0.1,
        "log_a": 1000.0,
        "invert": False,
        "hdu": None,
        "size": None,
        "max_file_mb": 100,
        "max_image_pixels": 25_000_000,
        "light_curve": True,
        "light_curve_columns": None,
        "light_curve_units": "mag",
        "light_curve_height": 260,
        "time_label": "MJD",
        "crosshair": True,
        "compass": True,
        "panel_size": None,
    }
    default_engine = "potato"
    engines = {
        "potato": ViewerEngine(name="potato", label="FITS cutouts", webgl=None,
                               licence="astropy BSD-3-Clause (server side)"),
    }

    # -- options ----------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        from potato.science.converters.fits import astropy_available, parse_size, scaling_errors
        errors = list(scaling_errors({k: options[k] for k in SCALING_KEYS if k in options}, path))
        if options.get("allow_remote"):
            errors.append(f"{path}.allow_remote: fits_cutout reads FITS files on the server, so "
                          f"they must be in the media directory; remote files are not supported")
        panels = options.get("panels")
        if panels is not None:
            if not isinstance(panels, list) or not panels:
                errors.append(f"{path}.panels must be a list of {{key, label}} mappings")
            else:
                if len(panels) > MAX_PANELS:
                    errors.append(f"{path}.panels has {len(panels)} entries; at most {MAX_PANELS}")
                seen = set()
                for n, p in enumerate(panels):
                    where = f"{path}.panels[{n}]"
                    if not isinstance(p, dict):
                        errors.append(f"{where} must be a mapping with key and label")
                        continue
                    extra = sorted(set(p) - PANEL_KEYS)
                    if extra:
                        errors.append(f"{where} has unknown key(s) {', '.join(extra)}; "
                                      f"accepted: {', '.join(sorted(PANEL_KEYS))}")
                    key = p.get("key")
                    if not isinstance(key, str) or not key:
                        errors.append(f"{where}.key must name a key in the item's mapping "
                                      f"(e.g. science)")
                    elif key in seen:
                        errors.append(f"{where}.key '{key}' repeats an earlier panel")
                    else:
                        seen.add(key)
                    if "label" in p and not isinstance(p["label"], str):
                        errors.append(f"{where}.label must be text")
                    errors.extend(scaling_errors({k: p[k] for k in SCALING_KEYS if k in p}, where))
        try:
            parse_size(options.get("size"))
        except ValueError as e:
            errors.append(f"{path}.size: {e}")
        for key, kind in (("max_file_mb", float), ("max_image_pixels", int),
                          ("light_curve_height", int)):
            v = options.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0 or (
                    kind is int and int(v) != v):
                errors.append(f"{path}.{key} must be a positive {'whole ' if kind is int else ''}number")
        for key in ("light_curve", "crosshair", "compass"):
            if not isinstance(options.get(key), bool):
                errors.append(f"{path}.{key} must be true or false")
        if options.get("light_curve_units") not in ("mag", "flux"):
            errors.append(f"{path}.light_curve_units must be mag (brighter is up) or flux")
        if not isinstance(options.get("time_label"), str):
            errors.append(f"{path}.time_label must be text, such as MJD")
        cols = options.get("light_curve_columns")
        if cols is not None:
            if not isinstance(cols, dict):
                errors.append(f"{path}.light_curve_columns must map roles "
                              f"({', '.join(LIGHT_CURVE_ROLES)}) to column names")
            else:
                extra = sorted(set(cols) - set(LIGHT_CURVE_ROLES))
                if extra:
                    errors.append(f"{path}.light_curve_columns has unknown role(s) "
                                  f"{', '.join(extra)}; roles: {', '.join(LIGHT_CURVE_ROLES)}")
                for role, name in cols.items():
                    if not isinstance(name, str) or not name:
                        errors.append(f"{path}.light_curve_columns.{role} must be a column name")
        ps = options.get("panel_size")
        if ps is not None and not isinstance(ps, (int, str)):
            errors.append(f"{path}.panel_size must be a CSS length such as 16rem or 240")
        if not astropy_available():
            errors.append(f"{path}: fits_cutout reads FITS files with astropy, which is not "
                          f"installed. Install it with: pip install 'potato-annotation[astro]'")
        return errors

    # -- rendering ------------------------------------------------------------------

    def _item(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, str) and data.strip():
            return {"image": data.strip()}
        if isinstance(data, dict):
            return data
        raise ViewerDataError("This item names no FITS file. Give a path, or a mapping with "
                              "science, reference and difference (or image).")

    def _panel_specs(self, options, item) -> List[Dict[str, Any]]:
        configured = options.get("panels")
        if configured:
            return [dict(p) for p in configured]
        present = [{"key": k, "label": label} for k, label in DEFAULT_PANELS if item.get(k)]
        if present:
            return present
        if item.get("image"):
            return [{"key": "image", "label": str(item.get("label") or "")}]
        raise ViewerDataError("This item's mapping has no science, reference, difference or "
                              "image file.")

    def client_config(self, field_config, data, options):
        from potato.science.converters.fits import parse_center, parse_size, scaling_errors
        item = self._item(data)
        try:
            center = parse_center({k: item[k] for k in ("ra", "dec", "x", "y") if k in item} or None)
            size = item.get("size", options.get("size"))
            parse_size(size)
        except ValueError as e:
            raise ViewerDataError(f"This item's position or size cannot be used: {e}.")
        item_scaling = {k: item[k] for k in SCALING_KEYS if k in item}
        problems = scaling_errors(item_scaling, "item")
        if problems:
            raise ViewerDataError("This item's scaling options are not valid: " + "; ".join(problems))

        panels = []
        for spec in self._panel_specs(options, item):
            panels.append(self._panel(spec, item, options, center, size, item_scaling))

        cfg: Dict[str, Any] = {
            "panels": panels,
            "aligned": _aligned(panels),
            "crosshair": bool(options.get("crosshair", True)),
            "compass": bool(options.get("compass", True)),
            "panelSize": css_length(options.get("panel_size"), "") or None,
            "lightCurve": None,
            "lightCurveError": None,
            "plotly": PLOTLY_SRC,
        }
        if options.get("light_curve", True) and item.get("light_curve") is not None:
            try:
                lc = self._light_curve(item["light_curve"], options)
                lc["units"] = options.get("light_curve_units") or "mag"
                lc["timeLabel"] = options.get("time_label") or "MJD"
                lc["height"] = int(options.get("light_curve_height") or 260)
                lc["epoch"] = _epoch(item, panels, lc)
                cfg["lightCurve"] = lc
            except ViewerDataError as e:
                cfg["lightCurveError"] = str(e)
        return cfg

    def _panel(self, spec, item, options, center, size, item_scaling) -> Dict[str, Any]:
        from potato.science import astro
        from potato.science.converters import ConverterUnavailable
        from potato.science.converters.fits import FitsError, parse_center, scaling_errors
        key = spec["key"]
        label = spec.get("label") if spec.get("label") is not None else key.replace("_", " ").title()
        out: Dict[str, Any] = {"key": key, "label": label}
        value = item.get(key)
        own: Dict[str, Any] = {}
        if isinstance(value, dict):
            own = {k: value[k] for k in SCALING_KEYS if k in value}
            problems = scaling_errors(own, key)
            if problems:
                out["error"] = "; ".join(problems)
                return out
            value = value.get("path") or value.get("file")
        if not isinstance(value, str) or not value.strip():
            out["error"] = f"This item has no {label.lower() or key} image."
            return out
        params = {k: options[k] for k in SCALING_KEYS if options.get(k) is not None}
        params.update({k: spec[k] for k in SCALING_KEYS if k in spec})
        params.update(item_scaling)
        params.update(own)
        params["center"] = center
        params["size"] = size
        params["max_file_bytes"] = int(float(options.get("max_file_mb") or 100) * 1024 * 1024)
        params["max_image_pixels"] = int(options.get("max_image_pixels") or 25_000_000)
        try:
            _url, path = resolve_source(value, False, f"{label.lower() or key} FITS file")
        except ViewerDataError as e:
            out["error"] = str(e)
            return out
        if path is None or not os.path.isfile(path):
            out["error"] = f"{value} is not in the media directory."
            return out
        try:
            result = astro.cutout(_config(), path, params)
        except (FitsError, ConverterUnavailable, ValueError) as e:
            out["error"] = str(e)
            return out
        except Exception as e:       # astropy can raise almost anything on a damaged file
            out["error"] = f"{os.path.basename(path)} could not be read ({type(e).__name__}: {e})."
            return out
        out.update({"src": result["src"], "wcs": result["wcs"], "meta": result["meta"]})
        return out

    def _light_curve(self, value, options) -> Dict[str, Any]:
        from potato.science.astro import light_curve_from_rows, read_light_curve
        columns = options.get("light_curve_columns") or None
        try:
            if isinstance(value, list):
                if not all(isinstance(r, dict) for r in value):
                    raise ValueError("an inline light curve is a list of objects, one per point")
                return light_curve_from_rows(value, columns, "this item's light curve")
            if isinstance(value, str) and value.strip():
                _url, path = resolve_source(value, False, "light curve")
                if path is None or not os.path.isfile(path):
                    raise ValueError(f"{value} is not in the media directory")
                return read_light_curve(path, columns)
        except (ValueError, OSError) as e:
            raise ViewerDataError(f"The light curve cannot be drawn: {e}.")
        raise ViewerDataError("The light curve cannot be drawn: give a CSV/JSON file or a "
                              "list of points.")

    def render_extras(self, field_config, data, options, cfg) -> str:
        """The light curve's place on the page, and its points as a table, so
        the numbers are there without JavaScript or a pointer."""
        lc = cfg.get("lightCurve")
        if cfg.get("lightCurveError"):
            return (f'<p class="fc-lc-error" role="note">{html.escape(cfg["lightCurveError"])}</p>')
        if not lc:
            return ""
        units = "Magnitude" if lc.get("units") == "mag" else "Flux"
        time_label = html.escape(lc.get("timeLabel") or "MJD")
        rows = []
        for band in lc["bands"]:
            pts = [(t, f"{y:.3f}", f"±{e:.3f}" if e else "") for t, y, e in
                   zip(band["t"], band["y"], band["err"])]
            pts += [(t, f"&gt; {y:.2f}", "upper limit") for t, y in zip(band["limit_t"], band["limit_y"])]
            for t, y, e in sorted(pts):
                rows.append(f"<tr><td>{t:.3f}</td><td>{html.escape(band['name'])}</td>"
                            f"<td>{y}</td><td>{e}</td></tr>")
        height = int(lc.get("height") or 260)
        return (
            f'<div class="fc-lightcurve-wrap">'
            f'<div class="fc-lightcurve" style="height: {height}px" role="img" '
            f'aria-label="Light curve: {units.lower()} against {time_label}, '
            f'{lc["points"]} points in {len(lc["bands"])} band(s)"></div>'
            f'<details class="fc-lc-table"><summary>Light curve points ({lc["points"]})</summary>'
            f'<div class="fc-lc-scroll"><table><thead><tr><th scope="col">{time_label}</th>'
            f'<th scope="col">Band</th><th scope="col">{units}</th><th scope="col">Error</th></tr>'
            f'</thead><tbody>{"".join(rows)}</tbody></table></div></details>'
            f'</div>')

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        classes.append("fits-cutout-container")
        return classes


def _config() -> Dict[str, Any]:
    from potato.science.astro import live_config
    return live_config()


def _aligned(panels: List[Dict[str, Any]]) -> bool:
    """Whether the panels show the same pixels of sky, so one crosshair
    position (as a fraction of the cutout) is the same place in each."""
    shown = [p for p in panels if p.get("meta")]
    if len(shown) < 2:
        return True
    first = shown[0]
    for p in shown[1:]:
        if (p["meta"]["width"], p["meta"]["height"]) != (first["meta"]["width"], first["meta"]["height"]):
            return False
        a, b = first.get("wcs"), p.get("wcs")
        if not a or not b:
            if p["meta"]["region"] != first["meta"]["region"]:
                return False
            continue
        scale = min(a["pixel_scale_arcsec"]) / 3600.0
        if abs(a["pixel_scale_arcsec"][0] - b["pixel_scale_arcsec"][0]) > 0.01 * a["pixel_scale_arcsec"][0]:
            return False
        if _separation_deg(a["center"], b["center"]) > 0.5 * scale:
            return False
    return True


def _separation_deg(a, b) -> float:
    """Haversine separation of two (lon, lat) positions in degrees."""
    d1, d2 = math.radians(a[1]), math.radians(b[1])
    dra, ddec = math.radians(a[0] - b[0]), d2 - d1
    h = math.sin(ddec / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(math.sqrt(min(1.0, h))))


def _epoch(item, panels, lc) -> Optional[float]:
    """Where to mark 'this image' on the light curve: the item's ``epoch``, or
    the first panel's MJD-OBS when the time axis is in that range."""
    value = item.get("epoch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    times = [t for b in lc["bands"] for t in b["t"] + b["limit_t"]]
    for p in panels:
        mjd = (p.get("meta") or {}).get("mjd_obs")
        if isinstance(mjd, (int, float)) and times and min(times) - 1000 <= mjd <= max(times) + 1000:
            return float(mjd)
    return None
