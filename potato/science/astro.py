"""Astronomy cutouts for the ``fits_cutout`` display: caching, light curves,
and the route that serves the PNGs.

The display converts FITS files while the page renders (:func:`cutout`),
which writes ``<task_dir>/.potato_cache/fits/<key>.png`` and ``<key>.json``.
The key is a hash of the file's real path, size, modification time and the
scaling options, so an edited file or a changed stretch makes a new entry and
an unchanged one is converted once. The browser fetches the PNG from
``/science/fits/<key>.png``, which serves only files already in that cache
directory and takes no path from the request.

Light curves (:func:`read_light_curve`) are small CSV or JSON files, parsed
on the server into per-band arrays so the page receives numbers, not a file
to interpret.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_SUBDIR = os.path.join(".potato_cache", "fits")
#: Entries kept in the cache before the oldest are removed.
MAX_CACHE_ENTRIES = 4000
URL_PREFIX = "/science/fits/"
_KEY = re.compile(r"^[0-9a-f]{32}$")

#: Light-curve files larger than this are refused.
MAX_LIGHT_CURVE_BYTES = 2 * 1024 * 1024
MAX_LIGHT_CURVE_POINTS = 20000
#: Column names for each role, tried in order when the config does not say.
LIGHT_CURVE_COLUMNS = {
    "time": ("mjd", "time", "jd", "hjd", "bjd", "t"),
    "mag": ("mag", "magnitude", "flux", "value", "y"),
    "err": ("magerr", "mag_err", "err", "error", "sigma", "fluxerr", "flux_err", "dy"),
    "band": ("band", "filter", "fid", "passband"),
    "limit": ("limit", "upper_limit", "diffmaglim", "maglim", "lim"),
}


def _task_dir(config: Dict[str, Any]) -> str:
    return os.path.realpath(str((config or {}).get("task_dir") or "."))


def cache_dir(config: Dict[str, Any]) -> str:
    return os.path.join(_task_dir(config), CACHE_SUBDIR)


def cache_key(path: str, params: Dict[str, Any]) -> str:
    st = os.stat(path)
    blob = json.dumps({"path": os.path.realpath(path), "size": st.st_size,
                       "mtime": st.st_mtime_ns, "params": params, "v": 1},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def _write_atomic(path: str, data: bytes) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune(folder: str, keep: int = MAX_CACHE_ENTRIES) -> None:
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".json")]
    except OSError:
        return
    if len(names) <= keep:
        return
    entries = []
    for n in names:
        try:
            entries.append((os.path.getmtime(os.path.join(folder, n)), n[:-5]))
        except OSError:
            continue
    entries.sort()
    for _mtime, key in entries[:len(entries) - keep]:
        for ext in (".json", ".png"):
            try:
                os.unlink(os.path.join(folder, key + ext))
            except OSError:
                pass


def cutout(config: Dict[str, Any], path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Convert (or fetch from the cache) one FITS cutout.

    ``params`` are :func:`potato.science.converters.fits.fits_cutout` keyword
    arguments. Returns ``{"src", "key", "wcs", "meta"}``. Raises FitsError,
    ConverterUnavailable or ValueError when the file cannot be shown.
    """
    from potato.science.converters import converter_for
    folder = cache_dir(config)
    key = cache_key(path, params)
    meta_path = os.path.join(folder, key + ".json")
    png_path = os.path.join(folder, key + ".png")
    if os.path.isfile(meta_path) and os.path.isfile(png_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                stored = json.load(f)
            os.utime(meta_path)          # recently used: pruned last
            return {"src": URL_PREFIX + key + ".png", "key": key, **stored}
        except (OSError, ValueError):
            pass                         # rebuild a damaged entry
    convert = converter_for(path)
    if convert is None:
        raise ValueError(f"{os.path.basename(path)} is not a FITS file "
                         f"(.fits, .fit, .fts, optionally .gz)")
    result = convert(path, **params)
    os.makedirs(folder, exist_ok=True)
    _write_atomic(png_path, result["png"])
    stored = {"wcs": result["wcs"], "meta": result["meta"]}
    _write_atomic(meta_path, json.dumps(stored).encode("utf-8"))
    _prune(folder)
    return {"src": URL_PREFIX + key + ".png", "key": key, **stored}


# ---------------------------------------------------------------------------
# Light curves
# ---------------------------------------------------------------------------

def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "null", "none", "--", "-"):
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _pick_column(header: List[str], role: str, configured: Optional[str]) -> Optional[str]:
    lower = {h.lower().strip(): h for h in header}
    if configured:
        return lower.get(configured.lower())
    for name in LIGHT_CURVE_COLUMNS[role]:
        if name in lower:
            return lower[name]
    return None


def light_curve_from_rows(rows: List[Dict[str, Any]], columns: Optional[Dict[str, str]] = None,
                          where: str = "light curve") -> Dict[str, Any]:
    """Group rows into bands: ``{"bands": [{"name", "t", "y", "err",
    "limit_t", "limit_y"}], "points": n}``.

    A row with a value is a detection; a row with no value but a limit is an
    upper limit (drawn as an open triangle). Rows with no usable time are
    skipped and counted."""
    columns = columns or {}
    header = list(rows[0].keys()) if rows else []
    col = {role: _pick_column(header, role, columns.get(role)) for role in LIGHT_CURVE_COLUMNS}
    for role in ("time", "mag"):
        if columns.get(role) and col[role] is None:
            raise ValueError(f"{where} has no '{columns[role]}' column (columns: {', '.join(header)})")
    if rows and col["time"] is None:
        raise ValueError(f"{where}: no time column; name one with light_curve_columns.time "
                         f"(columns: {', '.join(header)})")
    if rows and col["mag"] is None and col["limit"] is None:
        raise ValueError(f"{where}: no magnitude or flux column; name one with "
                         f"light_curve_columns.mag (columns: {', '.join(header)})")
    bands: Dict[str, Dict[str, list]] = {}
    skipped = 0
    for row in rows[:MAX_LIGHT_CURVE_POINTS]:
        t = _number(row.get(col["time"])) if col["time"] else None
        if t is None:
            skipped += 1
            continue
        name = str(row.get(col["band"], "") if col["band"] else "").strip() or "all"
        b = bands.setdefault(name, {"name": name, "t": [], "y": [], "err": [],
                                    "limit_t": [], "limit_y": []})
        y = _number(row.get(col["mag"])) if col["mag"] else None
        if y is not None:
            err = _number(row.get(col["err"])) if col["err"] else None
            b["t"].append(t)
            b["y"].append(y)
            b["err"].append(err if err is not None and err >= 0 else 0.0)
            continue
        lim = _number(row.get(col["limit"])) if col["limit"] else None
        if lim is not None:
            b["limit_t"].append(t)
            b["limit_y"].append(lim)
        else:
            skipped += 1
    out = {"bands": sorted(bands.values(), key=lambda b: _band_order(b["name"])),
           "points": sum(len(b["t"]) + len(b["limit_t"]) for b in bands.values())}
    if skipped:
        out["skipped"] = skipped
    if len(rows) > MAX_LIGHT_CURVE_POINTS:
        out["truncated"] = len(rows) - MAX_LIGHT_CURVE_POINTS
    return out


_BAND_ORDER = ["u", "g", "r", "i", "z", "y", "j", "h", "k", "w1", "w2", "c", "o"]


def _band_order(name: str):
    n = name.lower().replace("ztf_", "").replace("ztf", "").replace("lsst", "").strip("_ ")
    return (_BAND_ORDER.index(n) if n in _BAND_ORDER else len(_BAND_ORDER), name)


def read_light_curve(path: str, columns: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Parse a CSV/TSV or JSON light curve from disk (size-limited)."""
    label = os.path.basename(path)
    size = os.path.getsize(path)
    if size > MAX_LIGHT_CURVE_BYTES:
        raise ValueError(f"light curve {label} is {size / 1e6:.1f} MB, over the "
                         f"{MAX_LIGHT_CURVE_BYTES / 1e6:.0f} MB limit")
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if label.lower().endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValueError(f"light curve {label} is not valid JSON ({e})") from None
        if isinstance(data, dict):
            data = data.get("points") or data.get("data") or []
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError(f"light curve {label} must be a list of objects, one per point")
        return light_curve_from_rows(data, columns, f"light curve {label}")
    sample = text[:4096]
    delimiter = "\t" if label.lower().endswith(".tsv") or sample.count("\t") > sample.count(",") else ","
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = list(row for _, row in zip(range(MAX_LIGHT_CURVE_POINTS + 1), reader))
    return light_curve_from_rows(rows, columns, f"light curve {label}")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

_config: Dict[str, Any] = {}


def live_config() -> Dict[str, Any]:
    """The running project's config: the same dict the display renders with,
    so the page and this route agree on where the cache is."""
    try:
        from potato.server_utils.config_module import config
        if config:
            return config
    except ImportError:   # pragma: no cover
        pass
    return _config


def serve_cutout(key: str):
    from flask import abort, send_file
    if not _KEY.match(key or ""):
        abort(404)
    path = os.path.join(cache_dir(live_config()), key + ".png")
    if not os.path.isfile(path):
        abort(404)
    response = send_file(path, mimetype="image/png", max_age=3600)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def register_astro_routes(app, config) -> None:
    """``GET /science/fits/<key>.png``. Called from routes.configure_routes()."""
    global _config
    _config = config if config is not None else {}
    if "science_fits_cutout" in app.view_functions:
        return
    app.add_url_rule("/science/fits/<key>.png", "science_fits_cutout", serve_cutout,
                     methods=["GET"])
