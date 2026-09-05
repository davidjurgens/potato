"""
Cityscapes polygon exporter — the other half of the Cityscapes round trip.

Writes one ``<stem>_gtFine_polygons.json`` per image::

    {"imgHeight": 1024, "imgWidth": 2048,
     "objects": [{"label": "road", "polygon": [[x, y], ...]}]}

The one thing that must not be lost is **painter's order**. Cityscapes
rasterizes its label images by drawing objects in list order, so a later
polygon occludes an earlier one; the order IS the occlusion. Objects are
therefore emitted sorted by the ``draw_order`` attribute the importer preserved,
with anything lacking one appended in its stored order rather than interleaved
arbitrarily.

Masks are converted to their outline, which is genuinely lossy — a mask with
holes becomes its outer boundary — so it is reported rather than done quietly.
Boxes are written as four-corner polygons, which is exact.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
    rle_to_polygons,
)

logger = logging.getLogger(__name__)

#: The suffix Cityscapes' own tooling looks for.
POLYGON_SUFFIX = "_gtFine_polygons.json"

#: Objects with no recorded draw order sort after those that have one.
NO_ORDER = 10**9


class CityscapesExporter(BaseExporter):
    format_name = "cityscapes"
    description = "Cityscapes polygons (*_gtFine_polygons.json)"
    file_extensions = [".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") == "image_annotation"
                   for s in context.schemas):
            return False, "No image_annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings: List[str] = []
        files_written: List[str] = []
        os.makedirs(output_path, exist_ok=True)

        by_image: Dict[str, list] = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        num_objects = 0
        traced_masks = 0
        unsupported: Dict[str, int] = {}

        for instance_id, objects in sorted(by_image.items()):
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(
                item, config=context.config, annotation=ann)
            file_name = get_image_filename(item) or instance_id
            stem = self._stem(file_name, instance_id)

            # Painter's order: draw_order first, stored order as the tiebreak,
            # so objects that never had one keep their relative positions.
            ordered = sorted(
                enumerate(objects),
                key=lambda pair: (
                    self._draw_order(pair[1]), pair[0]))

            entries = []
            for _index, obj in ordered:
                converted, was_traced = self._polygon(
                    obj, width, height, instance_id, warnings, unsupported)
                if converted is None:
                    continue
                traced_masks += int(was_traced)
                entries.append(converted)

            doc = {
                "imgHeight": height,
                "imgWidth": width,
                "objects": entries,
            }
            out_file = os.path.join(output_path, f"{stem}{POLYGON_SUFFIX}")
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
            files_written.append(out_file)
            num_objects += len(entries)

        if traced_masks:
            warnings.append(
                f"{traced_masks} mask(s) were traced to their outer boundary. "
                f"Cityscapes stores outlines, so a mask with holes loses them "
                f"and the contour will not re-rasterize to the source pixels. "
                f"Export to COCO to keep exact masks.")
        for obj_type, count in sorted(unsupported.items()):
            warnings.append(
                f"{count} {obj_type} annotation(s) were not written: Cityscapes "
                f"stores closed polygons only.")

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_objects},
        )

    @staticmethod
    def _draw_order(obj) -> int:
        try:
            return int((obj.get("attributes") or {})["draw_order"])
        except (KeyError, TypeError, ValueError):
            return NO_ORDER

    @staticmethod
    def _stem(file_name: str, instance_id: str) -> str:
        base = os.path.splitext(os.path.basename(file_name))[0] or instance_id
        # Undo the importer's own suffix so a round trip does not accumulate
        # "_leftImg8bit_leftImg8bit".
        for suffix in ("_leftImg8bit", "_rightImg8bit"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base

    def _polygon(self, obj, width, height, instance_id, warnings, unsupported):
        obj_type = obj.get("type", "")
        label = obj.get("label", "")

        if obj_type == "mask":
            rings = rle_to_polygons(obj.get("rle") or {}, width, height)
            if not rings:
                return None, False
            largest = max(rings, key=len)
            return {"label": label,
                    "polygon": [[round(p[0], 2), round(p[1], 2)]
                                for p in largest]}, True

        if obj_type in ("polygon", "freeform", "bbox", "ellipse"):
            canon = normalize_annotation_object(obj, width, height)
            if canon is None:
                return None, False
            if obj_type == "bbox":
                x, y, w, h = canon["bbox"]
                points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            else:
                points = canon["points"]
            if len(points) < 3:
                return None, False
            return {"label": label,
                    "polygon": [[round(p[0], 2), round(p[1], 2)]
                                for p in points]}, False

        unsupported[obj_type or "unknown"] = (
            unsupported.get(obj_type or "unknown", 0) + 1)
        return None, False
