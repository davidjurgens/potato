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
    clip_bbox,
    label_file_paths,
    normalize_bbox,
    extract_image_annotations,
    blank_item_warning,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
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
                w, h = get_image_dimensions(
                    item, config=context.config, annotation=ann)
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

        # One label set per (annotator, image). Merging every annotator's boxes
        # into one file trained on duplicates; when the study has several
        # annotators each gets their own labels/<annotator>/ directory.
        image_labels = {}  # (user_id, instance_id) -> list of label lines
        annotators = sorted({str(a.get("user_id", "")) for a in context.annotations
                             if extract_image_annotations(a)})
        per_annotator = len(annotators) > 1
        label_paths = label_file_paths({
            a.get("instance_id", ""): (get_image_filename(
                context.items.get(a.get("instance_id", ""), {}), context.config)
                or a.get("instance_id", ""))
            for a in context.annotations if extract_image_annotations(a)})

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            img_w, img_h = get_image_dimensions(
                item, config=context.config, annotation=ann)
            if img_w <= 0 or img_h <= 0:
                warnings.append(f"Skipping {instance_id}: no image dimensions")
                continue

            stem = (str(ann.get("user_id", "")), instance_id)
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

                    if obj_type == "landmark":
                        warnings.append(
                            f"Landmark in {instance_id} skipped (not supported in YOLO)"
                        )
                        continue

                    if obj_type not in ("bbox", "polygon", "freeform", "mask"):
                        warnings.append(
                            f"Unknown type '{obj_type}' in {instance_id}"
                        )
                        continue

                    # Reads the client's normalized `coordinates` shape and
                    # returns absolute pixels; normalize_bbox re-normalizes to
                    # YOLO's center-based convention below.
                    canon = normalize_annotation_object(obj, img_w, img_h)
                    if canon is None:
                        warnings.append(
                            f"Unusable {obj_type} in {instance_id}, skipping"
                        )
                        continue
                    warnings.extend(
                        f"{w} ({instance_id})" for w in canon["warnings"]
                    )

                    if obj_type != "bbox":
                        warnings.append(
                            f"{obj_type} in {instance_id} converted to enclosing bbox"
                        )

                    bx, by, bw, bh = canon["bbox"]
                    if clip_bbox(bx, by, bw, bh, img_w, img_h) is None:
                        warnings.append(
                            f"{obj_type} in {instance_id} lies outside the image, skipping")
                        continue
                    cx, cy, nw, nh = normalize_bbox(bx, by, bw, bh, img_w, img_h)
                    image_labels[stem].append(
                        f"{class_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                    )

        if per_annotator:
            warnings.append(
                f"{len(annotators)} annotators drew boxes: wrote one label set per "
                f"annotator under labels/<annotator>/. Choose or merge them "
                f"before training.")

        # Write label files
        for (user_id, instance_id), lines in image_labels.items():
            rel = label_paths.get(instance_id, instance_id)
            if per_annotator:
                safe_user = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_id)
                rel = f"{safe_user or '_'}/{rel}"
            label_file = os.path.join(labels_dir, *f"{rel}.txt".split("/"))
            os.makedirs(os.path.dirname(label_file), exist_ok=True)
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

        # Items nobody marked produce no record at all, so they are
        # absent from the output rather than present and empty.
        _blank = blank_item_warning(context, 'the YOLO export')
        if _blank:
            warnings.append(_blank)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_images": len({iid for _u, iid in image_labels}),
                "num_annotators": len(annotators),
                "num_annotations": sum(len(v) for v in image_labels.values()),
                "num_classes": len(sorted_labels),
            },
        )
