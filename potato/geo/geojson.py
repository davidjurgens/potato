"""
GeoJSON normalisation to RFC 7946.

Every geometry Potato stores, exports or aggregates goes through
:func:`normalize_feature_collection`, which:

* accepts a FeatureCollection, a Feature, a bare geometry, a list of features,
  or any of these as a JSON string;
* puts positions in ``[longitude, latitude]`` order (``order="latlon"`` swaps
  input that was written the other way round) and refuses positions outside
  -180..180 / -90..90, saying so when the position looks swapped;
* rounds coordinates to ``decimals`` places (7 is about 1 cm);
* drops repeated consecutive positions, closes polygon rings, refuses rings
  with fewer than three distinct positions or no area;
* winds exterior rings counter-clockwise and holes clockwise (the right-hand
  rule of RFC 7946 section 3.1.6).

Antimeridian-crossing geometries are not split; a ring that crosses 180°
should be drawn as two polygons.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

GEOMETRY_TYPES = ("Point", "MultiPoint", "LineString", "MultiLineString",
                  "Polygon", "MultiPolygon", "GeometryCollection")

#: Mean Earth radius in metres (IUGG), used for areas.
EARTH_RADIUS_M = 6371008.8


class GeoJSONError(ValueError):
    """The input is not GeoJSON that can be normalised."""


# ---------------------------------------------------------------------------
# Positions and rings
# ---------------------------------------------------------------------------

def _number(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise GeoJSONError(f"coordinate {v!r} is not a number")
    f = float(v)
    if not math.isfinite(f):
        raise GeoJSONError(f"coordinate {v!r} is not finite")
    return f


def normalize_position(pos: Any, order: str = "lonlat", decimals: int = 7) -> List[float]:
    """One position as ``[lon, lat]`` (plus altitude if given), checked and rounded."""
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        raise GeoJSONError(f"position {pos!r} must be a list of at least two numbers")
    a, b = _number(pos[0]), _number(pos[1])
    lon, lat = (b, a) if order == "latlon" else (a, b)
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        if -180.0 <= lat <= 180.0 and -90.0 <= lon <= 90.0:
            raise GeoJSONError(
                f"position {list(pos)!r} is out of range as [longitude, latitude] but would fit as "
                "[latitude, longitude]; GeoJSON puts longitude first (set coordinate_order: latlon "
                "if your source writes latitude first)")
        raise GeoJSONError(
            f"position {list(pos)!r} is outside longitude -180..180 / latitude -90..90")
    out = [round(lon, decimals), round(lat, decimals)]
    if len(pos) > 2 and pos[2] is not None:
        out.append(round(_number(pos[2]), 3))
    return out


def _dedupe(positions: List[List[float]]) -> List[List[float]]:
    out: List[List[float]] = []
    for p in positions:
        if not out or out[-1][:2] != p[:2]:
            out.append(p)
    return out


def ring_signed_area(ring: Sequence[Sequence[float]]) -> float:
    """Planar shoelace area in degrees²; positive when counter-clockwise."""
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def normalize_ring(ring: Any, exterior: bool, order: str = "lonlat",
                   decimals: int = 7) -> List[List[float]]:
    """A closed linear ring with the RFC 7946 winding for its role."""
    if not isinstance(ring, (list, tuple)):
        raise GeoJSONError("a polygon ring must be a list of positions")
    pts = _dedupe([normalize_position(p, order, decimals) for p in ring])
    if len(pts) > 1 and pts[0][:2] == pts[-1][:2]:
        pts = pts[:-1]
    if len({(p[0], p[1]) for p in pts}) < 3:
        raise GeoJSONError("a polygon ring needs at least three distinct positions")
    pts.append(list(pts[0]))
    area = ring_signed_area(pts)
    if area == 0:
        raise GeoJSONError("a polygon ring has no area (its positions are collinear)")
    if (area > 0) != exterior:
        pts.reverse()
    return pts


# ---------------------------------------------------------------------------
# Geometries
# ---------------------------------------------------------------------------

def normalize_geometry(geom: Any, order: str = "lonlat", decimals: int = 7) -> Optional[Dict[str, Any]]:
    """A normalised copy of one geometry, or None for a null geometry."""
    if geom is None:
        return None
    if not isinstance(geom, dict):
        raise GeoJSONError("a geometry must be an object")
    gtype = geom.get("type")
    if gtype not in GEOMETRY_TYPES:
        raise GeoJSONError(f"unknown geometry type {gtype!r}")
    if gtype == "GeometryCollection":
        parts = geom.get("geometries")
        if not isinstance(parts, list):
            raise GeoJSONError("a GeometryCollection needs a geometries list")
        return {"type": gtype, "geometries": [normalize_geometry(g, order, decimals) for g in parts]}
    coords = geom.get("coordinates")
    if gtype == "Point":
        return {"type": gtype, "coordinates": normalize_position(coords, order, decimals)}
    if not isinstance(coords, (list, tuple)):
        raise GeoJSONError(f"{gtype} coordinates must be a list")
    if gtype == "MultiPoint":
        return {"type": gtype, "coordinates": [normalize_position(p, order, decimals) for p in coords]}
    if gtype == "LineString":
        return {"type": gtype, "coordinates": _line(coords, order, decimals)}
    if gtype == "MultiLineString":
        return {"type": gtype, "coordinates": [_line(c, order, decimals) for c in coords]}
    if gtype == "Polygon":
        return {"type": gtype, "coordinates": _polygon(coords, order, decimals)}
    return {"type": gtype, "coordinates": [_polygon(c, order, decimals) for c in coords]}


def _line(coords: Any, order: str, decimals: int) -> List[List[float]]:
    if not isinstance(coords, (list, tuple)):
        raise GeoJSONError("a line must be a list of positions")
    pts = _dedupe([normalize_position(p, order, decimals) for p in coords])
    if len(pts) < 2:
        raise GeoJSONError("a line needs at least two distinct positions")
    return pts


def _polygon(rings: Any, order: str, decimals: int) -> List[List[List[float]]]:
    if not isinstance(rings, (list, tuple)) or not rings:
        raise GeoJSONError("a polygon needs at least one ring")
    return [normalize_ring(r, i == 0, order, decimals) for i, r in enumerate(rings)]


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def _as_features(obj: Any) -> List[Any]:
    if isinstance(obj, str):
        if not obj.strip():
            return []
        try:
            obj = json.loads(obj)
        except ValueError as e:
            raise GeoJSONError(f"not JSON: {e}") from None
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        raise GeoJSONError("GeoJSON must be an object or a list of features")
    t = obj.get("type")
    if t == "FeatureCollection":
        feats = obj.get("features")
        if not isinstance(feats, list):
            raise GeoJSONError("a FeatureCollection needs a features list")
        return feats
    if t == "Feature":
        return [obj]
    if t in GEOMETRY_TYPES:
        return [{"type": "Feature", "geometry": obj, "properties": {}}]
    raise GeoJSONError(f"unknown GeoJSON type {t!r}")


def normalize_feature(feature: Any, order: str = "lonlat", decimals: int = 7) -> Dict[str, Any]:
    if not isinstance(feature, dict):
        raise GeoJSONError("a feature must be an object")
    if feature.get("type") in GEOMETRY_TYPES:
        feature = {"type": "Feature", "geometry": feature, "properties": {}}
    elif feature.get("type") != "Feature":
        raise GeoJSONError(f"expected a Feature, got {feature.get('type')!r}")
    props = feature.get("properties")
    if props is not None and not isinstance(props, dict):
        raise GeoJSONError("feature properties must be an object or null")
    out: Dict[str, Any] = {"type": "Feature",
                           "geometry": normalize_geometry(feature.get("geometry"), order, decimals),
                           "properties": dict(props or {})}
    if "id" in feature and isinstance(feature["id"], (str, int)) and not isinstance(feature["id"], bool):
        out["id"] = feature["id"]
    return out


def normalize_feature_collection(obj: Any, order: str = "lonlat", decimals: int = 7,
                                 strict: bool = True) -> Tuple[Dict[str, Any], List[str]]:
    """``(FeatureCollection, warnings)``.

    With ``strict`` a bad feature raises :class:`GeoJSONError`; without it the
    feature is dropped and the reason is returned as a warning.
    """
    if order not in ("lonlat", "latlon"):
        raise GeoJSONError("order must be 'lonlat' or 'latlon'")
    features: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for i, f in enumerate(_as_features(obj)):
        try:
            features.append(normalize_feature(f, order, decimals))
        except GeoJSONError as e:
            if strict:
                raise GeoJSONError(f"feature {i}: {e}") from None
            warnings.append(f"feature {i} dropped: {e}")
    return {"type": "FeatureCollection", "features": features}, warnings


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------

def iter_positions(geom: Optional[Dict[str, Any]]) -> Iterable[Sequence[float]]:
    if not geom:
        return
    t = geom.get("type")
    if t == "GeometryCollection":
        for g in geom.get("geometries") or []:
            yield from iter_positions(g)
        return
    c = geom.get("coordinates")
    if t == "Point":
        yield c
    elif t in ("MultiPoint", "LineString"):
        yield from c
    elif t in ("MultiLineString", "Polygon"):
        for part in c:
            yield from part
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring


def bbox(geoms: Iterable[Optional[Dict[str, Any]]]) -> Optional[List[float]]:
    """``[min_lon, min_lat, max_lon, max_lat]`` over several geometries, or None."""
    xs: List[float] = []
    ys: List[float] = []
    for g in geoms:
        for p in iter_positions(g):
            xs.append(p[0])
            ys.append(p[1])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def polygons_of(geom: Optional[Dict[str, Any]]) -> List[List[List[List[float]]]]:
    """The polygons (lists of rings) inside a geometry, recursing into collections."""
    if not geom:
        return []
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    if t == "GeometryCollection":
        out: List[List[List[List[float]]]] = []
        for g in geom.get("geometries") or []:
            out.extend(polygons_of(g))
        return out
    return []


def ring_area_m2(ring: Sequence[Sequence[float]]) -> float:
    """Spherical area of a closed ring in m² (unsigned)."""
    total = 0.0
    n = len(ring)
    if n < 4:
        return 0.0
    for i in range(n - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * EARTH_RADIUS_M ** 2 / 2.0)


def area_km2(geom: Optional[Dict[str, Any]]) -> float:
    """Area of the polygons in a geometry, holes subtracted, in km²."""
    total = 0.0
    for poly in polygons_of(geom):
        if not poly:
            continue
        a = ring_area_m2(poly[0]) - sum(ring_area_m2(h) for h in poly[1:])
        total += max(a, 0.0)
    return total / 1e6


def centroid(geom: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """Mean of the distinct positions -- a label point, not an area centroid."""
    pts = {(p[0], p[1]) for p in iter_positions(geom)}
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
