"""
Mask Exporter

Exports segmentation mask annotations as PNG binary images.
Each label gets a separate PNG where filled pixels are the label color
and background is transparent.

Requires: numpy and Pillow (PIL)
"""

import os
import logging
from typing import Optional, Tuple, List

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    extract_image_annotations,
    get_image_dimensions,
    get_image_filename,
    build_category_mapping,
)

logger = logging.getLogger(__name__)


def _decode_rle(rle: dict, width: int, height: int) -> list:
    """
    Decode RLE-encoded mask to a flat binary array.

    Args:
        rle: Dict with 'counts' (list of ints) and 'size' [height, width]
        width: Image width
        height: Image height

    Returns:
        Flat list of 0/1 values
    """
    counts = rle.get("counts", [])
    total = width * height
    mask = [0] * total
    pos = 0
    val = 0
    for count in counts:
        for _ in range(count):
            if pos < total:
                mask[pos] = val
                pos += 1
        val = 1 - val
    return mask


class MaskExporter(BaseExporter):
    format_name = "mask_png"
    description = "Segmentation masks as PNG images (requires Pillow)"
    file_extensions = [".png"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        # Check for Pillow
        try:
            from PIL import Image
        except ImportError:
            return False, "Pillow (PIL) is required for mask export. Install with: pip install Pillow"

        has_image_schema = any(
            s.get("annotation_type") == "image_annotation"
            for s in context.schemas
        )
        if not has_image_schema:
            return False, "No image_annotation schema found in config"

        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from PIL import Image

        options = options or {}
        warnings = []
        files_written = []

        os.makedirs(output_path, exist_ok=True)
        category_map = build_category_mapping(context.annotations, context.schemas)

        # Assign colors to categories
        default_colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 0), (0, 128, 0), (0, 0, 128),
            (128, 128, 0),
        ]
        category_colors = {}
        for name, idx in category_map.items():
            category_colors[name] = default_colors[idx % len(default_colors)]

        masks_exported = 0

        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            item = context.items.get(instance_id, {})
            img_anns = extract_image_annotations(ann)
            if not img_anns:
                continue

            width, height = get_image_dimensions(item)
            if width <= 0 or height <= 0:
                # Try to get from mask RLE size
                for _, objects in img_anns:
                    for obj in objects:
                        if obj.get("type") == "mask" and "rle" in obj:
                            size = obj["rle"].get("size", [])
                            if len(size) == 2:
                                height, width = size
                                break
                    if width > 0:
                        break

            if width <= 0 or height <= 0:
                warnings.append(f"No dimensions for {instance_id}, skipping masks")
                continue

            file_name = get_image_filename(item) or instance_id
            stem = os.path.splitext(os.path.basename(file_name))[0]

            for schema_name, objects in img_anns:
                for obj in objects:
                    if obj.get("type") != "mask":
                        continue

                    label = obj.get("label", "unknown")
                    rle = obj.get("rle", {})
                    if not rle.get("counts"):
                        continue

                    mask_data = _decode_rle(rle, width, height)
                    color = category_colors.get(label, (255, 255, 255))

                    # Create RGBA image
                    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    pixels = img.load()

                    for i, val in enumerate(mask_data):
                        if val:
                            y = i // width
                            x = i % width
                            if x < width and y < height:
                                pixels[x, y] = (color[0], color[1], color[2], 200)

                    mask_file = os.path.join(output_path, f"{stem}_{label}_mask.png")
                    img.save(mask_file)
                    files_written.append(mask_file)
                    masks_exported += 1

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_masks": masks_exported},
        )
