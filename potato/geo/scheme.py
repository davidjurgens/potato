"""
Configuration for ``annotation_type: geo_annotation``: validation, label
colours, basemap loading and answer decoding, shared by the generator, the
config validator and the exporters.

Potato never loads a map from the internet unless the configuration names
one. A scheme needs a basemap the project supplies -- a GeoJSON outline, a
georeferenced image, a GeoTIFF -- or tiles from a URL the administrator
wrote into ``basemap.tiles``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .geojson import GeoJSONError, normalize_feature_collection

TASKS = ("draw", "pin", "classify_region")
TOOLS = ("point", "line", "polygon", "freehand")
PROJECTIONS = ("EPSG:3857", "EPSG:4326")
BASEMAP_KEYS = {"geojson", "tiles", "attribution", "image", "extent", "geotiff",
                "region_id_property", "region_name_property", "max_zoom"}
RASTER_KEYS = ("tiles", "image", "geotiff")

#: Okabe-Ito, reordered so the first few are distinct in every colour-vision type.
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#7F7F7F", "#000000")

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_TILE_URL = re.compile(r"\{z\}.*\{x\}.*\{-?y\}|\{z\}.*\{-?y\}.*\{x\}")

#: The OpenStreetMap Foundation's own tile servers. Their usage policy
#: (https://operations.osmfoundation.org/policies/tiles/) forbids heavy use,
#: which a crowd of annotators panning a map is.
OSM_TILE_HOSTS = ("tile.openstreetmap.org", "tile.osm.org")


def _is_url(v: str) -> bool:
    return v.startswith(("http://", "https://"))


def _is_external(v: str) -> bool:
    return _is_url(v) or v.startswith("//")


def _valid_lonlat(v: Any) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v)
            and -180 <= v[0] <= 180 and -90 <= v[1] <= 90)


def _valid_extent(v: Any) -> bool:
    return (isinstance(v, (list, tuple)) and len(v) == 4
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v)
            and -180 <= v[0] < v[2] <= 180 and -90 <= v[1] < v[3] <= 90)


def label_list(scheme: Dict[str, Any]) -> List[Dict[str, str]]:
    """``[{"name", "color"}, ...]`` with palette colours filled in."""
    out = []
    for i, entry in enumerate(scheme.get("labels") or []):
        if isinstance(entry, dict):
            name = str(entry.get("name", ""))
            color = entry.get("color") or PALETTE[i % len(PALETTE)]
        else:
            name, color = str(entry), PALETTE[i % len(PALETTE)]
        out.append({"name": name, "color": color})
    return out


def feature_text_config(scheme: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The per-feature text box, normalised, or None when it is off."""
    ft = scheme.get("feature_text")
    if not ft:
        return None
    if ft is True:
        return {"prompt": "Name", "required": False, "placeholder": ""}
    return {"prompt": str(ft.get("prompt") or "Name"), "required": bool(ft.get("required", False)),
            "placeholder": str(ft.get("placeholder") or "")}


def validate_geo_scheme(scheme: Dict[str, Any], path: str) -> List[str]:
    """Refuse a bad geo_annotation scheme (``ValueError``); return warnings."""
    warnings: List[str] = []

    def bad(msg: str) -> None:
        raise ValueError(f"{path}{msg}")

    task = scheme.get("task", "draw")
    if task not in TASKS:
        bad(f".task must be one of {', '.join(TASKS)}, got {task!r}")

    labels = scheme.get("labels")
    if not isinstance(labels, list) or not labels:
        bad(".labels must be a non-empty list (for task: pin, one label per place to mark)")
    names = []
    for i, entry in enumerate(labels):
        if isinstance(entry, dict):
            name = entry.get("name")
            color = entry.get("color")
            extra = set(entry) - {"name", "color", "description"}
            if extra:
                bad(f".labels[{i}] has unknown keys: {', '.join(sorted(extra))}")
            if color is not None and not (isinstance(color, str) and _HEX.match(color)):
                bad(f".labels[{i}].color must be a hex colour such as '#0072B2'")
        else:
            name = entry
        if not isinstance(name, str) or not name.strip():
            bad(f".labels[{i}] must be a non-empty string or {{name: ...}} "
                "(quote YAML words such as Yes/No/On, which load as booleans)")
        names.append(name)
    if len(set(names)) != len(names):
        bad(".labels must not repeat a name")

    tools = scheme.get("tools")
    if tools is not None:
        if task != "draw":
            bad(".tools applies to task: draw only")
        if (not isinstance(tools, list) or not tools
                or not all(isinstance(t, str) and t in TOOLS for t in tools)):
            bad(f".tools must be a non-empty list drawn from {', '.join(TOOLS)}")

    ft = scheme.get("feature_text")
    if ft is not None and not isinstance(ft, bool):
        if not isinstance(ft, dict) or set(ft) - {"prompt", "required", "placeholder"}:
            bad(".feature_text must be true/false or {prompt, required, placeholder}")
        if "required" in ft and not isinstance(ft["required"], bool):
            bad(".feature_text.required must be true or false")
    if ft and task == "classify_region":
        bad(".feature_text does not apply to task: classify_region")

    for key in ("basemap_field", "preannotation_field"):
        if key in scheme and not (isinstance(scheme[key], str) and scheme[key].strip()):
            bad(f".{key} must be the name of an item field")
    if scheme.get("preannotation_field") and task == "classify_region":
        bad(".preannotation_field does not apply to task: classify_region")

    order = scheme.get("coordinate_order", "lonlat")
    if order not in ("lonlat", "latlon"):
        bad(".coordinate_order must be lonlat (GeoJSON) or latlon")
    if scheme.get("projection", "EPSG:3857") not in PROJECTIONS:
        bad(f".projection must be one of {', '.join(PROJECTIONS)}")
    if "center" in scheme and not _valid_lonlat(scheme["center"]):
        bad(".center must be [longitude, latitude]")
    zoom = scheme.get("zoom")
    if zoom is not None and not (isinstance(zoom, (int, float)) and not isinstance(zoom, bool)
                                 and 0 <= zoom <= 24):
        bad(".zoom must be a number from 0 to 24")
    height = scheme.get("height")
    if height is not None and not (isinstance(height, int) and not isinstance(height, bool)
                                   and 200 <= height <= 1200):
        bad(".height must be a whole number of pixels from 200 to 1200")
    for key in ("snapping", "require_all_regions"):
        if key in scheme and not isinstance(scheme[key], bool):
            bad(f".{key} must be true or false")
    if scheme.get("require_all_regions") and task != "classify_region":
        bad(".require_all_regions applies to task: classify_region only")
    for key in ("min_features", "max_features"):
        v = scheme.get(key)
        if v is not None:
            if task != "draw":
                bad(f".{key} applies to task: draw only")
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                bad(f".{key} must be a whole number, 0 or more")
    if (isinstance(scheme.get("min_features"), int) and isinstance(scheme.get("max_features"), int)
            and scheme["min_features"] > scheme["max_features"]):
        bad(".min_features must not exceed max_features")

    basemap = scheme.get("basemap")
    if basemap is None:
        if not scheme.get("basemap_field"):
            bad(": give the map a basemap -- basemap: {geojson: maps/regions.geojson} (an outline "
                "the project supplies), basemap: {image: ..., extent: [...]}, basemap: {geotiff: ...}, "
                "or basemap: {tiles: <your tile URL>, attribution: ...}. Potato loads no map from "
                "the internet unless you configure one.")
    else:
        warnings += _validate_basemap(basemap, path + ".basemap", bad)
    if task == "classify_region" and not ((basemap or {}).get("geojson") or scheme.get("basemap_field")):
        bad(": task: classify_region needs region outlines in basemap.geojson (or a basemap_field)")
    return warnings


def _validate_basemap(basemap: Any, path: str, bad) -> List[str]:
    warnings: List[str] = []
    if not isinstance(basemap, dict) or not basemap:
        bad(" must be an object such as {geojson: maps/regions.geojson}")
    unknown = set(basemap) - BASEMAP_KEYS
    if unknown:
        raise ValueError(f"{path} has unknown keys: {', '.join(sorted(unknown))} "
                         f"(allowed: {', '.join(sorted(BASEMAP_KEYS))})")
    rasters = [k for k in RASTER_KEYS if basemap.get(k)]
    if len(rasters) > 1:
        raise ValueError(f"{path}: use one of tiles, image or geotiff, not {' and '.join(rasters)}")
    if not rasters and not basemap.get("geojson"):
        raise ValueError(f"{path} needs geojson, tiles, image or geotiff")
    for key in ("geojson", "tiles", "image", "geotiff", "attribution",
                "region_id_property", "region_name_property"):
        if key in basemap and not (isinstance(basemap[key], str) and basemap[key].strip()):
            raise ValueError(f"{path}.{key} must be a non-empty string")
    gj = basemap.get("geojson")
    if gj and not _is_external(gj) and not gj.startswith("/"):
        if os.path.isabs(gj) or ".." in gj.replace("\\", "/").split("/"):
            raise ValueError(f"{path}.geojson must be a path inside the project (relative to task_dir)")
    tiles = basemap.get("tiles")
    if tiles:
        if not (_is_url(tiles) or tiles.startswith("/")):
            raise ValueError(f"{path}.tiles must be an http(s) URL or a path on this server")
        if not _TILE_URL.search(tiles):
            raise ValueError(f"{path}.tiles must contain {{z}}, {{x}} and {{y}} (or {{-y}})")
        if _is_url(tiles) and not basemap.get("attribution"):
            raise ValueError(f"{path}.attribution is required with external tiles: tile providers "
                             "require credit on the map")
        if any(h in tiles for h in OSM_TILE_HOSTS):
            warnings.append(
                f"{path}.tiles uses the OpenStreetMap Foundation's tile servers. Their tile usage "
                "policy forbids heavy use; a study with many annotators should host its own tiles "
                "or use a commercial provider.")
    if basemap.get("image"):
        if not _valid_extent(basemap.get("extent")):
            raise ValueError(f"{path}.extent must be [min_lon, min_lat, max_lon, max_lat] for an image")
    elif "extent" in basemap:
        raise ValueError(f"{path}.extent applies to basemap.image only")
    mz = basemap.get("max_zoom")
    if mz is not None and not (isinstance(mz, int) and not isinstance(mz, bool) and 0 <= mz <= 24):
        raise ValueError(f"{path}.max_zoom must be a whole number from 0 to 24")
    return warnings


# ---------------------------------------------------------------------------
# Per-item basemaps
# ---------------------------------------------------------------------------

#: Item field the server adds when it refuses an item's basemap:
#: ``{basemap_field: message}``. The page shows the message instead of a map.
REFUSED_KEY = "_geo_basemap_refused"


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url if not url.startswith("//") else "https:" + url).hostname or "").lower()


def _configured_hosts(basemap: Any) -> set:
    if not isinstance(basemap, dict):
        return set()
    return {_host(v) for v in basemap.values() if isinstance(v, str) and _is_external(v)}


def check_item_basemap(scheme: Dict[str, Any], value: Any) -> Optional[str]:
    """Why an item's ``basemap_field`` value is refused, or None when it is fine.

    The item's value is merged over the scheme's basemap the way the page
    merges it, then held to the same rules as a configured basemap
    (:func:`_validate_basemap`: tile URL shape, attribution with external
    tiles, an extent with an image). On top of that an item may name an
    external server only when the scheme's own basemap names that host, since
    item data is not configuration and no map loads from the internet unless
    the configuration says so.
    """
    if value in (None, ""):
        return None
    if isinstance(value, dict) and value.get("type") in ("FeatureCollection", "Feature"):
        return None
    scheme_map = scheme.get("basemap") if isinstance(scheme.get("basemap"), dict) else {}
    allowed = _configured_hosts(scheme_map)
    if isinstance(value, str):
        text = value.strip()
        if _is_external(text) and _host(text) not in allowed:
            return (f"its basemap is on {_host(text) or text}, a server the "
                    f"configuration does not name")
        return None
    if not isinstance(value, dict):
        return f"its basemap is a {type(value).__name__}, not a URL or an object"
    merged = dict(scheme_map)
    if any(value.get(k) for k in RASTER_KEYS):
        for k in RASTER_KEYS + ("extent", "attribution"):
            merged.pop(k, None)
    for k, v in value.items():
        if k == "geojson" and isinstance(v, dict):
            merged[k] = "inline.geojson"      # an outline given inline
        else:
            merged[k] = v

    def bad(msg: str) -> None:
        raise ValueError(f"basemap{msg}")

    try:
        _validate_basemap(merged, "basemap", bad)
    except ValueError as e:
        return f"its basemap settings are invalid: {str(e).rstrip('.')}"
    for k in RASTER_KEYS + ("geojson",):
        v = value.get(k)
        if isinstance(v, str) and _is_external(v) and _host(v) not in allowed:
            return (f"its basemap.{k} is on {_host(v) or v}, a server the "
                    f"configuration does not name")
    return None


def screen_item_basemaps(config: Dict[str, Any], record: Any) -> Any:
    """``record`` with every refused per-item basemap removed and the reason
    recorded under :data:`REFUSED_KEY`, for the page to show."""
    if not isinstance(record, dict):
        return record
    refused: Dict[str, str] = {}
    for scheme in (config or {}).get("annotation_schemes") or []:
        if not (isinstance(scheme, dict) and scheme.get("annotation_type") == "geo_annotation"):
            continue
        field = scheme.get("basemap_field")
        if not field or field not in record:
            continue
        reason = check_item_basemap(scheme, record[field])
        if reason:
            refused[str(field)] = reason
    if not refused:
        return record
    import logging
    logging.getLogger(__name__).warning("geo_annotation: %s", "; ".join(
        f"item field '{k}' not loaded, as {v}" for k, v in refused.items()))
    out = {k: v for k, v in record.items() if k not in refused}
    out[REFUSED_KEY] = refused
    return out


# ---------------------------------------------------------------------------
# Basemaps and regions
# ---------------------------------------------------------------------------

def region_id(feature: Dict[str, Any], index: int, id_property: str = "id") -> str:
    """The id a region is stored under: the id property, else the feature id, else ``r<index>``."""
    props = feature.get("properties") or {}
    if props.get(id_property) not in (None, ""):
        return str(props[id_property])
    if feature.get("id") not in (None, ""):
        return str(feature["id"])
    return f"r{index}"


def with_region_ids(fc: Dict[str, Any], id_property: str = "id") -> Dict[str, Any]:
    feats = []
    for i, f in enumerate(fc.get("features") or []):
        feats.append({**f, "id": region_id(f, i, id_property)})
    return {"type": "FeatureCollection", "features": feats}


def resolve_project_path(rel: str, task_dir: str) -> str:
    from potato.server_utils.config_module import validate_path_security
    return validate_path_security(rel, task_dir)


def load_geojson_file(rel: str, task_dir: str, order: str = "lonlat") -> Dict[str, Any]:
    """Read and normalise a GeoJSON file under ``task_dir``."""
    full = resolve_project_path(rel, task_dir)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"basemap GeoJSON not found: {rel} (looked in {full})")
    with open(full, encoding="utf-8") as f:
        data = json.load(f)
    fc, _ = normalize_feature_collection(data, order=order)
    return fc


def scheme_regions(scheme: Dict[str, Any], task_dir: str) -> Optional[Dict[str, Any]]:
    """The scheme's own basemap outline with region ids, or None (URL or absent)."""
    basemap = scheme.get("basemap") or {}
    gj = basemap.get("geojson")
    if not gj or _is_external(gj) or gj.startswith("/"):
        return None
    fc = load_geojson_file(gj, task_dir, scheme.get("coordinate_order", "lonlat"))
    return with_region_ids(fc, basemap.get("region_id_property", "id"))


def item_basemap_regions(scheme: Dict[str, Any], item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A per-item basemap outline (``basemap_field`` holding GeoJSON), or None."""
    field = scheme.get("basemap_field")
    if not field or not isinstance(item, dict):
        return None
    value = item.get(field)
    if isinstance(value, dict) and value.get("type") != "FeatureCollection" and "geojson" in value:
        value = value["geojson"]
    if not isinstance(value, dict) or value.get("type") not in ("FeatureCollection", "Feature"):
        return None
    try:
        fc, _ = normalize_feature_collection(value, order=scheme.get("coordinate_order", "lonlat"),
                                             strict=False)
    except GeoJSONError:
        return None
    return with_region_ids(fc, (scheme.get("basemap") or {}).get("region_id_property", "id"))


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def decode_answer(labels: Any, schema: str) -> Optional[Dict[str, Any]]:
    """The stored FeatureCollection for one scheme, from a labels entry, or None.

    The page stores one hidden input, ``schema:::schema``, holding JSON; the
    export context hands it over as ``{schema: "<json>"}``.
    """
    raw = labels
    if isinstance(raw, dict) and raw.get("type") != "FeatureCollection":
        raw = raw.get(schema, next(iter(raw.values())) if len(raw) == 1 else None)
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
        return raw
    return None


def answer_features(labels: Any, schema: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Normalised features of a stored answer, and why any were dropped."""
    fc = decode_answer(labels, schema)
    if fc is None:
        return [], []
    try:
        norm, warnings = normalize_feature_collection(fc, strict=False)
    except GeoJSONError as e:
        return [], [str(e)]
    return norm["features"], warnings
