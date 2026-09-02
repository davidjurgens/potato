"""
COCO JSON Exporter

Exports image annotations to COCO format with images[], annotations[],
and categories[] arrays. Supports bbox, polygon/freeform segmentation.
"""

import json
import os
import logging
from typing import List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    build_coco_category_map,
    coco_rle_to_rle,
    decode_rle,
    flatten_polygon,
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
    normalize_annotation_object,
    polygons_to_rle,
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
        polyline_count = 0
        ellipse_count = 0

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            # Dimensions are read per annotation record, NOT only when a new
            # image id is minted. Two annotators on the same image produce two
            # records with the same instance_id, and the second one used to
            # fall through with `width`/`height` still holding the PREVIOUS
            # image's values -- silently rescaling that annotator's geometry.
            width, height = get_image_dimensions(item)

            # Assign image ID (deduplicate by instance_id)
            if instance_id not in image_id_map:
                image_id = image_id_counter
                image_id_counter += 1
                image_id_map[instance_id] = image_id

                file_name = get_image_filename(item) or instance_id

                image_entry = {
                    "id": image_id,
                    "file_name": file_name,
                    "width": width,
                    "height": height,
                }
                # Video sequences (MOT, DAVIS, extracted frames) carry which
                # clip and which frame each item came from. COCO's own video
                # derivatives use exactly these keys, and dropping them turns
                # an ordered sequence into an unordered pile of stills that
                # cannot be reassembled.
                if item.get("sequence") is not None:
                    image_entry["sequence"] = item["sequence"]
                if item.get("frame") is not None:
                    try:
                        image_entry["frame_id"] = int(item["frame"])
                    except (TypeError, ValueError):
                        pass
                coco_images.append(image_entry)
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

                    if obj_type == "keypoint_set":
                        # The other half of the round trip the importer opens.
                        # COCO wants a flat [x, y, v, ...] triplet stream plus
                        # num_keypoints (visible/occluded only, NOT unlabelled).
                        canon = normalize_annotation_object(obj, width, height)
                        if canon is None or not canon.get("points"):
                            warnings.append(
                                f"Unusable keypoint_set in {instance_id}")
                            continue
                        vis = canon.get("visibility") or []
                        flat: List[float] = []
                        for idx, (px, py) in enumerate(canon["points"]):
                            v = int(vis[idx]) if idx < len(vis) else 2
                            # An unlabelled point is (0, 0, 0) by convention,
                            # not its stored position.
                            flat.extend([0.0, 0.0, 0] if v == 0
                                        else [round(px, 2), round(py, 2), v])
                        bx, by, bw, bh = canon["bbox"]
                        coco_annotations.append({
                            "id": annotation_id_counter,
                            "image_id": image_id,
                            "category_id": category_map[label],
                            "bbox": [round(bx, 2), round(by, 2),
                                     round(bw, 2), round(bh, 2)],
                            "area": round(bw * bh, 2),
                            "iscrowd": 0,
                            "keypoints": flat,
                            "num_keypoints": sum(1 for v in vis if v > 0),
                            "segmentation": [],
                        })
                        annotation_id_counter += 1
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

                    elif obj_type == "ellipse":
                        # COCO has no ellipse. The 36-gon approximation is
                        # visually identical and is a real polygon, so it is
                        # written as one; the parametric form is kept in an
                        # extension key so a Potato-to-Potato trip is exact.
                        coco_ann["segmentation"] = [
                            flatten_polygon(canon["points"])
                        ]
                        coco_ann["ellipse"] = canon["ellipse"]
                        ellipse_count += 1

                    elif obj_type == "polyline":
                        # An open path has no interior, so `segmentation` stays
                        # empty and `area` is 0 rather than the area of the
                        # closed shape -- writing the closed polygon would turn
                        # every lane marking into a filled region, which reads
                        # as a real segmentation mask downstream.
                        coco_ann["segmentation"] = []
                        coco_ann["area"] = 0
                        coco_ann["polyline"] = flatten_polygon(canon["points"])
                        polyline_count += 1

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

        if polyline_count:
            warnings.append(
                f"{polyline_count} polyline(s) were written with an empty "
                f"`segmentation`, `area: 0`, and their points under a "
                f"non-standard `polyline` key. COCO has no open-path type; "
                f"closing them into polygons would turn each one into a filled "
                f"region that reads downstream as a real segmentation mask.")
        if ellipse_count:
            warnings.append(
                f"{ellipse_count} ellipse(s) were written as their 36-vertex "
                f"polygon approximation, with the exact parametric form kept "
                f"under a non-standard `ellipse` key.")

        os.makedirs(output_path, exist_ok=True)
        out_file = os.path.join(output_path, "annotations.json")
        with open(out_file, "w") as f:
            json.dump(coco_output, f, indent=2)

        files_written = [out_file]
        if options.get("panoptic"):
            panoptic_files, panoptic_warnings = self._write_panoptic(
                context, coco_images, coco_annotations, coco_categories,
                output_path)
            files_written.extend(panoptic_files)
            warnings.extend(panoptic_warnings)

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_images": len(coco_images),
                "num_annotations": len(coco_annotations),
                "num_categories": len(coco_categories),
            },
        )

    # ------------------------------------------------------------------
    # Panoptic
    # ------------------------------------------------------------------

    def _write_panoptic(self, context, coco_images, coco_annotations,
                        coco_categories, output_path):
        """
        Write COCO panoptic output: one PNG per image plus a segments JSON.

        The panoptic format encodes each segment's id in the PIXEL COLOUR as
        ``id = R + G*256 + B*256^2``. That is not a palette and not a class
        map — two segments of the same class have different ids, which is the
        whole point — so the PNG must be written as RGB with those exact
        channel values. Saving an indexed image instead (as the DAVIS exporter
        correctly does for *its* format) would cap the ids at 255 and silently
        merge segments in any image with more than a handful.

        Panoptic segmentation also requires that every pixel belong to at most
        one segment. Potato's annotations may overlap, so later segments
        overwrite earlier ones and the overlap is reported rather than left to
        produce a silently inconsistent ground truth.
        """
        warnings = []
        try:
            from PIL import Image
        except ImportError:
            return [], ["Panoptic export needs Pillow; install it with "
                        "`pip install Pillow`. The detection JSON was still "
                        "written."]

        by_image = {}
        for ann in coco_annotations:
            by_image.setdefault(ann["image_id"], []).append(ann)

        panoptic_dir = os.path.join(output_path, "panoptic")
        os.makedirs(panoptic_dir, exist_ok=True)

        files_written = []
        panoptic_annotations = []
        overlapping = 0

        for image in coco_images:
            width, height = image["width"], image["height"]
            # Segment id 0 is reserved for unlabelled pixels.
            id_canvas = [0] * (width * height)
            segments_info = []

            for ann in by_image.get(image["id"], []):
                bitmap = self._panoptic_bitmap(ann, width, height)
                if bitmap is None:
                    continue
                segment_id = ann["id"]
                claimed = 0
                for i, on in enumerate(bitmap):
                    if not on:
                        continue
                    if id_canvas[i]:
                        claimed += 1
                    id_canvas[i] = segment_id
                if claimed:
                    overlapping += 1
                segments_info.append({
                    "id": segment_id,
                    "category_id": ann["category_id"],
                    "area": int(sum(bitmap)),
                    "bbox": ann["bbox"],
                    "iscrowd": ann.get("iscrowd", 0),
                })

            # id = R + G*256 + B*256^2, written as real RGB channels.
            pixels = [(sid % 256, (sid // 256) % 256, (sid // 65536) % 256)
                      for sid in id_canvas]
            png = Image.new("RGB", (width, height))
            png.putdata(pixels)

            stem = os.path.splitext(os.path.basename(image["file_name"]))[0]
            png_name = f"{stem}.png"
            png_path = os.path.join(panoptic_dir, png_name)
            png.save(png_path)
            files_written.append(png_path)

            panoptic_annotations.append({
                "image_id": image["id"],
                "file_name": png_name,
                "segments_info": segments_info,
            })

        json_path = os.path.join(output_path, "panoptic.json")
        with open(json_path, "w") as f:
            json.dump({
                "images": coco_images,
                "annotations": panoptic_annotations,
                "categories": coco_categories,
            }, f, indent=2)
        files_written.append(json_path)

        if overlapping:
            warnings.append(
                f"{overlapping} segment(s) overlapped another and the later "
                f"one won. Panoptic segmentation requires each pixel to belong "
                f"to at most one segment, so overlapping annotations cannot be "
                f"represented; the detection JSON keeps them intact.")
        return files_written, warnings

    @staticmethod
    def _panoptic_bitmap(ann, width, height):
        """A flat 0/1 bitmap for one COCO annotation."""
        segmentation = ann.get("segmentation")
        if isinstance(segmentation, dict) and segmentation.get("counts"):
            rle = coco_rle_to_rle(segmentation)
            return decode_rle(rle, width, height)
        if isinstance(segmentation, list) and segmentation:
            rle = polygons_to_rle(segmentation, height, width)
            return decode_rle(rle, width, height)
        # A box-only annotation fills its box; a polyline has no interior.
        if ann.get("polyline"):
            return None
        x, y, w, h = ann.get("bbox") or [0, 0, 0, 0]
        if w <= 0 or h <= 0:
            return None
        bitmap = [0] * (width * height)
        for row in range(max(0, int(y)), min(height, int(y + h))):
            base = row * width
            for col in range(max(0, int(x)), min(width, int(x + w))):
                bitmap[base + col] = 1
        return bitmap
