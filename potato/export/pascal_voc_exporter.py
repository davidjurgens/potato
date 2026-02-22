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
    build_category_mapping,
    polygon_to_bbox,
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
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

        # Group annotations by instance_id to produce one XML per image
        image_objects = {}  # instance_id -> list of object dicts

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            if instance_id not in image_objects:
                image_objects[instance_id] = []

            for schema_name, objects in img_anns:
                for obj in objects:
                    image_objects[instance_id].append(obj)

        for instance_id, objects in image_objects.items():
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(item)
            file_name = get_image_filename(item) or instance_id
            stem = os.path.splitext(os.path.basename(file_name))[0]

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

                if obj_type == "bbox":
                    xmin = obj.get("x", 0)
                    ymin = obj.get("y", 0)
                    xmax = xmin + obj.get("width", 0)
                    ymax = ymin + obj.get("height", 0)

                elif obj_type in ("polygon", "freeform"):
                    points = obj.get("points", [])
                    if not points:
                        continue
                    bx, by, bw, bh = polygon_to_bbox(points)
                    xmin = bx
                    ymin = by
                    xmax = bx + bw
                    ymax = by + bh
                    warnings.append(
                        f"{obj_type} in {instance_id} converted to enclosing bbox"
                    )

                else:
                    warnings.append(
                        f"Unknown type '{obj_type}' in {instance_id}"
                    )
                    continue

                obj_elem = SubElement(root, "object")
                SubElement(obj_elem, "name").text = label
                SubElement(obj_elem, "pose").text = "Unspecified"
                SubElement(obj_elem, "truncated").text = "0"
                SubElement(obj_elem, "difficult").text = "0"

                bndbox = SubElement(obj_elem, "bndbox")
                SubElement(bndbox, "xmin").text = str(int(round(xmin)))
                SubElement(bndbox, "ymin").text = str(int(round(ymin)))
                SubElement(bndbox, "xmax").text = str(int(round(xmax)))
                SubElement(bndbox, "ymax").text = str(int(round(ymax)))

            xml_file = os.path.join(output_path, f"{stem}.xml")
            tree = ElementTree(root)
            indent(tree, space="  ")
            tree.write(xml_file, encoding="unicode", xml_declaration=True)
            files_written.append(xml_file)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_images": len(image_objects),
                "num_objects": sum(len(v) for v in image_objects.values()),
            },
        )
