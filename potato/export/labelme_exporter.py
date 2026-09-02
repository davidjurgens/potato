"""
LabelMe JSON exporter — the other half of the LabelMe round trip.

One ``.json`` per image, matching what the LabelMe desktop tool writes::

    {"version": "5.2.1", "flags": {}, "imagePath": "img.jpg",
     "imageData": null, "imageWidth": 640, "imageHeight": 480,
     "shapes": [{"label": "cat", "shape_type": "rectangle",
                 "points": [[x0, y0], [x1, y1]], "group_id": null,
                 "flags": {}}]}

Notes that matter for the file actually opening in LabelMe:

* ``imageData`` is written as ``null``, not omitted and not filled. LabelMe
  accepts null and loads the image from ``imagePath``; inlining base64 would
  multiply the export by the size of the corpus.
* A ``rectangle`` is **two opposite corners**, not four, and a ``circle`` is a
  centre plus a rim point — so an ellipse only round-trips when it is circular.
  A non-circular one is written as its polygon approximation and reported,
  rather than being silently squashed to a circle.
* ``group_id`` carries our instance index, which is what LabelMe uses to mark
  several shapes as parts of one object.
"""

import json
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

#: The schema version LabelMe writes; recorded so the files are recognisable.
LABELME_VERSION = "5.2.1"

#: Below this, an ellipse's radii are equal enough to be a circle.
CIRCLE_TOLERANCE = 0.01


class LabelMeExporter(BaseExporter):
    format_name = "labelme"
    description = "LabelMe JSON (one .json per image)"
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

        by_image = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        num_objects = 0
        for instance_id, objects in sorted(by_image.items()):
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(item)
            file_name = os.path.basename(get_image_filename(item) or instance_id)

            shapes = []
            for obj in objects:
                shape = self._shape(obj, width, height, instance_id, warnings)
                if shape is not None:
                    shapes.append(shape)

            doc = {
                "version": LABELME_VERSION,
                "flags": {},
                "shapes": shapes,
                "imagePath": file_name,
                # null, not omitted: LabelMe accepts it and loads from
                # imagePath. Inlining base64 would multiply the export by the
                # size of the corpus.
                "imageData": None,
                "imageHeight": height,
                "imageWidth": width,
            }

            stem = os.path.splitext(file_name)[0] or instance_id
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
            out_file = os.path.join(output_path, f"{safe}.json")
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
            files_written.append(out_file)
            num_objects += len(shapes)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_objects},
        )

    def _shape(self, obj, width, height, instance_id, warnings):
        obj_type = obj.get("type", "")
        label = obj.get("label", "")

        if obj_type == "mask":
            warnings.append(
                f"Mask in {instance_id} skipped: LabelMe stores regions as "
                f"outlines, not pixels. Export to COCO to keep pixel masks.")
            return None

        canon = normalize_annotation_object(obj, width, height)
        if canon is None:
            warnings.append(f"Unusable {obj_type or 'annotation'} in {instance_id}")
            return None
        warnings.extend(f"{w} ({instance_id})" for w in canon["warnings"])

        shape_type, points = self._geometry(
            obj_type, canon, instance_id, warnings)
        if shape_type is None:
            return None

        shape = {
            "label": label,
            "points": [[round(x, 2), round(y, 2)] for x, y in points],
            "group_id": obj.get("instance"),
            "description": "",
            "shape_type": shape_type,
            "flags": {},
        }
        return shape

    def _geometry(self, obj_type, canon, instance_id, warnings):
        if obj_type == "bbox":
            x, y, w, h = canon["bbox"]
            # Two OPPOSITE corners, not four.
            return "rectangle", [[x, y], [x + w, y + h]]

        if obj_type == "ellipse":
            e = canon["ellipse"]
            if abs(e["rx"] - e["ry"]) <= CIRCLE_TOLERANCE * max(e["rx"], e["ry"]):
                # Centre plus a point on the rim.
                return "circle", [[e["cx"], e["cy"]], [e["cx"] + e["rx"], e["cy"]]]
            # LabelMe has no non-circular ellipse. Writing it as a circle would
            # change the shape silently; the polygon approximation is honest and
            # visually identical.
            warnings.append(
                f"Non-circular ellipse in {instance_id} exported as a polygon: "
                f"LabelMe's circle type has a single radius.")
            return "polygon", canon["points"]

        if obj_type == "polyline":
            return "linestrip", canon["points"]

        if obj_type == "landmark":
            return "point", canon["points"][:1]

        if obj_type == "keypoint_set":
            visible = [p for p, v in zip(canon["points"],
                                         canon.get("visibility") or [])
                       if v]
            if not visible:
                warnings.append(
                    f"Keypoint set in {instance_id} has no labelled points")
                return None, []
            # LabelMe has no ordered skeleton type, so the ordering is lost.
            warnings.append(
                f"Keypoint set in {instance_id} exported as loose points: "
                f"LabelMe has no ordered skeleton type, so joint identity "
                f"(which point is which) is not preserved.")
            return "points", visible

        if obj_type in ("polygon", "freeform"):
            return "polygon", canon["points"]

        warnings.append(f"Unknown type '{obj_type}' in {instance_id}")
        return None, []
