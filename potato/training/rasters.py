"""Images a trainer can open, made from sources it cannot.

A microscopy item is an OME-Zarr directory or an OME-TIFF with channels,
z-slices and time points; the detection trainers read RGB files. So at
bundle time each plane that carries annotations (``z``, ``t``) is rendered
with the server's own compositor (``potato/science/microscopy.py``, the
channels and contrast the scheme shows by default) and the item becomes one
row per plane: ``<instance id>@z<z>t<t>``, with ``plane_of`` naming the item
and the plane's ROIs as its targets. An item with nothing drawn yet is
rendered at its middle z-slice and first time point, which is what the
viewer opens on. The renders are on the Potato host, so a remote training
host needs neither zarr nor the raw data.

After prediction :func:`finalize_file` folds each item's plane predictions
back into the microscopy answer, ``{"image": {...}, "rois": [...]}`` with
each ROI's ``z`` and ``t``, which is what write-back stores as the prelabel.
Held-out scores are computed before that, per plane.

Geo answers are GeoJSON in EPSG:4326 over a raster basemap: a GeoTIFF, or an
image with a ``[min_lon, min_lat, max_lon, max_lat]`` extent (placed in
lon/lat, as the map widget places it). :func:`geo_rasters` writes the raster
as an RGB image, turns each labelled feature into an image-widget shape on
it (polygon, polyline or landmark, normalized), and stores the pixel-to-map
transform on the row as ``georef``. The detection and segmentation trainers
then train on it like any image, tiled if it is large, and
:func:`finalize_file` turns their shapes back into a FeatureCollection in
EPSG:4326 for write-back. A GeoTIFF's transform is read from its own tags
(ModelPixelScale and ModelTiepoint, or ModelTransformation, and the EPSG
code in the GeoKey directory); a projected one is reprojected with pyproj.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = ["PLANE_TYPES", "render_planes", "finalize_file", "geo_rasters",
           "read_georef", "to_pixels", "to_lonlat"]

#: Annotation types whose items are rendered to planes.
PLANE_TYPES = ("microscopy",)

#: Planes larger than this are rendered from a coarser pyramid level; the
#: ROIs are normalized, so they fit any level. Tiling can then cut the
#: render if it is still large.
_MAX_PLANE_PIXELS = 64_000_000


def _plane_key(obj: Dict[str, Any]) -> Tuple[int, int]:
    try:
        return int(obj.get("z") or 0), int(obj.get("t") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _render(image, z: int, t: int, dest: str) -> Tuple[int, int]:
    from PIL import Image
    from potato.science.microscopy import (composite, default_channel_spec,
                                           parse_channel_spec, pick_level)
    scale = 1.0
    while (image.size_x / scale) * (image.size_y / scale) > _MAX_PLANE_PIXELS:
        scale *= 2
    level = pick_level(image, scale)
    fy, fx = image.level_factor(level)
    width, height = int(round(image.size_x / fx)), int(round(image.size_y / fy))
    channels = parse_channel_spec(default_channel_spec(image), image)
    pixels = composite(image, level, (0, 0, width, height), channels, z, t)
    Image.fromarray(pixels).save(dest)
    return width, height


def render_planes(rows: Sequence[Dict[str, Any]], split: str, media_dir: str,
                  schema_name: str, scheme: Dict[str, Any],
                  task_dir: str, media_directory: str,
                  problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Each microscopy row as one row per annotated plane, rendered to PNG."""
    from potato.science.converters.ome import open_ome
    from potato.training.dataset import _media_file
    problems = problems if problems is not None else []
    out: List[Dict[str, Any]] = []
    for row in rows:
        reference = row.get("media_source") or row.get("media_missing")
        if not reference:
            out.append(row)
            continue
        source = reference if os.path.isabs(reference) else _media_file(
            reference, task_dir, media_directory)
        try:
            image = open_ome(source)
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s" % (row.get("instance_id"), exc))
            continue
        iid = str(row["instance_id"])
        rois = (row.get("targets") or {}).get(schema_name)
        planes: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        if isinstance(rois, list):
            for roi in rois:
                planes.setdefault(_plane_key(roi), []).append(
                    {k: v for k, v in roi.items() if k not in ("z", "t")})
        if not planes:
            planes[(image.size_z // 2, 0)] = []
        folder = hashlib.sha1(iid.encode()).hexdigest()[:12]
        os.makedirs(os.path.join(media_dir, "planes", folder), exist_ok=True)
        for (z, t), objects in sorted(planes.items()):
            try:
                image.check_plane(0, z, t)
            except Exception as exc:  # noqa: BLE001
                problems.append("%s z=%d t=%d: %s" % (iid, z, t, exc))
                continue
            name = "z%d_t%d.png" % (z, t)
            dest = os.path.join(media_dir, "planes", folder, name)
            width, height = _render(image, z, t, dest)
            plane = {k: v for k, v in row.items()
                     if k not in ("instance_id", "targets", "soft_targets",
                                  "media", "media_missing")}
            plane.update({"instance_id": "%s@z%dt%d" % (iid, z, t), "plane_of": iid,
                          "plane": {"z": z, "t": t, "width": image.size_x,
                                    "height": image.size_y},
                          "media": os.path.join("planes", folder, name)})
            if split != "unlabeled":
                plane["targets"] = dict(row.get("targets") or {}, **{schema_name: objects})
            out.append(plane)
    return out


def _georefs(bundle) -> Dict[str, Dict[str, Any]]:
    """Each geo item's georef, from its row or, when tiled, its parent."""
    from potato.training.tiling import _parents
    out: Dict[str, Dict[str, Any]] = {}
    for split in list((bundle.manifest.get("splits") or {})):
        for row in bundle.read_split(split):
            if row.get("georef") and not row.get("parent_id"):
                out[str(row["instance_id"])] = row["georef"]
    for parent in _parents(bundle).values():
        if parent.get("georef"):
            out[str(parent["instance_id"])] = parent["georef"]
    return out


def finalize_file(bundle, path: str) -> int:
    """Rewrite *path* with each item's plane predictions as one microscopy
    answer, and each geo item's shapes as GeoJSON in EPSG:4326. Returns the
    number of records written, or 0 when there was nothing to convert."""
    planes: Dict[str, Dict[str, Any]] = {}
    for split in list((bundle.manifest.get("splits") or {})):
        for row in bundle.read_split(split):
            if row.get("plane_of"):
                planes[str(row["instance_id"])] = row
    from potato.training.tiling import _parents
    for parent in _parents(bundle).values():
        if parent.get("plane_of"):
            planes[str(parent["instance_id"])] = parent
    georefs = _georefs(bundle)
    if not planes and not georefs:
        return 0
    if not os.path.isfile(path):
        return 0
    records: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            georef = georefs.get(str(record.get("instance_id")))
            if georef is not None and isinstance(record.get("payload"), list):
                record["payload"] = objects_to_features(
                    record["payload"], to_lonlat(georef, georef["width"], georef["height"]))
            row = planes.get(str(record.get("instance_id")))
            if row is None:
                records.append(record)
                continue
            key = (str(row["plane_of"]), str(record.get("schema_name")))
            entry = grouped.setdefault(key, {"image": {
                "width": row["plane"]["width"], "height": row["plane"]["height"]},
                "rois": [], "confidences": [], "heldout_only": False})
            # One plane made from an annotator's answer makes the item's
            # whole answer unpublishable, as in tiling.stitch_file.
            entry["heldout_only"] = entry["heldout_only"] or bool(record.get("heldout_only"))
            payload = record.get("payload")
            for obj in payload if isinstance(payload, list) else []:
                if isinstance(obj, dict):
                    entry["rois"].append(dict(obj, z=row["plane"]["z"], t=row["plane"]["t"]))
            if isinstance(record.get("confidence"), (int, float)):
                entry["confidences"].append(float(record["confidence"]))
    for (iid, schema), entry in grouped.items():
        if not entry["rois"]:
            continue
        confidences = entry.pop("confidences")
        heldout = entry.pop("heldout_only")
        record = {"instance_id": iid, "schema_name": schema, "payload": entry,
                  "confidence": (round(sum(confidences) / len(confidences), 4)
                                 if confidences else None)}
        if heldout:
            record["heldout_only"] = True
        records.append(record)
    with open(path, "w") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


# ---------------------------------------------------------------------- geo

_GEOTIFF_SUFFIXES = (".tif", ".tiff", ".cog")


def item_basemap(scheme: Dict[str, Any], item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The raster an item's map shows, as the widget resolves it: the item's
    ``basemap_field`` (a GeoTIFF path, or ``{image, extent}`` /
    ``{geotiff}``) over the scheme's ``basemap``."""
    base = dict(scheme.get("basemap") or {})
    value = item_data.get(scheme.get("basemap_field")) if scheme.get("basemap_field") else None
    if isinstance(value, str) and value.lower().split("?")[0].endswith(_GEOTIFF_SUFFIXES):
        base = {"geotiff": value}
    elif isinstance(value, dict) and (value.get("image") or value.get("geotiff")):
        base = {k: value[k] for k in ("image", "extent", "geotiff") if k in value}
    if base.get("geotiff"):
        return {"geotiff": str(base["geotiff"])}
    if base.get("image") and base.get("extent"):
        return {"image": str(base["image"]), "extent": [float(v) for v in base["extent"]]}
    return None


def read_georef(path: str) -> Tuple[Any, Dict[str, Any]]:
    """``(RGB uint8 array, georef)`` for a GeoTIFF.

    The georef is ``{"kind": "affine", "crs": "EPSG:n", "transform": [a, b,
    c, d, e, f]}`` with map x = a*col + b*row + c and y = d*col + e*row + f
    at a pixel's corner. Bands past the third are dropped and each is
    stretched between its 2nd and 98th percentile, as a viewer would show it.
    """
    import numpy
    import tifffile
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        tags = {tag.code: tag.value for tag in page.tags.values()}
        data = page.asarray()
    if 34264 in tags:
        m = [float(v) for v in tags[34264]]
        transform = [m[0], m[1], m[3], m[4], m[5], m[7]]
    elif 33550 in tags and 33922 in tags:
        sx, sy = float(tags[33550][0]), float(tags[33550][1])
        i, j, _k, x, y = (float(v) for v in tags[33922][:5])
        transform = [sx, 0.0, x - i * sx, 0.0, -sy, y + j * sy]
    else:
        raise ValueError("%s has no georeferencing tags" % os.path.basename(path))
    epsg = 4326
    point_raster = False
    keys = tags.get(34735)
    if keys is not None:
        keys = [int(v) for v in keys]
        found = {}
        for n in range(4, len(keys), 4):
            key, location, _count, value = keys[n:n + 4]
            if location == 0:
                found[key] = value
        # ProjectedCSTypeGeoKey, else GeographicTypeGeoKey.
        code = found.get(3072) or found.get(2048)
        if code == 32767:
            raise ValueError("%s uses a user-defined coordinate system (EPSG code 32767), "
                             "which cannot be reprojected; save it with an EPSG code"
                             % os.path.basename(path))
        if code:
            epsg = code
        # GTRasterTypeGeoKey 2 is PixelIsPoint: the tiepoint is a pixel's centre.
        point_raster = found.get(1025) == 2
    if point_raster and 34264 not in tags:
        transform[2] -= transform[0] / 2.0
        transform[5] -= transform[4] / 2.0
    if data.ndim == 3 and data.shape[0] < data.shape[-1] and data.shape[0] <= 16:
        data = numpy.moveaxis(data, 0, -1)
    if data.ndim == 2:
        data = data[..., None]
    bands = data[..., :3].astype("float64")
    out = numpy.zeros(bands.shape[:2] + (3,), dtype="uint8")
    for band in range(bands.shape[-1]):
        values = bands[..., band]
        finite = values[numpy.isfinite(values)]
        low, high = (numpy.percentile(finite, (2, 98)) if finite.size else (0.0, 1.0))
        scaled = numpy.clip((values - low) / ((high - low) or 1.0), 0, 1) * 255
        out[..., band] = numpy.nan_to_num(scaled).astype("uint8")
    if bands.shape[-1] == 1:
        out[..., 1] = out[..., 2] = out[..., 0]
    return out, {"kind": "affine", "crs": "EPSG:%d" % epsg, "transform": transform}


def _projector(georef: Dict[str, Any], inverse: bool = False):
    """lon/lat -> raster CRS (or back with *inverse*); identity for 4326."""
    crs = georef.get("crs") or "EPSG:4326"
    if georef.get("kind") != "affine" or crs in ("EPSG:4326", "EPSG:4979"):
        return lambda x, y: (x, y)
    from pyproj import Transformer
    transformer = (Transformer.from_crs(crs, "EPSG:4326", always_xy=True) if inverse
                   else Transformer.from_crs("EPSG:4326", crs, always_xy=True))
    return lambda x, y: transformer.transform(x, y)


def to_pixels(georef: Dict[str, Any], width: int, height: int):
    """A function from (lon, lat) to normalized (x, y) on the raster."""
    if georef.get("kind") == "extent":
        x0, y0, x1, y1 = georef["extent"]
        return lambda lon, lat: ((lon - x0) / (x1 - x0), (y1 - lat) / (y1 - y0))
    a, b, c, d, e, f = georef["transform"]
    det = a * e - b * d
    project = _projector(georef)

    def convert(lon, lat):
        x, y = project(lon, lat)
        col = (e * (x - c) - b * (y - f)) / det
        row = (-d * (x - c) + a * (y - f)) / det
        return col / width, row / height
    return convert


def to_lonlat(georef: Dict[str, Any], width: int, height: int):
    """A function from normalized (x, y) on the raster to (lon, lat)."""
    if georef.get("kind") == "extent":
        x0, y0, x1, y1 = georef["extent"]
        return lambda x, y: (x0 + x * (x1 - x0), y1 - y * (y1 - y0))
    a, b, c, d, e, f = georef["transform"]
    project = _projector(georef, inverse=True)

    def convert(x, y):
        col, row = x * width, y * height
        return project(a * col + b * row + c, d * col + e * row + f)
    return convert


def features_to_objects(features: Sequence[Dict[str, Any]], convert) -> List[Dict[str, Any]]:
    """GeoJSON features as image-widget shapes through *convert*; a feature
    entirely off the raster is left out."""
    out = []

    def ring(coords):
        return [dict(zip(("x", "y"), convert(float(c[0]), float(c[1])))) for c in coords]

    def on_raster(points):
        return any(-0.01 <= p["x"] <= 1.01 and -0.01 <= p["y"] <= 1.01 for p in points)

    for feature in features:
        geometry = feature.get("geometry") or {}
        label = (feature.get("properties") or {}).get("label")
        kind, coords = geometry.get("type"), geometry.get("coordinates")
        polygons = ([coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else [])
        for polygon in polygons or []:
            points = ring(polygon[0][:-1] if polygon and polygon[0][0] == polygon[0][-1]
                          else polygon[0])
            if len(points) >= 3 and on_raster(points):
                out.append({"type": "polygon", "label": label, "coordinates": points})
        if kind in ("LineString", "MultiLineString"):
            for line in ([coords] if kind == "LineString" else coords):
                points = ring(line)
                if len(points) >= 2 and on_raster(points):
                    out.append({"type": "polyline", "label": label, "coordinates": points})
        if kind in ("Point", "MultiPoint"):
            for point in ([coords] if kind == "Point" else coords):
                (p,) = ring([point])
                if on_raster([p]):
                    out.append({"type": "landmark", "label": label, "coordinates": p})
    return out


def objects_to_features(objects: Sequence[Dict[str, Any]], convert) -> Dict[str, Any]:
    """Image-widget shapes as a FeatureCollection in EPSG:4326, the geo
    widget's answer, each feature marked as the model's."""
    features = []
    for obj in objects:
        coords = obj.get("coordinates")
        try:
            if obj.get("type") == "bbox":
                x, y = float(coords["x"]), float(coords["y"])
                w, h = float(coords["width"]), float(coords["height"])
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                ring = [list(convert(px, py)) for px, py in corners]
                geometry = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
                tool = "polygon"
            elif obj.get("type") == "polygon":
                ring = [list(convert(float(p["x"]), float(p["y"]))) for p in coords]
                geometry = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
                tool = "polygon"
            elif obj.get("type") == "polyline":
                geometry = {"type": "LineString", "coordinates": [
                    list(convert(float(p["x"]), float(p["y"]))) for p in coords]}
                tool = "line"
            elif obj.get("type") == "landmark":
                geometry = {"type": "Point", "coordinates": list(
                    convert(float(coords["x"]), float(coords["y"])))}
                tool = "point"
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        geometry["coordinates"] = _rounded(geometry["coordinates"])
        properties = {"label": obj.get("label"), "tool": tool, "text": "", "source": "model"}
        if isinstance(obj.get("confidence"), (int, float)):
            properties["confidence"] = obj["confidence"]
        features.append({"type": "Feature", "id": "f%d" % len(features),
                         "geometry": geometry, "properties": properties})
    return {"type": "FeatureCollection", "features": features}


def _rounded(value):
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return round(float(value), 7)


def geo_rasters(rows: Sequence[Dict[str, Any]], media_dir: str, schema_name: str,
                task_dir: str, media_directory: str,
                problems: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Geo rows with their raster written as an image and their features as
    shapes on it. A row whose basemap is not a local raster is left out."""
    from PIL import Image
    from potato.training.dataset import _media_file
    problems = problems if problems is not None else []
    out = []
    for row in rows:
        basemap = row.get("basemap")
        if not basemap:
            problems.append("%s: its map has no raster basemap (a GeoTIFF, or an image "
                            "with an extent) to train on" % row.get("instance_id"))
            continue
        reference = basemap.get("geotiff") or basemap.get("image")
        if reference.startswith(("http://", "https://", "//")):
            problems.append("%s: its basemap %s is remote; training reads local files"
                            % (row.get("instance_id"), reference))
            continue
        source = _media_file(reference, task_dir, media_directory)
        folder = os.path.join(media_dir, "geo")
        os.makedirs(folder, exist_ok=True)
        name = hashlib.sha1(os.path.abspath(source).encode()).hexdigest()[:16] + ".png"
        dest = os.path.join(folder, name)
        try:
            if basemap.get("geotiff"):
                pixels, georef = read_georef(source)
                if not os.path.exists(dest):
                    Image.fromarray(pixels).save(dest)
                height, width = pixels.shape[:2]
            else:
                with Image.open(source) as image:
                    width, height = image.size
                    if not os.path.exists(dest):
                        image.convert("RGB").save(dest)
                georef = {"kind": "extent", "extent": basemap["extent"]}
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: %s" % (row.get("instance_id"), exc))
            continue
        georef.update(width=width, height=height)
        converted = dict(row, media=os.path.join("geo", name), georef=georef)
        converted.pop("basemap", None)
        converted.pop("media_missing", None)
        features = (row.get("targets") or {}).get(schema_name)
        if isinstance(features, list):
            convert = to_pixels(georef, width, height)
            converted["targets"] = dict(row["targets"], **{
                schema_name: features_to_objects(features, convert)})
        out.append(converted)
    return out
