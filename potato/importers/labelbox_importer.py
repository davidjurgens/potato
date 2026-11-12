"""
Labelbox export importer (NDJSON, and the older JSON array form).

Labelbox v2 exports are **newline-delimited JSON**: one complete record per
line, not a JSON array. That is why the import CLI now falls back to a
line-by-line parse — ``json.load`` on a 40k-row export fails on line 2 with a
message about trailing data, which reads as a corrupt file rather than a
different container.

A record nests the annotations several levels down::

    {"data_row": {"external_id": "img.jpg", "row_data": "https://..."},
     "media_attributes": {"width": 640, "height": 480},
     "projects": {"<project_id>": {"labels": [
         {"annotations": {"objects": [...], "classifications": [...]}}]}}}

Things worth stating because getting them wrong still looks plausible:

* **A bounding box is ``{top, left, height, width}``** — not ``x, y``. The
  names differ from every other format here, and reading ``top`` as ``x``
  transposes every box, which on roughly square images looks like a
  registration error rather than a parsing bug.
* **Masks are URLs, not pixels.** Labelbox stores each segmentation mask as a
  separate authenticated PNG. Fetching them would mean network access, an API
  key, and an unbounded download during what looks like a local file
  conversion, so the URL is preserved on the object and the import reports how
  many masks need a separate fetch. An honest gap beats a silent one.
* **The label is ``name``**, and the same export can carry several projects;
  all of them are read, with the project id kept on each object so a
  multi-project export does not silently merge into one flat set.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import FALLBACK_SIZE, apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Labelbox's annotation_kind values, mapped to our client types.
KIND_TO_TYPE = {
    "ImageBoundingBox": "bbox",
    "ImagePolygon": "polygon",
    "ImagePolyline": "polyline",
    "ImagePoint": "landmark",
    "ImageSegmentationMask": "mask",
}


class LabelboxImporter(BaseAnnotationImporter):
    format_name = "labelbox"
    description = "Labelbox export (NDJSON)"
    file_extensions = [".ndjson", ".jsonl", ".json"]

    def detect(self, data: Any) -> bool:
        records = data if isinstance(data, list) else [data]
        for record in records[:5]:
            if not isinstance(record, dict):
                continue
            if "data_row" in record and "projects" in record:
                return True
            # v1 export: {"External ID": ..., "Label": {"objects": [...]}}
            if "External ID" in record and isinstance(record.get("Label"), dict):
                return True
        return False

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        records = data if isinstance(data, list) else [data]
        if not self.detect(records):
            raise ValueError(
                "Not a Labelbox export: expected records with data_row and "
                "projects (v2), or External ID and Label (v1).")

        result = ImportResult()
        labels: Dict[str, dict] = {}
        tools: set = set()
        mask_urls = 0
        unmeasured: List[str] = []

        for record in records:
            if not isinstance(record, dict):
                continue
            parsed = self._image(record, options, labels, tools,
                                 result.warnings)
            if parsed is None:
                continue
            image, needs_fetch, measured = parsed
            mask_urls += needs_fetch
            if not measured:
                unmeasured.append(image.file_name)
            result.images.append(image)

        if mask_urls:
            result.warnings.append(
                f"{mask_urls} segmentation mask(s) are stored by Labelbox as "
                f"separate authenticated PNG URLs, not as pixels in the export. "
                f"Their URLs were preserved on each object's attributes, but "
                f"the pixels were NOT downloaded — that needs your API key and "
                f"an unbounded fetch. Their URLs are on each item under "
                f"labelbox_mask_urls; download them, then import the PNGs with "
                f"--input-format davis.")
        if unmeasured:
            shown = ", ".join(unmeasured[:3])
            more = f" (+{len(unmeasured) - 3} more)" if len(unmeasured) > 3 else ""
            result.warnings.append(
                f"{len(unmeasured)} record(s) carry no media_attributes — "
                f"{shown}{more}. Labelbox geometry is absolute pixels, so those "
                f"were normalized against an assumed "
                f"{FALLBACK_SIZE[0]}x{FALLBACK_SIZE[1]} and will be misplaced. "
                f"Re-export with media attributes, or pass --image-dir.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize()
        return result

    # ------------------------------------------------------------------

    def _image(self, record, options, labels, tools, warnings):
        data_row = record.get("data_row") or {}
        file_name = str(
            data_row.get("external_id")
            or record.get("External ID")
            or data_row.get("id")
            or record.get("ID")
            or "").strip()
        if not file_name:
            return None

        media = record.get("media_attributes") or {}
        measured = bool(media.get("width") and media.get("height"))
        width = int(media.get("width") or FALLBACK_SIZE[0])
        height = int(media.get("height") or FALLBACK_SIZE[1])

        objects: List[dict] = []
        mask_urls = 0
        pending_masks: List[dict] = []
        for project_id, raw in self._annotation_sets(record):
            for entry in raw:
                obj, is_mask_url = self._object(
                    entry, width, height, file_name, warnings)
                if is_mask_url:
                    mask_urls += 1
                    mask = entry.get("mask") or {}
                    pending_masks.append({
                        "label": str(entry.get("name") or "").strip(),
                        "url": mask.get("url") or mask.get("instanceURI") or "",
                    })
                if obj is None:
                    continue
                if project_id:
                    obj.setdefault("attributes", {})["labelbox_project"] = project_id
                objects.append(obj)
                labels.setdefault(obj["label"], {"name": obj["label"]})
                tools.add(obj["type"])

        row_data = data_row.get("row_data") or record.get("Labeled Data") or ""
        # A row_data URL is already fetchable; only a bare filename needs the
        # prefix joined onto it.
        image_url = (row_data if str(row_data).startswith(("http://", "https://"))
                     else apply_url_prefix(file_name, options))

        extra = {"image_url": image_url}
        if pending_masks:
            # Kept on the item so the pointers survive the conversion without
            # masquerading as annotations.
            extra["labelbox_mask_urls"] = pending_masks

        image = ImportedImage(
            instance_id=safe_instance_id(data_row.get("id") or file_name),
            file_name=file_name,
            width=width,
            height=height,
            objects=objects,
            extra=extra,
        )
        return image, mask_urls, measured

    @staticmethod
    def _annotation_sets(record):
        """Every (project_id, objects) pair, across v2 projects and v1 Label."""
        out = []
        projects = record.get("projects")
        if isinstance(projects, dict):
            for project_id, project in projects.items():
                for label in (project.get("labels") or []):
                    annotations = (label or {}).get("annotations") or {}
                    objects = annotations.get("objects") or []
                    if objects:
                        out.append((project_id, objects))
        legacy = record.get("Label")
        if isinstance(legacy, dict) and legacy.get("objects"):
            out.append(("", legacy["objects"]))
        return out

    def _object(self, entry, width, height, file_name, warnings):
        if not isinstance(entry, dict):
            return None, False

        label = str(entry.get("name") or entry.get("value")
                    or entry.get("title") or "").strip()
        if not label:
            return None, False

        kind = entry.get("annotation_kind") or ""
        obj_type = KIND_TO_TYPE.get(kind) or self._infer_type(entry)

        if obj_type == "bbox":
            box = entry.get("bounding_box") or entry.get("bbox") or {}
            try:
                # top/left, NOT x/y.
                left = float(box.get("left", 0) or 0)
                top = float(box.get("top", 0) or 0)
                w = float(box.get("width", 0) or 0)
                h = float(box.get("height", 0) or 0)
            except (TypeError, ValueError):
                return None, False
            return to_client_object("bbox", label, img_w=width, img_h=height,
                                    bbox=[left, top, w, h]), False

        if obj_type in ("polygon", "polyline"):
            raw = entry.get("polygon") or entry.get("line") or []
            points = [[float(p["x"]), float(p["y"])] for p in raw
                      if isinstance(p, dict) and "x" in p and "y" in p]
            if len(points) < 2:
                return None, False
            return to_client_object(obj_type, label, img_w=width,
                                    img_h=height, points=points), False

        if obj_type == "landmark":
            point = entry.get("point") or {}
            if "x" not in point or "y" not in point:
                return None, False
            return to_client_object(
                "landmark", label, img_w=width, img_h=height,
                points=[[float(point["x"]), float(point["y"])]]), False

        if obj_type == "mask":
            # No pixels in the export, so there is no annotation to make. The
            # URL is carried on the ITEM (see _image) rather than emitted as an
            # object: an object of an invented type would not render, and an
            # empty mask would export as a real, wrong annotation.
            return None, True

        warnings.append(
            f"Unsupported Labelbox annotation kind '{kind}' in {file_name}.")
        return None, False

    @staticmethod
    def _infer_type(entry) -> str:
        """v1 exports carry no annotation_kind; the key present is the type."""
        for key, obj_type in (("bbox", "bbox"), ("bounding_box", "bbox"),
                              ("polygon", "polygon"), ("line", "polyline"),
                              ("point", "landmark"), ("mask", "mask"),
                              ("instanceURI", "mask")):
            if key in entry:
                return obj_type
        return ""
