"""
Pascal VOC XML Exporter

Exports image annotations to Pascal VOC format:
- One XML file per image with <annotation><object><bndbox> structure
"""

import os
import logging
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    clip_bbox,
    extract_image_annotations,
    label_file_paths,
    blank_item_warning,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
)

logger = logging.getLogger(__name__)


class PascalVOCExporter(BaseExporter):
    format_name = "pascal_voc"
    description = "Pascal VOC XML format for object detection"
    file_extensions = [".xml"]

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
        files_written = []

        os.makedirs(output_path, exist_ok=True)

        # One XML per (annotator, image). Grouping by image merged every
        # annotator's boxes into one file of duplicates; with several
        # annotators each gets their own <annotator>/ directory.
        image_objects = {}  # (user_id, instance_id) -> list of object dicts
        record_for = {}

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue
            key = (str(ann.get("user_id", "")), instance_id)
            image_objects.setdefault(key, [])
            record_for[key] = ann

            for schema_name, objects in img_anns:
                for obj in objects:
                    image_objects[key].append(obj)

        annotators = sorted({u for u, _iid in image_objects})
        per_annotator = len(annotators) > 1
        if per_annotator:
            warnings.append(
                f"{len(annotators)} annotators drew boxes: wrote one XML set per "
                f"annotator under <annotator>/. Choose or merge them before training.")
        label_paths = label_file_paths({
            iid: get_image_filename(context.items.get(iid, {}), context.config) or iid
            for _u, iid in image_objects})

        for (user_id, instance_id), objects in image_objects.items():
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(
                item, config=context.config, annotation=record_for[(user_id, instance_id)])
            file_name = get_image_filename(item, context.config) or instance_id
            stem = label_paths.get(instance_id, instance_id)
            if per_annotator:
                safe_user = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_id)
                stem = f"{safe_user or '_'}/{stem}"

            root = Element("annotation")

            folder_elem = SubElement(root, "folder")
            folder_elem.text = "images"

            filename_elem = SubElement(root, "filename")
            filename_elem.text = os.path.basename(file_name)

            size_elem = SubElement(root, "size")
            SubElement(size_elem, "width").text = str(width)
            SubElement(size_elem, "height").text = str(height)
            SubElement(size_elem, "depth").text = str(item.get("depth", 3))

            SubElement(root, "segmented").text = "0"

            for obj in objects:
                obj_type = obj.get("type", "")
                label = obj.get("label", "")

                if obj_type == "landmark":
                    warnings.append(
                        f"Landmark in {instance_id} skipped "
                        f"(not supported in Pascal VOC)"
                    )
                    continue

                if obj_type not in ("bbox", "polygon", "freeform", "mask"):
                    warnings.append(
                        f"Unknown type '{obj_type}' in {instance_id}"
                    )
                    continue

                # Reads the client's normalized `coordinates` shape; VOC wants
                # absolute pixel corners.
                canon = normalize_annotation_object(obj, width, height)
                if canon is None:
                    warnings.append(
                        f"Unusable {obj_type} in {instance_id}, skipping"
                    )
                    continue
                warnings.extend(f"{w} ({instance_id})" for w in canon["warnings"])

                if obj_type != "bbox":
                    warnings.append(
                        f"{obj_type} in {instance_id} converted to enclosing bbox"
                    )

                bx, by, bw, bh = canon["bbox"]
                clipped = clip_bbox(bx, by, bw, bh, width, height) if width > 0 and height > 0 \
                    else (bx, by, bw, bh)
                if clipped is None:
                    warnings.append(
                        f"{obj_type} in {instance_id} lies outside the image, skipping")
                    continue
                bx, by, bw, bh = clipped
                # VOC corners are 1-based pixel indices, inclusive: a box
                # covering pixels 0..9 is xmin=1, xmax=10, as the VOC devkit
                # defines it. detectron2 and py-faster-rcnn subtract 1 from
                # xmin/ymin on read, so a 0-based export landed every box a
                # pixel up and left there, and a box at the image edge came out
                # as xmin=0, which VOC does not allow.
                xmin, ymin = round(bx) + 1, round(by) + 1
                xmax, ymax = max(round(bx + bw), xmin), max(round(by + bh), ymin)

                obj_elem = SubElement(root, "object")
                SubElement(obj_elem, "name").text = label
                SubElement(obj_elem, "pose").text = "Unspecified"
                SubElement(obj_elem, "truncated").text = "0"
                SubElement(obj_elem, "difficult").text = "0"

                bndbox = SubElement(obj_elem, "bndbox")
                SubElement(bndbox, "xmin").text = str(int(xmin))
                SubElement(bndbox, "ymin").text = str(int(ymin))
                SubElement(bndbox, "xmax").text = str(int(xmax))
                SubElement(bndbox, "ymax").text = str(int(ymax))

            xml_file = os.path.join(output_path, *f"{stem}.xml".split("/"))
            os.makedirs(os.path.dirname(xml_file), exist_ok=True)
            tree = ElementTree(root)
            indent(tree, space="  ")
            tree.write(xml_file, encoding="unicode", xml_declaration=True)
            files_written.append(xml_file)

        # Items nobody marked produce no record at all, so they are
        # absent from the output rather than present and empty.
        _blank = blank_item_warning(context, 'the Pascal VOC export')
        if _blank:
            warnings.append(_blank)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_images": len({iid for _u, iid in image_objects}),
                "num_annotators": len(annotators),
                "num_objects": sum(len(v) for v in image_objects.values()),
            },
        )
