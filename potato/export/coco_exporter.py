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
    build_category_mapping,
    polygon_to_bbox,
    polygon_area,
    flatten_polygon,
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
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

        category_map = build_category_mapping(context.annotations, context.schemas)
        # COCO uses 1-indexed category IDs
        coco_categories = [
            {"id": idx + 1, "name": name, "supercategory": ""}
            for name, idx in sorted(category_map.items(), key=lambda kv: kv[1])
        ]

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

                    cat_id = category_map[label] + 1  # 1-indexed for COCO

                    coco_ann = {
                        "id": annotation_id_counter,
                        "image_id": image_id,
                        "category_id": cat_id,
                        "iscrowd": 0,
                    }
                    annotation_id_counter += 1

                    if obj_type == "bbox":
                        x = obj.get("x", 0)
                        y = obj.get("y", 0)
                        w = obj.get("width", 0)
                        h = obj.get("height", 0)
                        coco_ann["bbox"] = [x, y, w, h]
                        coco_ann["area"] = w * h
                        coco_ann["segmentation"] = []

                    elif obj_type in ("polygon", "freeform"):
                        points = obj.get("points", [])
                        if not points:
                            warnings.append(
                                f"Empty points for {obj_type} in {instance_id}"
                            )
                            continue
                        flat = flatten_polygon(points)
                        coco_ann["segmentation"] = [flat]
                        bx, by, bw, bh = polygon_to_bbox(points)
                        coco_ann["bbox"] = [bx, by, bw, bh]
                        coco_ann["area"] = polygon_area(points)

                    elif obj_type == "landmark":
                        warnings.append(
                            f"Landmark annotation in {instance_id} skipped "
                            f"(not standard in COCO detection format)"
                        )
                        continue

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
