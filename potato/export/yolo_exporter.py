"""
YOLO Exporter

Exports image annotations to YOLO format:
- One .txt file per image with lines: class_id cx cy w h (normalized 0-1)
- classes.txt listing class names
- data.yaml for Ultralytics compatibility
"""

import os
import logging
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    build_category_mapping,
    polygon_to_bbox,
    normalize_bbox,
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
)

logger = logging.getLogger(__name__)


class YOLOExporter(BaseExporter):
    format_name = "yolo"
    description = "YOLO format for object detection (Ultralytics compatible)"
    file_extensions = [".txt", ".yaml"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        has_image_schema = any(
            s.get("annotation_type") == "image_annotation"
            for s in context.schemas
        )
        if not has_image_schema:
            return False, "No image_annotation schema found in config"

        # Check that we can get image dimensions
        missing_dims = []
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if img_anns:
                w, h = get_image_dimensions(item)
                if w <= 0 or h <= 0:
                    missing_dims.append(instance_id)

        if missing_dims:
            return (
                False,
                f"YOLO requires image dimensions. Missing for: "
                f"{', '.join(missing_dims[:5])}"
                f"{'...' if len(missing_dims) > 5 else ''}"
            )
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings = []
        files_written = []

        category_map = build_category_mapping(context.annotations, context.schemas)
        labels_dir = os.path.join(output_path, "labels")
        os.makedirs(labels_dir, exist_ok=True)

        # Track which images have been written (handle multiple annotators)
        image_labels = {}  # filename_stem -> list of label lines

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            img_w, img_h = get_image_dimensions(item)
            if img_w <= 0 or img_h <= 0:
                warnings.append(f"Skipping {instance_id}: no image dimensions")
                continue

            file_name = get_image_filename(item) or instance_id
            stem = os.path.splitext(os.path.basename(file_name))[0]

            if stem not in image_labels:
                image_labels[stem] = []

            for schema_name, objects in img_anns:
                for obj in objects:
                    obj_type = obj.get("type", "")
                    label = obj.get("label", "")

                    if label not in category_map:
                        warnings.append(f"Unknown label '{label}' in {instance_id}")
                        continue

                    class_id = category_map[label]

                    if obj_type == "bbox":
                        x = obj.get("x", 0)
                        y = obj.get("y", 0)
                        w = obj.get("width", 0)
                        h = obj.get("height", 0)
                        cx, cy, nw, nh = normalize_bbox(x, y, w, h, img_w, img_h)
                        image_labels[stem].append(
                            f"{class_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                        )

                    elif obj_type in ("polygon", "freeform"):
                        points = obj.get("points", [])
                        if not points:
                            continue
                        bx, by, bw, bh = polygon_to_bbox(points)
                        cx, cy, nw, nh = normalize_bbox(bx, by, bw, bh, img_w, img_h)
                        warnings.append(
                            f"{obj_type} in {instance_id} converted to enclosing bbox"
                        )
                        image_labels[stem].append(
                            f"{class_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                        )

                    elif obj_type == "landmark":
                        warnings.append(
                            f"Landmark in {instance_id} skipped (not supported in YOLO)"
                        )

                    else:
                        warnings.append(
                            f"Unknown type '{obj_type}' in {instance_id}"
                        )

        # Write label files
        for stem, lines in image_labels.items():
            label_file = os.path.join(labels_dir, f"{stem}.txt")
            with open(label_file, "w") as f:
                f.write("\n".join(lines))
                if lines:
                    f.write("\n")
            files_written.append(label_file)

        # Write classes.txt
        sorted_labels = sorted(category_map.items(), key=lambda kv: kv[1])
        classes_file = os.path.join(output_path, "classes.txt")
        with open(classes_file, "w") as f:
            for name, _ in sorted_labels:
                f.write(f"{name}\n")
        files_written.append(classes_file)

        # Write data.yaml for Ultralytics
        data_yaml = os.path.join(output_path, "data.yaml")
        with open(data_yaml, "w") as f:
            f.write(f"path: {output_path}\n")
            f.write("train: images/train\n")
            f.write("val: images/val\n")
            f.write(f"nc: {len(sorted_labels)}\n")
            f.write(f"names: [{', '.join(repr(n) for n, _ in sorted_labels)}]\n")
        files_written.append(data_yaml)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_images": len(image_labels),
                "num_annotations": sum(len(v) for v in image_labels.values()),
                "num_classes": len(sorted_labels),
            },
        )
