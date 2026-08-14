"""
V7 Darwin JSON v2 exporter — closing the Darwin round trip.

One ``.json`` per item, mirroring what the Darwin importer reads::

    {"version": "2.0",
     "schema_ref": "https://darwin-public.s3.../2.0/schema.json",
     "item": {"name": "img.jpg", "path": "/",
              "slots": [{"type": "image", "slot_name": "0",
                         "width": 640, "height": 480}]},
     "annotations": [{"id": "...", "name": "car",
                      "bounding_box": {"x": 10, "y": 20, "w": 90, "h": 180}}]}

Two structural details the importer's docstring already calls out, restated
here because writing them wrongly is easy:

* **The present key IS the type.** Darwin annotations carry no ``type`` field,
  so an object must emit exactly one shape key. Emitting two (say a
  ``bounding_box`` alongside a ``polygon`` for convenience) makes the file
  ambiguous to Darwin's own reader.
* **Dimensions live in ``item.slots``**, not at the top level.

Masks are Darwin's ``raster_layer``, a dense encoding tied to V7's own layer
model that is not documented well enough to synthesize safely. Rather than
write a plausible guess into a file someone will upload to a paid platform,
masks are traced to polygons and the loss is reported — with COCO named as the
lossless alternative.

Annotation ids are content-derived (a hash of the item, label and geometry)
rather than random, so re-exporting an unchanged project produces byte-identical
files and a diff shows only real changes.
"""

import hashlib
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

DARWIN_VERSION = "2.0"
SCHEMA_REF = ("https://darwin-public.s3.eu-west-1.amazonaws.com/darwin_json/"
              "2.0/schema.json")


class DarwinExporter(BaseExporter):
    format_name = "darwin"
    description = "V7 Darwin JSON v2 (one .json per item)"
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
            width, height = get_image_dimensions(item)
            file_name = os.path.basename(
                get_image_filename(item) or instance_id)

            annotations = []
            for obj in objects:
                entry, was_traced = self._annotation(
                    obj, width, height, file_name, warnings, unsupported)
                if entry is None:
                    continue
                traced_masks += int(was_traced)
                annotations.append(entry)

            doc = {
                "version": DARWIN_VERSION,
                "schema_ref": SCHEMA_REF,
                "item": {
                    "name": file_name,
                    "path": "/",
                    "slots": [{
                        "type": "image",
                        "slot_name": "0",
                        "source_files": [{"file_name": file_name}],
                        "width": width,
                        "height": height,
                    }],
                },
                "annotations": annotations,
            }

            stem = os.path.splitext(file_name)[0] or instance_id
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
            out_file = os.path.join(output_path, f"{safe}.json")
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
            files_written.append(out_file)
            num_objects += len(annotations)

        if traced_masks:
            warnings.append(
                f"{traced_masks} mask(s) were traced to polygons. Darwin stores "
                f"masks as raster_layer, a dense encoding tied to V7's layer "
                f"model; writing an untested approximation of it into a file "
                f"you would upload is worse than the loss. Holes are dropped "
                f"and the outline will not re-rasterize exactly — export to "
                f"COCO to keep pixel masks.")
        for obj_type, count in sorted(unsupported.items()):
            warnings.append(
                f"{count} {obj_type} annotation(s) were not written: Darwin "
                f"JSON has no equivalent shape.")

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_objects},
        )

    # ------------------------------------------------------------------

    def _annotation(self, obj, width, height, file_name, warnings, unsupported):
        obj_type = obj.get("type", "")
        label = obj.get("label", "")
        traced = False

        shape = None
        if obj_type == "bbox":
            canon = normalize_annotation_object(obj, width, height)
            if canon is None:
                return None, False
            x, y, w, h = canon["bbox"]
            # Origin plus size, like COCO -- unlike CVAT and VOC.
            shape = {"bounding_box": {"x": round(x, 2), "y": round(y, 2),
                                      "w": round(w, 2), "h": round(h, 2)}}

        elif obj_type == "ellipse":
            canon = normalize_annotation_object(obj, width, height)
            if canon is None:
                return None, False
            e = canon["ellipse"]
            shape = {"ellipse": {
                "center": {"x": round(e["cx"], 2), "y": round(e["cy"], 2)},
                "radius": {"x": round(e["rx"], 2), "y": round(e["ry"], 2)},
                "angle": round(e.get("angle", 0.0), 4),
            }}

        elif obj_type == "landmark":
            canon = normalize_annotation_object(obj, width, height)
            if canon is None or not canon.get("points"):
                return None, False
            px, py = canon["points"][0]
            shape = {"keypoint": {"x": round(px, 2), "y": round(py, 2)}}

        elif obj_type == "polyline":
            canon = normalize_annotation_object(obj, width, height)
            if canon is None or len(canon.get("points") or []) < 2:
                return None, False
            shape = {"line": {"path": [{"x": round(p[0], 2), "y": round(p[1], 2)}
                                       for p in canon["points"]]}}

        elif obj_type in ("polygon", "freeform"):
            canon = normalize_annotation_object(obj, width, height)
            if canon is None or len(canon.get("points") or []) < 3:
                return None, False
            shape = {"polygon": {"paths": [
                [{"x": round(p[0], 2), "y": round(p[1], 2)}
                 for p in canon["points"]]]}}

        elif obj_type == "mask":
            rings = rle_to_polygons(obj.get("rle") or {}, width, height)
            if not rings:
                return None, False
            traced = True
            shape = {"polygon": {"paths": [
                [{"x": round(p[0], 2), "y": round(p[1], 2)} for p in ring]
                for ring in rings if len(ring) >= 3]}}
            if not shape["polygon"]["paths"]:
                return None, False

        else:
            unsupported[obj_type or "unknown"] = (
                unsupported.get(obj_type or "unknown", 0) + 1)
            return None, False

        entry = {
            # Content-derived so an unchanged project re-exports byte-identically
            # and a diff shows only real changes.
            "id": self._stable_id(file_name, label, shape),
            "name": label,
            **shape,
        }
        attributes = obj.get("attributes") or {}
        if attributes:
            entry["properties"] = attributes
        return entry, traced

    @staticmethod
    def _stable_id(file_name, label, shape) -> str:
        payload = json.dumps([file_name, label, shape], sort_keys=True)
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        # Formatted as a UUID, which is what Darwin's ids look like.
        return (f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-"
                f"{digest[16:20]}-{digest[20:32]}")
