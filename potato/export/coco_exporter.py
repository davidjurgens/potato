"""
COCO JSON Exporter

Exports image annotations to COCO format with images[], annotations[],
and categories[] arrays. Supports bbox, polygon/freeform segmentation.
"""

import json
import os
import logging
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    build_coco_category_map,
    flatten_polygon,
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
    rle_to_coco_rle,
)

logger = logging.getLogger(__name__)


class COCOExporter(BaseExporter):
    format_name = "coco"
    description = "COCO JSON format for object detection and segmentation"
    file_extensions = [".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_image_schema = any(
            s.get("annotation_type") == "image_annotation"
            for s in context.schemas
        )
        if not has_image_schema:
            return False, "No image_annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings = []
        annotation_id_counter = 1

        # Category IDs come from the label config's `label_id` when present, so
        # a file imported from COCO exports with its original (often sparse)
        # IDs intact rather than being densely renumbered.
        category_map, coco_categories = build_coco_category_map(
            context.schemas, context.annotations
        )

        coco_images = []
        coco_annotations = []
        image_id_map = {}  # instance_id -> image_id
        image_id_counter = 1

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            # Assign image ID (deduplicate by instance_id)
            if instance_id not in image_id_map:
                image_id = image_id_counter
                image_id_counter += 1
                image_id_map[instance_id] = image_id

                width, height = get_image_dimensions(item)
                file_name = get_image_filename(item) or instance_id

                coco_images.append({
                    "id": image_id,
                    "file_name": file_name,
                    "width": width,
                    "height": height,
                })
            else:
                image_id = image_id_map[instance_id]

            for schema_name, objects in img_anns:
                for obj in objects:
                    obj_type = obj.get("type", "")
                    label = obj.get("label", "")

                    if label not in category_map:
                        warnings.append(
                            f"Unknown label '{label}' in {instance_id}, skipping"
                        )
                        continue

                    if obj_type == "landmark":
                        warnings.append(
                            f"Landmark annotation in {instance_id} skipped "
                            f"(not standard in COCO detection format)"
                        )
                        continue

                    # Reads the shape the browser actually writes (normalized,
                    # nested under `coordinates`) and returns absolute pixels.
                    canon = normalize_annotation_object(obj, width, height)
                    if canon is None:
                        if obj_type == "mask":
                            warnings.append(f"Empty RLE mask in {instance_id}")
                        else:
                            warnings.append(
                                f"Unusable {obj_type or 'annotation'} in "
                                f"{instance_id}, skipping"
                            )
                        continue
                    warnings.extend(
                        f"{w} ({instance_id})" for w in canon["warnings"]
                    )

                    coco_ann = {
                        "id": annotation_id_counter,
                        "image_id": image_id,
                        "category_id": category_map[label],
                        "iscrowd": canon["iscrowd"],
                        "bbox": canon["bbox"],
                        "area": canon["area"],
                    }
                    annotation_id_counter += 1

                    if obj_type == "bbox":
                        coco_ann["segmentation"] = []

                    elif obj_type in ("polygon", "freeform"):
                        coco_ann["segmentation"] = [
                            flatten_polygon(canon["points"])
                        ]

                    elif obj_type == "mask":
                        rle = canon["rle"]
                        size = rle.get("size", [])
                        mask_h = size[0] if len(size) >= 2 else height
                        mask_w = size[1] if len(size) >= 2 else width
                        coco_ann["segmentation"] = rle_to_coco_rle(
                            rle, mask_w, mask_h
                        )

                    else:
                        warnings.append(
                            f"Unknown annotation type '{obj_type}' in {instance_id}"
                        )
                        continue

                    coco_annotations.append(coco_ann)

        coco_output = {
            "images": coco_images,
            "annotations": coco_annotations,
            "categories": coco_categories,
        }

        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "annotations.json")
        with open(out_file, "w") as f:
            json.dump(coco_output, f, indent=2)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            warnings=warnings,
            stats={
                "num_images": len(coco_images),
                "num_annotations": len(coco_annotations),
                "num_categories": len(coco_categories),
            },
        )
