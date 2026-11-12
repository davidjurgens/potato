"""
Microscopy Exporter

For ``microscopy`` schemes. Writes:

    microscopy_rois.geojson   every region of interest as a GeoJSON Feature in
                              full-resolution pixel coordinates (x right, y
                              down), with QuPath-style ``objectType`` and
                              ``classification`` properties plus ``item_id``,
                              ``user_id``, ``schema``, ``roi_type``, ``z``
                              and ``t``. Rectangles and polygons are Polygons
                              (closed rings), points are Points.
    microscopy_cells.csv      one row per classified cell: user, item,
                              schema, label image, label id, class, and the
                              z / t it was classified on
    ome_zarr/<item>.ome.zarr/labels/<schema>__<user>/
                              a class label image per annotator and item: the
                              item's label image with each cell id replaced
                              by its class number (1 = the first of
                              ``cell_labels``, 0 = unclassified), with
                              ``image-label`` colours and a ``properties``
                              list naming each class. Written as OME-Zarr 0.5
                              (Zarr v3) next to an OME-Zarr 0.5 source, and as
                              0.4 (Zarr v2) otherwise; copy the
                              ``labels/<name>`` group into the source image to
                              open it there. Needs zarr-python and the source
                              image; skipped with a warning without them, or
                              with ``--option label_arrays=false``.

GeoJSON is not georeferenced here: the coordinates are image pixels, which is
the convention QuPath uses for its GeoJSON import and export.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult


def _slug(text: Any) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return s[:80] or "x"


def _rgb(hex_colour: str) -> List[int]:
    h = str(hex_colour or "").lstrip("#")
    try:
        return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
    except ValueError:
        return [128, 128, 128]


def roi_geometry(roi: Dict[str, Any], width: float, height: float) -> Optional[Dict[str, Any]]:
    """A stored ROI (fractions of the image) as a GeoJSON geometry in pixels."""
    c = roi.get("coordinates")
    kind = roi.get("type")
    try:
        if kind == "bbox":
            x0, y0 = float(c["x"]) * width, float(c["y"]) * height
            x1, y1 = x0 + float(c["width"]) * width, y0 + float(c["height"]) * height
            ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
            return {"type": "Polygon", "coordinates": [[[round(x, 3), round(y, 3)] for x, y in ring]]}
        if kind == "polygon":
            ring = [[float(p["x"]) * width, float(p["y"]) * height] for p in c]
            if len(ring) < 3:
                return None
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            return {"type": "Polygon", "coordinates": [[[round(x, 3), round(y, 3)] for x, y in ring]]}
        if kind == "landmark":
            return {"type": "Point", "coordinates": [round(float(c["x"]) * width, 3),
                                                     round(float(c["y"]) * height, 3)]}
    except (KeyError, TypeError, ValueError):
        return None
    return None


class MicroscopyExporter(BaseExporter):
    format_name = "microscopy"
    description = ("Microscopy: ROIs as GeoJSON (pixel coordinates), cell classes as CSV, "
                   "class label images as OME-Zarr")
    file_extensions = [".geojson", ".csv", ".zarr"]

    def _schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if isinstance(s, dict) and s.get("annotation_type") == "microscopy"}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No microscopy scheme in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def _answers(self, context: ExportContext, schemes: Dict[str, dict]):
        from potato.science.microscopy import decode_answer

        for ann in context.annotations or []:
            labels = ann.get("labels") or {}
            for name in schemes:
                if name not in labels:
                    continue
                answer = decode_answer(labels[name])
                if answer:
                    yield str(ann.get("user_id", "")), str(ann.get("instance_id", "")), name, answer

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.server_utils.schemas.microscopy import _labels

        options = options or {}
        os.makedirs(output_path, exist_ok=True)
        schemes = self._schemes(context)
        warnings: List[str] = []
        features: List[Dict[str, Any]] = []
        cell_rows: List[Dict[str, Any]] = []
        # (item, scheme) -> {user: {label_id: class name}} and the label image name
        assignments: Dict[Tuple[str, str], Dict[str, Dict[int, str]]] = defaultdict(dict)
        label_names: Dict[Tuple[str, str], str] = {}

        for uid, iid, name, answer in self._answers(context, schemes):
            scheme = schemes[name]
            colours = {l["name"]: l["color"] for l in _labels(scheme.get("labels"))}
            size = answer.get("image") or {}
            width, height = size.get("width"), size.get("height")
            for index, roi in enumerate(answer.get("rois") or []):
                if not (isinstance(width, (int, float)) and isinstance(height, (int, float))):
                    warnings.append(f"{iid}/{uid}: the answer has no image size, so its ROIs "
                                    "could not be converted to pixels")
                    break
                geometry = roi_geometry(roi, float(width), float(height))
                if geometry is None:
                    warnings.append(f"{iid}/{uid}: ROI {index + 1} ({roi.get('type')}) is "
                                    "malformed and was skipped")
                    continue
                label = str(roi.get("label") or "")
                features.append({"type": "Feature", "geometry": geometry, "properties": {
                    "objectType": "annotation",
                    "classification": {"name": label,
                                       "color": _rgb(roi.get("color") or colours.get(label, ""))},
                    "item_id": iid, "user_id": uid, "schema": name,
                    "roi_type": roi.get("type"), "z": int(roi.get("z") or 0),
                    "t": int(roi.get("t") or 0)}})
            cells = {}
            for cell in answer.get("cells") or []:
                try:
                    label_id = int(cell["label_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                cells[label_id] = str(cell.get("class") or "")
                cell_rows.append({"user_id": uid, "instance_id": iid, "schema": name,
                                  "label_image": answer.get("label_image") or "",
                                  "label_id": label_id, "class": cells[label_id],
                                  "z": int(cell.get("z") or 0), "t": int(cell.get("t") or 0)})
            if cells:
                assignments[(iid, name)][uid] = cells
                label_names[(iid, name)] = answer.get("label_image") or ""

        files: List[str] = []
        geo_path = os.path.join(output_path, "microscopy_rois.geojson")
        with open(geo_path, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f, indent=1)
        files.append(geo_path)

        cells_path = os.path.join(output_path, "microscopy_cells.csv")
        columns = ["user_id", "instance_id", "schema", "label_image", "label_id", "class", "z", "t"]
        with open(cells_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in sorted(cell_rows, key=lambda r: (r["instance_id"], r["schema"],
                                                        r["user_id"], r["label_id"])):
                writer.writerow(row)
        files.append(cells_path)

        label_arrays = str(options.get("label_arrays", "true")).lower() not in ("false", "0", "no")
        stores = 0
        if label_arrays and assignments:
            stores = self._write_label_arrays(context, schemes, assignments, label_names,
                                              output_path, options, files, warnings)

        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"rois": len(features), "cells": len(cell_rows),
                                   "label_stores": stores})

    def _write_label_arrays(self, context, schemes, assignments, label_names, output_path,
                            options, files, warnings) -> int:
        from potato.science.converters.ome import (
            OmeError, open_ome, open_zarr_for_writing, write_labels_group, zarr_format_of)
        from potato.science.microscopy import class_volume
        from potato.science.microscopy_routes import resolve_item_path
        from potato.server_utils.schemas.microscopy import _labels

        try:
            import zarr  # noqa: F401
        except ImportError:
            warnings.append("OME-Zarr label arrays were not written: zarr-python is not installed "
                            "(pip install 'potato-annotation[microscopy]').")
            return 0

        by_item: Dict[str, List[Tuple[str, Dict[str, Dict[int, str]]]]] = defaultdict(list)
        for (iid, name), users in assignments.items():
            by_item[iid].append((name, users))

        written = 0
        for iid, entries in sorted(by_item.items()):
            item = context.items.get(iid) if context.items else None
            if not isinstance(item, dict):
                warnings.append(f"{iid}: not in the data, so its label arrays were skipped")
                continue
            arrays: Dict[str, Any] = {}
            colors: Dict[str, Dict[int, str]] = {}
            properties: Dict[str, List[Dict[str, Any]]] = {}
            scale: Dict[str, float] = {}
            zarr_format = 2
            label_axes = None
            for name, users in entries:
                scheme = schemes[name]
                source = resolve_item_path(context.config, item.get(scheme.get("image_key", "image")))
                labels_ref = item.get(scheme["labels_key"]) if scheme.get("labels_key") else None
                label_path = resolve_item_path(context.config, labels_ref) if labels_ref else None
                if source is None or (labels_ref and label_path is None):
                    warnings.append(f"{iid}: the image for {name} was not found under the media "
                                    "directory, so its label arrays were skipped")
                    continue
                try:
                    image = open_ome(source, label_path=label_path,
                                     max_pixels=int(scheme.get("max_pixels") or 64_000_000))
                except OmeError as exc:
                    warnings.append(f"{iid}: {exc}")
                    continue
                if os.path.isdir(source):
                    zarr_format = zarr_format_of(source)
                classes = _labels(scheme.get("cell_labels") or scheme.get("labels"))
                values = {c["name"]: i + 1 for i, c in enumerate(classes)}
                label_name = label_names.get((iid, name)) or (image.labels[0] if image.labels else "")
                for axis in "zyx":
                    if axis in image.physical:
                        scale[axis] = float(image.physical[axis]["size"])
                for uid, cells in sorted(users.items()):
                    unknown = sorted({c for c in cells.values() if c not in values})
                    if unknown:
                        warnings.append(f"{iid}/{uid}: classes not in the scheme were left "
                                        f"unclassified in the label array: {', '.join(unknown)}")
                    mapping = {cid: values[c] for cid, c in cells.items() if c in values}
                    try:
                        volume, axes = class_volume(image, label_name, mapping)
                    except OmeError as exc:
                        warnings.append(f"{iid}/{uid}: {exc}")
                        continue
                    if label_axes not in (None, axes):
                        warnings.append(f"{iid}: label images with different axes; skipped {name}")
                        continue
                    label_axes = axes
                    key = f"{_slug(name)}__{_slug(uid)}"
                    arrays[key] = volume
                    colors[key] = {i + 1: c["color"].lstrip("#") for i, c in enumerate(classes)}
                    properties[key] = [{"label-value": i + 1, "class": c["name"]}
                                       for i, c in enumerate(classes)]
            if not arrays:
                continue
            zarr_format = int(options.get("zarr_format") or zarr_format)
            store = os.path.join(output_path, "ome_zarr", f"{_slug(iid)}.ome.zarr")
            os.makedirs(os.path.dirname(store), exist_ok=True)
            root = open_zarr_for_writing(store, zarr_format)
            write_labels_group(root, arrays, label_axes, zarr_format, colors=colors,
                               properties=properties, scale=scale)
            files.append(store)
            written += 1
        return written
