"""
CVAT XML 1.1 exporter — the other half of the CVAT round trip.

CVAT was import-only, which is the wrong asymmetry for a migration story:
getting data *out* of a tool is never the hard part, but a one-way import means
a team cannot move back, or hand a colleague on CVAT the corrected annotations.

CVAT carries more shape types than most formats, so unlike Pascal VOC this
exporter does not have to flatten anything into a bounding box:

    bbox         -> <box xtl ytl xbr ybr>       (CORNERS, not origin+size)
    polygon      -> <polygon points="x,y;...">
    polyline     -> <polyline points="x,y;...">  stays open
    ellipse      -> <ellipse cx cy rx ry rotation>
    landmark     -> <points points="x,y">
    keypoint_set -> <points> with every visible point

Masks are the exception and are reported: CVAT 1.1's ``<mask>`` uses its own RLE
dialect with an offset origin, and emitting an untested approximation of someone
else's binary format is worse than saying it is not supported.
"""

import logging
import os
from typing import List, Optional, Tuple
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    extract_image_annotations,
    blank_item_warning,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
)

logger = logging.getLogger(__name__)


def _points_attr(points: List[List[float]]) -> str:
    """CVAT's point list format: ``x,y;x,y;...`` with 2dp."""
    return ";".join(f"{round(x, 2)},{round(y, 2)}" for x, y in points)


class CVATExporter(BaseExporter):
    format_name = "cvat"
    description = "CVAT XML 1.1 for images"
    file_extensions = [".xml"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") == "image_annotation"
                   for s in context.schemas):
            return False, "No image_annotation schema found in config"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        warnings: List[str] = []
        os.makedirs(output_path, exist_ok=True)

        # Label colours come from the schema so a round trip through CVAT keeps
        # the project looking the same rather than being recoloured.
        colours = {}
        for schema in context.schemas:
            for label in schema.get("labels", []) or []:
                if isinstance(label, dict) and label.get("name"):
                    colours[label["name"]] = label.get("color", "")
                elif isinstance(label, str):
                    colours.setdefault(label, "")

        root = Element("annotations")
        SubElement(root, "version").text = "1.1"
        meta = SubElement(root, "meta")
        task = SubElement(meta, "task")
        SubElement(task, "name").text = context.config.get(
            "annotation_task_name", "potato-export")
        labels_elem = SubElement(task, "labels")
        for name in sorted(colours):
            label_elem = SubElement(labels_elem, "label")
            SubElement(label_elem, "name").text = name
            SubElement(label_elem, "color").text = colours[name] or ""

        by_image = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        num_objects = 0
        for index, (instance_id, objects) in enumerate(sorted(by_image.items())):
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(
                item, config=context.config, annotation=ann)
            file_name = get_image_filename(item) or instance_id

            image_elem = SubElement(root, "image", {
                "id": str(index),
                "name": os.path.basename(file_name),
                "width": str(width),
                "height": str(height),
            })

            for obj in objects:
                element = self._shape_element(
                    obj, width, height, instance_id, warnings)
                if element is None:
                    continue
                image_elem.append(element)
                num_objects += 1

        out_file = os.path.join(output_path, "annotations.xml")
        tree = ElementTree(root)
        indent(tree, space="  ")
        tree.write(out_file, encoding="utf-8", xml_declaration=True)

        # Items nobody marked produce no record at all, so they are
        # absent from the output rather than present and empty.
        _blank = blank_item_warning(context, 'the CVAT XML')
        if _blank:
            warnings.append(_blank)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[out_file],
            warnings=warnings,
            stats={"num_images": len(by_image), "num_annotations": num_objects},
        )

    def _shape_element(self, obj, width, height, instance_id, warnings):
        obj_type = obj.get("type", "")
        label = obj.get("label", "")

        if obj_type == "mask":
            # CVAT 1.1's <mask> uses its own RLE dialect with an offset origin.
            # Emitting an untested approximation of someone else's binary format
            # is worse than saying plainly that it is not supported.
            warnings.append(
                f"Mask in {instance_id} skipped: CVAT's <mask> RLE dialect is "
                f"not implemented. Export to COCO to keep pixel masks.")
            return None

        canon = normalize_annotation_object(obj, width, height)
        if canon is None:
            warnings.append(f"Unusable {obj_type or 'annotation'} in {instance_id}")
            return None
        warnings.extend(f"{w} ({instance_id})" for w in canon["warnings"])

        attrs = {"label": label, "occluded": str(int(obj.get("occluded", 0) or 0)),
                 "source": "manual"}

        if obj_type == "bbox":
            x, y, w, h = canon["bbox"]
            # CORNERS. Writing origin+size here produces a file CVAT opens with
            # every box the wrong size, which reads as an annotation error.
            attrs.update({"xtl": f"{x:.2f}", "ytl": f"{y:.2f}",
                          "xbr": f"{x + w:.2f}", "ybr": f"{y + h:.2f}"})
            element = Element("box", attrs)

        elif obj_type == "ellipse":
            e = canon["ellipse"]
            attrs.update({"cx": f"{e['cx']:.2f}", "cy": f"{e['cy']:.2f}",
                          "rx": f"{e['rx']:.2f}", "ry": f"{e['ry']:.2f}",
                          "rotation": f"{e['angle']:.2f}"})
            element = Element("ellipse", attrs)

        elif obj_type in ("polygon", "freeform"):
            attrs["points"] = _points_attr(canon["points"])
            element = Element("polygon", attrs)

        elif obj_type == "polyline":
            attrs["points"] = _points_attr(canon["points"])
            element = Element("polyline", attrs)

        elif obj_type == "landmark":
            attrs["points"] = _points_attr(canon["points"])
            element = Element("points", attrs)

        elif obj_type == "keypoint_set":
            # Only the points the annotator actually marked: CVAT's <points>
            # has no visibility flag, so an unlabelled joint would otherwise be
            # written at (0, 0) and read back as a real point at the corner.
            visible = [p for p, v in zip(canon["points"],
                                         canon.get("visibility") or [])
                       if v]
            if not visible:
                warnings.append(
                    f"Keypoint set in {instance_id} has no labelled points")
                return None
            if len(visible) != len(canon["points"]):
                warnings.append(
                    f"Keypoint set in {instance_id}: {len(canon['points']) - len(visible)} "
                    f"unlabelled point(s) dropped — CVAT's <points> has no "
                    f"visibility flag.")
            attrs["points"] = _points_attr(visible)
            element = Element("points", attrs)

        else:
            warnings.append(f"Unknown type '{obj_type}' in {instance_id}")
            return None

        for key, value in (obj.get("attributes") or {}).items():
            attr_elem = SubElement(element, "attribute", {"name": str(key)})
            attr_elem.text = str(value)
        return element
