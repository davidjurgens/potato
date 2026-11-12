"""
Pathology region files: QuPath GeoJSON and ASAP XML, read and written.

Both store regions in the slide's full-resolution pixels (level 0), origin at
the top-left corner, y down. Potato stores image annotations as fractions of
the image (``cv_utils.to_client_object`` / ``normalize_annotation_object``),
so reading and writing need the slide's level-0 width and height and nothing
else: there is no scaling by magnification or microns.

QuPath GeoJSON (QuPath 0.2 to 0.5): a FeatureCollection, or a bare list of
Features. Each feature's ``properties`` may carry ``objectType``
(``annotation``, ``detection``, ``cell``, ...), ``classification``
(``{"name", "color": [r, g, b]}``, or QuPath 0.2's ``colorRGB`` packed int),
``name`` and ``isLocked``. Geometry is Polygon, MultiPolygon, LineString,
MultiLineString, Point, MultiPoint or a GeometryCollection of those.

ASAP XML (the format the CAMELYON challenges use)::

    <ASAP_Annotations>
      <Annotations>
        <Annotation Name="Annotation 0" Type="Polygon" PartOfGroup="tumor" Color="#F4FA58">
          <Coordinates><Coordinate Order="0" X="1024.5" Y="2048"/>...</Coordinates>
        </Annotation>
      </Annotations>
      <AnnotationGroups>
        <Group Name="tumor" PartOfGroup="None" Color="#64FE2E"><Attributes/></Group>
      </AnnotationGroups>
    </ASAP_Annotations>

This module is written from the file formats; it shares no code with QuPath
or ASAP.

Mapping, both ways:

============  =====================  ======================
Potato        QuPath geometry        ASAP Type
============  =====================  ======================
bbox          Polygon (4 corners)    Rectangle
polygon       Polygon                Polygon
freeform      Polygon                Polygon
ellipse       Polygon (36 points)    Polygon
polyline      LineString             Measurement (2 points only)
landmark      Point                  Dot
keypoint_set  MultiPoint             PointSet
============  =====================  ======================

On import an axis-aligned four-corner QuPath polygon becomes a bbox (QuPath's
rectangles are written that way), a MultiPolygon becomes one polygon per
part, polygon holes are dropped with a warning, and an ASAP Spline is read as
the polygon through its control points. Masks are not written: a pixel mask
at slide resolution is not something either tool reads from these files.

A region with no class is labelled ``Unclassified`` on import, and a region
labelled ``Unclassified`` is written with no QuPath classification and with
ASAP's ``PartOfGroup="None"``.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # untrusted XML: refuse entity expansion when defusedxml is installed
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - expat >= 2.4.1 limits expansion itself
    from xml.etree.ElementTree import fromstring as _xml_fromstring

UNCLASSIFIED = "Unclassified"
#: A region file larger than this is refused rather than parsed into memory.
MAX_FILE_BYTES = 256 * 1024 * 1024
#: Regions read per slide. QuPath cell detections can number in the
#: millions; the annotation canvas cannot show that many, so the rest are
#: left out with a warning.
MAX_REGIONS = 50_000
DEFAULT_COLOR = "#7f8c8d"
#: Stable ids for exported features: uuid5(namespace, "<item>/<index>").
_ID_NAMESPACE = uuid.UUID("6f0b9c43-2d0e-4e59-9c55-3a1f6c1e2b7d")

QUPATH_OBJECT_TYPES = frozenset({
    "annotation", "detection", "cell", "tile", "tma_core", "root",
})


class RegionFormatError(ValueError):
    """The file is not a region file of the expected kind."""


# -- colours -----------------------------------------------------------------

def hex_to_rgb(color: Any) -> Optional[List[int]]:
    text = str(color or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return None
    try:
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return None


def rgb_to_hex(rgb: Iterable[Any]) -> Optional[str]:
    try:
        r, g, b = (max(0, min(255, int(v))) for v in list(rgb)[:3])
    except (TypeError, ValueError):
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def _qupath_color(classification: Dict[str, Any]) -> Optional[str]:
    color = classification.get("color")
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        return rgb_to_hex(color)
    packed = classification.get("colorRGB")
    if isinstance(packed, int) and not isinstance(packed, bool):
        packed &= 0xFFFFFF       # QuPath 0.2 packs ARGB into a signed int
        return rgb_to_hex(((packed >> 16) & 255, (packed >> 8) & 255, packed & 255))
    return None


# -- slide size ----------------------------------------------------------------

def slide_dimensions(path: Any) -> Optional[Tuple[int, int]]:
    """Level-0 ``(width, height)`` of a slide or image, or None.

    A slide format goes through openslide (the ``wsi`` extra); anything else,
    and a slide when openslide is missing, through Pillow's header read.
    """
    from potato.media import slides
    from potato.media.tiles import TileError
    path = Path(path)
    if not path.is_file():
        return None
    if slides.is_slide(str(path)):
        try:
            spec = slides.describe_slide(str(path))
            return int(spec.width), int(spec.height)
        except TileError:
            pass
    from potato.importers._common import probe_image_size
    size = probe_image_size(path)
    if size and size[0] > 0 and size[1] > 0:
        return int(size[0]), int(size[1])
    return None


# -- shared helpers ---------------------------------------------------------------

def _finite_point(raw: Any) -> Optional[List[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return [x, y]


def _open_ring(points: List[List[float]]) -> List[List[float]]:
    """Drop the closing vertex GeoJSON repeats at the end of a ring."""
    if len(points) >= 2 and points[0] == points[-1]:
        return points[:-1]
    return points


def _axis_aligned_rectangle(points: List[List[float]]) -> Optional[List[float]]:
    """``[x, y, w, h]`` when four points are the corners of an upright box."""
    if len(points) != 4:
        return None
    xs = sorted({p[0] for p in points})
    ys = sorted({p[1] for p in points})
    if len(xs) != 2 or len(ys) != 2:
        return None
    corners = {(p[0], p[1]) for p in points}
    if corners != {(x, y) for x in xs for y in ys}:
        return None
    return [xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]]


class _Reader:
    """Collects objects, labels and warnings while one file is read."""

    def __init__(self, width: int, height: int, fmt: str, where: str):
        self.width, self.height = int(width), int(height)
        self.fmt, self.where = fmt, where
        self.objects: List[dict] = []
        self.labels: Dict[str, Optional[str]] = {}
        self.tools: set = set()
        self.warnings: List[str] = []
        self.counts: Dict[str, int] = {}
        self.outside = 0
        self.truncated = 0

    def warn_once(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def count(self, what: str, n: int = 1) -> None:
        self.counts[what] = self.counts.get(what, 0) + n

    def add(self, obj_type: str, label: str, color: Optional[str], *,
            points: Optional[List[List[float]]] = None,
            bbox: Optional[List[float]] = None,
            attributes: Optional[Dict[str, Any]] = None,
            instance: Optional[int] = None) -> None:
        from potato.export.cv_utils import to_client_object
        if len(self.objects) >= MAX_REGIONS:
            self.truncated += 1
            return
        check = points if points is not None else (
            [[bbox[0], bbox[1]], [bbox[0] + bbox[2], bbox[1] + bbox[3]]] if bbox else [])
        if any(x < 0 or y < 0 or x > self.width or y > self.height for x, y in check):
            self.outside += 1
        tool = obj_type
        obj = to_client_object(obj_type, label, color or "",
                               img_w=self.width, img_h=self.height,
                               bbox=bbox, points=points,
                               provenance={"source": "import", "import_format": self.fmt})
        if obj is None:
            self.count("unusable regions")
            return
        if attributes:
            obj["attributes"] = {k: v for k, v in attributes.items() if v not in (None, "")}
        if instance is not None:
            obj["instance"] = int(instance)
        self.objects.append(obj)
        self.tools.add(tool)
        if label not in self.labels or (color and not self.labels[label]):
            self.labels[label] = color
        self.count("regions")

    def finish(self) -> None:
        if self.outside:
            self.warnings.append(
                f"{self.where}: {self.outside} region(s) reach outside the "
                f"{self.width}x{self.height} slide; kept as they are. If they all do, "
                f"the file belongs to another slide or another magnification level.")
        if self.truncated:
            self.warnings.append(
                f"{self.where}: only the first {MAX_REGIONS} regions were read; "
                f"{self.truncated} more were left out (cell detections? export "
                f"annotations only from QuPath).")


def _read_bytes(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise RegionFormatError(
            f"{path.name} is {size // (1024 * 1024)} MB; region files over "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB are refused")
    return path.read_bytes()


# -- QuPath GeoJSON -------------------------------------------------------------

def qupath_features(doc: Any) -> Optional[List[dict]]:
    """The features of a QuPath GeoJSON document, or None if it is not one.

    Plain GeoJSON (longitude/latitude for maps) has the same structure, so
    at least one feature has to carry a QuPath property: an ``objectType``
    QuPath uses, a ``classification`` or ``isLocked``.
    """
    if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
        features = doc.get("features")
    elif isinstance(doc, dict) and doc.get("type") == "Feature":
        features = [doc]
    elif isinstance(doc, list):
        features = doc
    else:
        return None
    if not isinstance(features, list):
        return None
    features = [f for f in features if isinstance(f, dict) and f.get("type") == "Feature"]
    for feature in features:
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        if (str(props.get("objectType", "")).lower() in QUPATH_OBJECT_TYPES
                or isinstance(props.get("classification"), dict)
                or "isLocked" in props):
            return features
    return None


def read_qupath(doc: Any, width: int, height: int, where: str = "QuPath file") -> _Reader:
    features = qupath_features(doc)
    if features is None:
        raise RegionFormatError(f"{where} is not QuPath GeoJSON (no feature has objectType, "
                                f"classification or isLocked)")
    reader = _Reader(width, height, "qupath_geojson", where)
    for index, feature in enumerate(features):
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        classification = props.get("classification")
        if isinstance(classification, dict) and classification.get("name"):
            label = str(classification["name"])
            color = _qupath_color(classification)
        else:
            label, color = UNCLASSIFIED, None
        object_type = str(props.get("objectType") or props.get("object_type") or "annotation")
        reader.count(f"QuPath {object_type} objects")
        attributes = {"qupath_id": feature.get("id"), "qupath_name": props.get("name"),
                      "qupath_object_type": None if object_type == "annotation" else object_type}
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            reader.count("features with no geometry")
            continue
        _qupath_geometry(reader, geometry, label, color, attributes, index)
    reader.finish()
    return reader


def _qupath_geometry(reader: _Reader, geometry: dict, label: str, color: Optional[str],
                     attributes: Dict[str, Any], index: int, instance: Optional[int] = None) -> None:
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "GeometryCollection":
        for part in geometry.get("geometries") or []:
            if isinstance(part, dict):
                _qupath_geometry(reader, part, label, color, attributes, index, instance=index)
        return
    if kind == "Polygon":
        _qupath_polygon(reader, coords, label, color, attributes, instance)
    elif kind == "MultiPolygon":
        for polygon in coords or []:
            _qupath_polygon(reader, polygon, label, color, attributes, index)
    elif kind in ("LineString", "MultiLineString"):
        lines = [coords] if kind == "LineString" else (coords or [])
        for line in lines:
            points = [p for p in (_finite_point(c) for c in line or []) if p]
            if len(points) < 2:
                reader.count("lines with fewer than two points")
                continue
            reader.add("polyline", label, color, points=points, attributes=attributes,
                       instance=instance if kind == "LineString" else index)
    elif kind in ("Point", "MultiPoint"):
        raw = [coords] if kind == "Point" else (coords or [])
        for c in raw:
            point = _finite_point(c)
            if point is None:
                reader.count("unreadable points")
                continue
            reader.add("landmark", label, color, points=[point], attributes=attributes)
    else:
        reader.count(f"unsupported geometry ({kind})")
        reader.warn_once(f"{reader.where}: {kind} geometry is not read")


def _qupath_polygon(reader: _Reader, rings: Any, label: str, color: Optional[str],
                    attributes: Dict[str, Any], instance: Optional[int]) -> None:
    if not isinstance(rings, list) or not rings:
        reader.count("polygons with no ring")
        return
    outer = _open_ring([p for p in (_finite_point(c) for c in rings[0] or []) if p])
    if len(outer) < 3:
        reader.count("polygons with fewer than three points")
        return
    if len(rings) > 1:
        reader.count("polygon holes dropped", len(rings) - 1)
        reader.warn_once(f"{reader.where}: polygons with holes are read as their outer "
                         f"ring; Potato polygons have no holes")
    box = _axis_aligned_rectangle(outer)
    if box is not None:
        reader.add("bbox", label, color, bbox=box, attributes=attributes, instance=instance)
    else:
        reader.add("polygon", label, color, points=outer, attributes=attributes,
                   instance=instance)


def load_qupath(path: Path, width: int, height: int) -> _Reader:
    try:
        doc = json.loads(_read_bytes(path).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, RegionFormatError):
            raise
        raise RegionFormatError(f"{path.name} is not JSON: {exc}") from exc
    return read_qupath(doc, width, height, where=path.name)


# -- ASAP XML -------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_asap(head: bytes) -> bool:
    return b"<ASAP_Annotations" in head


def _asap_number(text: Any) -> Optional[float]:
    # ASAP builds from some locales write a decimal comma ("1024,5").
    raw = str(text or "").strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_asap(data: bytes, width: int, height: int, where: str = "ASAP file") -> _Reader:
    try:
        root = _xml_fromstring(data)
    except Exception as exc:  # ParseError, or defusedxml's refusals
        raise RegionFormatError(f"{where}: not well-formed XML ({exc})") from exc
    if _local(root.tag) != "ASAP_Annotations":
        raise RegionFormatError(f"{where}: not an ASAP file (root is <{_local(root.tag)}>)")
    reader = _Reader(width, height, "asap_xml", where)
    group_colors: Dict[str, Optional[str]] = {}
    for groups in root:
        if _local(groups.tag) != "AnnotationGroups":
            continue
        for group in groups:
            if _local(group.tag) == "Group" and group.get("Name"):
                group_colors[group.get("Name")] = group.get("Color") or None
    spline_seen = False
    for section in root:
        if _local(section.tag) != "Annotations":
            continue
        for annotation in section:
            if _local(annotation.tag) != "Annotation":
                continue
            group = annotation.get("PartOfGroup") or "None"
            label = UNCLASSIFIED if group == "None" else group
            color = group_colors.get(group) or annotation.get("Color") or None
            kind = (annotation.get("Type") or "").strip()
            reader.count(f"ASAP {kind or 'untyped'} annotations")
            coords = []
            for container in annotation:
                if _local(container.tag) != "Coordinates":
                    continue
                for c in container:
                    if _local(c.tag) != "Coordinate":
                        continue
                    x, y = _asap_number(c.get("X")), _asap_number(c.get("Y"))
                    if x is None or y is None:
                        continue
                    order = _asap_number(c.get("Order"))
                    coords.append((order if order is not None else len(coords), [x, y]))
            points = [p for _o, p in sorted(coords, key=lambda t: t[0])]
            attributes = {"asap_name": annotation.get("Name")}
            if kind in ("Polygon", "Spline"):
                if kind == "Spline" and not spline_seen:
                    spline_seen = True
                    reader.warn_once(f"{where}: Spline annotations are read as the polygon "
                                     f"through their control points")
                points = _open_ring(points)
                if len(points) < 3:
                    reader.count("polygons with fewer than three points")
                    continue
                reader.add("polygon", label, color, points=points, attributes=attributes)
            elif kind == "Rectangle":
                if len(points) < 2:
                    reader.count("rectangles with fewer than two corners")
                    continue
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                reader.add("bbox", label, color,
                           bbox=[min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)],
                           attributes=attributes)
            elif kind in ("Dot", "PointSet"):
                for point in points:
                    reader.add("landmark", label, color, points=[point], attributes=attributes)
            elif kind == "Measurement":
                if len(points) < 2:
                    reader.count("measurements with fewer than two points")
                    continue
                reader.add("polyline", label, color, points=points, attributes=attributes)
            else:
                reader.count(f"unsupported ASAP types ({kind or 'none'})")
                reader.warn_once(f"{where}: ASAP annotation type {kind or '(none)'} is not read")
    reader.finish()
    return reader


def load_asap(path: Path, width: int, height: int) -> _Reader:
    return read_asap(_read_bytes(path), width, height, where=path.name)


# -- writing ----------------------------------------------------------------------

def _round(value: float) -> float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _pt(p) -> List[float]:
    return [_round(p[0]), _round(p[1])]


def canonical_regions(objects: List[dict], width: int, height: int,
                      where: str, warnings: List[str]) -> List[dict]:
    """Stored client objects as ``{type, label, color, points, attributes}`` in pixels.

    ``points`` is the outline (bbox: four corners clockwise from top-left;
    ellipse: its 36-point polygon). Masks and unusable objects are reported
    in ``warnings`` and left out.
    """
    from potato.export.cv_utils import normalize_annotation_object
    out = []
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type", "")
        if kind == "mask":
            _note(warnings, f"{where}: brush masks are not written (QuPath GeoJSON and "
                            f"ASAP XML hold outlines); export them with mask_png or coco")
            continue
        canon = normalize_annotation_object(obj, width, height)
        if canon is None:
            _note(warnings, f"{where}: an unusable {kind or 'annotation'} was left out")
            continue
        warnings.extend(f"{w} ({where})" for w in canon.get("warnings") or [])
        if kind == "bbox":
            x, y, w, h = canon["bbox"]
            points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        elif kind == "keypoint_set":
            points = [p for p, v in zip(canon.get("points") or [], canon.get("visibility") or [])
                      if v]
        else:
            points = canon.get("points") or []
        if not points:
            _note(warnings, f"{where}: a {kind} with no points was left out")
            continue
        out.append({"type": kind, "label": canon.get("label") or UNCLASSIFIED,
                    "color": canon.get("color") or "", "points": points,
                    "attributes": obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}})
    return out


def _note(warnings: List[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def write_qupath(regions: List[dict], label_colors: Dict[str, str], item_key: str,
                 where: str, warnings: List[str]) -> Dict[str, Any]:
    """A QuPath GeoJSON FeatureCollection for ``canonical_regions`` output."""
    features = []
    for index, region in enumerate(regions):
        kind, points = region["type"], region["points"]
        if kind in ("bbox", "polygon", "freeform", "ellipse"):
            if len(points) < 3:
                continue
            ring = [_pt(p) for p in points]
            geometry = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
            if kind == "ellipse":
                _note(warnings, f"{where}: ellipses are written as 36-point polygons; they "
                                f"come back as polygons")
        elif kind == "polyline":
            geometry = {"type": "LineString", "coordinates": [_pt(p) for p in points]}
        elif kind == "landmark":
            geometry = {"type": "Point", "coordinates": _pt(points[0])}
        elif kind == "keypoint_set":
            geometry = {"type": "MultiPoint", "coordinates": [_pt(p) for p in points]}
            _note(warnings, f"{where}: keypoint sets are written as unordered MultiPoints")
        else:
            _note(warnings, f"{where}: {kind} is not written")
            continue
        attributes = region.get("attributes") or {}
        props: Dict[str, Any] = {
            "objectType": attributes.get("qupath_object_type") or "annotation"}
        label = region["label"]
        if label != UNCLASSIFIED:
            rgb = hex_to_rgb(label_colors.get(label) or region.get("color") or DEFAULT_COLOR)
            props["classification"] = {"name": label, "color": rgb or hex_to_rgb(DEFAULT_COLOR)}
        name = attributes.get("qupath_name") or attributes.get("asap_name")
        if name:
            props["name"] = str(name)
        props["isLocked"] = False
        feature_id = attributes.get("qupath_id") or str(
            uuid.uuid5(_ID_NAMESPACE, f"{item_key}/{index}"))
        features.append({"type": "Feature", "id": str(feature_id),
                         "geometry": geometry, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def write_asap(regions: List[dict], label_colors: Dict[str, str],
               where: str, warnings: List[str]) -> str:
    """ASAP XML text for ``canonical_regions`` output."""
    import xml.etree.ElementTree as ET
    root = ET.Element("ASAP_Annotations")
    annotations = ET.SubElement(root, "Annotations")
    groups: Dict[str, str] = {}
    written = 0
    for region in regions:
        kind, points = region["type"], region["points"]
        if kind == "bbox":
            asap_type = "Rectangle"
        elif kind in ("polygon", "freeform", "ellipse"):
            asap_type = "Polygon"
            if kind == "ellipse":
                _note(warnings, f"{where}: ellipses are written as 36-point polygons")
        elif kind == "landmark":
            asap_type, points = "Dot", points[:1]
        elif kind == "keypoint_set":
            asap_type = "PointSet"
        elif kind == "polyline":
            if len(points) != 2:
                _note(warnings, f"{where}: ASAP has no open polyline of more than two "
                                f"points (its Measurement is a single segment); "
                                f"polylines of {len(points)} points were left out")
                continue
            asap_type = "Measurement"
        else:
            _note(warnings, f"{where}: {kind} is not written")
            continue
        label = region["label"]
        color = label_colors.get(label) or region.get("color") or DEFAULT_COLOR
        group = "None" if label == UNCLASSIFIED else label
        if group != "None":
            groups.setdefault(group, color)
        attributes = region.get("attributes") or {}
        name = (attributes.get("asap_name") or attributes.get("qupath_name")
                or f"Annotation {written}")
        element = ET.SubElement(annotations, "Annotation", {
            "Name": str(name), "Type": asap_type, "PartOfGroup": group,
            "Color": rgb_to_hex(hex_to_rgb(color) or hex_to_rgb(DEFAULT_COLOR)).upper()})
        coordinates = ET.SubElement(element, "Coordinates")
        for order, point in enumerate(points):
            x, y = _pt(point)
            ET.SubElement(coordinates, "Coordinate",
                          {"Order": str(order), "X": str(x), "Y": str(y)})
        written += 1
    annotation_groups = ET.SubElement(root, "AnnotationGroups")
    for name, color in groups.items():
        group = ET.SubElement(annotation_groups, "Group", {
            "Name": name, "PartOfGroup": "None",
            "Color": rgb_to_hex(hex_to_rgb(color) or hex_to_rgb(DEFAULT_COLOR)).upper()})
        ET.SubElement(group, "Attributes")
    ET.indent(root)
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
