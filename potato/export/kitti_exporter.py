"""
KITTI 2D label exporter — the other half of the KITTI round trip.

Writes one ``label_2/<stem>.txt`` per image, fifteen space-separated fields::

    type truncated occluded alpha  x1 y1 x2 y2  h w l  x y z  ry

Deliberate choices, each of which would otherwise be a silent lie:

* **Boxes are written as CORNERS**, matching the devkit. Potato stores origin +
  size, so ``x2 = x + w``. A round trip that used origin+size on both sides
  would close cleanly and still produce a file KITTI misreads — which is why
  there is a test asserting the written ``x2`` is a corner, not a width.
* **The 3D fields are written as the devkit's "unset" values** (``-1`` for
  dimensions and ``-1000`` for location, exactly as KITTI's own ``DontCare``
  rows do) unless the object carries real 3D attributes from an earlier import.
  Writing zeros instead would place a zero-sized object at the camera origin,
  which downstream 3D tooling reads as a real detection.
* **Only boxes survive.** KITTI's 2D label format has no polygon, mask, or
  polyline. Those are reported per type rather than dropped quietly.
"""

import logging
import os
from typing import List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
)

logger = logging.getLogger(__name__)

#: The devkit's own sentinel for "no 3D information", as used on DontCare rows.
UNSET_DIMENSION = -1.0
UNSET_LOCATION = -1000.0
UNSET_ANGLE = -10.0

#: Occlusion names written back as the integer codes KITTI defines.
OCCLUSION_CODES = {"fully_visible": 0, "partly_occluded": 1,
                   "largely_occluded": 2, "unknown": 3}


class KITTIExporter(BaseExporter):
    format_name = "kitti"
    description = "KITTI 2D object detection labels (label_2/*.txt)"
    file_extensions = [".txt"]

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

        label_dir = os.path.join(output_path, "label_2")
        os.makedirs(label_dir, exist_ok=True)

        by_image = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        unsupported = {}
        num_objects = 0

        for instance_id, objects in sorted(by_image.items()):
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(
                item, config=context.config, annotation=ann)
            file_name = get_image_filename(item) or instance_id
            stem = os.path.splitext(os.path.basename(file_name))[0] or instance_id

            lines = []
            for obj in objects:
                obj_type = obj.get("type", "")
                if obj_type != "bbox":
                    unsupported[obj_type] = unsupported.get(obj_type, 0) + 1
                    continue
                line = self._line(obj, width, height)
                if line:
                    lines.append(line)

            out_file = os.path.join(label_dir, f"{stem}.txt")
            with open(out_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
                if lines:
                    fh.write("\n")
            files_written.append(out_file)
            num_objects += len(lines)

        for obj_type, count in sorted(unsupported.items()):
            warnings.append(
                f"{count} {obj_type} annotation(s) were not written: KITTI's 2D "
                f"label format holds boxes only. Export to COCO to keep "
                f"{obj_type} geometry.")

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_objects},
        )

    def _line(self, obj, width, height) -> str:
        canon = normalize_annotation_object(obj, width, height)
        if canon is None:
            return ""
        x, y, w, h = canon["bbox"]
        # Corners, not origin+size.
        x1, y1, x2, y2 = x, y, x + w, y + h

        label = (obj.get("label") or "DontCare").replace(" ", "_")
        attrs = obj.get("attributes") or {}

        truncated = self._float(attrs.get("truncated"), 0.0)
        occluded = attrs.get("occluded")
        if isinstance(occluded, str):
            occluded = OCCLUSION_CODES.get(occluded, 3)
        occluded = int(self._float(occluded, 0))
        alpha = self._float(attrs.get("alpha"), UNSET_ANGLE)

        dims = attrs.get("dimensions_hwl") or [UNSET_DIMENSION] * 3
        loc = attrs.get("location_xyz") or [UNSET_LOCATION] * 3
        rotation = self._float(attrs.get("rotation_y"), UNSET_ANGLE)

        fields = [
            label, f"{truncated:.2f}", str(occluded), f"{alpha:.2f}",
            f"{x1:.2f}", f"{y1:.2f}", f"{x2:.2f}", f"{y2:.2f}",
            *[f"{self._float(v, UNSET_DIMENSION):.2f}" for v in dims[:3]],
            *[f"{self._float(v, UNSET_LOCATION):.2f}" for v in loc[:3]],
            f"{rotation:.2f}",
        ]
        return " ".join(fields)

    @staticmethod
    def _float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)
