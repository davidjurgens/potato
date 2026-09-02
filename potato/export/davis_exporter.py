"""
DAVIS / YouTube-VOS exporter — per-frame indexed PNG masks.

Writes ``Annotations/<sequence>/<frame>.png``, one **palette** image per frame
whose pixel values are object ids: 0 background, 1..N the objects.

The property that makes or breaks this format is that the file must be indexed,
mode ``P``, with pixel values equal to the ids. Saving an RGB image that merely
looks the same is the standard way to produce a mask set every VOS tool
silently misreads — the palette colours survive, the ids do not, and the error
only surfaces as poor benchmark numbers much later. So the image is built in
``P`` mode with an explicit palette, and a test reads the pixel values back
rather than comparing the rendering.

Object identity comes from ``instance`` (or ``track_id``), which is what makes
id 3 the same object in frame 0 and frame 50. When an object has neither, ids
are assigned per label and held stable across the sequence — arbitrary, but
consistent, and reported.

Requires Pillow. Without it the export fails with the install command rather
than writing nothing and reporting success.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult
from .cv_utils import (
    decode_rle,
    extract_image_annotations,
    get_image_dimensions,
    normalize_annotation_object,
    polygons_to_rle,
)

logger = logging.getLogger(__name__)

#: DAVIS reserves 0 for background and 255 for void/ignore, so real object ids
#: run 1..254. Beyond that the format cannot represent them.
MAX_OBJECT_ID = 254

DEFAULT_SEQUENCE = "sequence"


def _davis_palette() -> List[int]:
    """
    The DAVIS palette: distinct, stable colours so a mask is readable by eye.

    Only the palette differs from the standard PASCAL VOC colour map; the
    pixel VALUES are what carry meaning, and those are the object ids.
    """
    palette = []
    for index in range(256):
        r = g = b = 0
        cid = index
        for shift in range(8):
            r |= ((cid >> 0) & 1) << (7 - shift)
            g |= ((cid >> 1) & 1) << (7 - shift)
            b |= ((cid >> 2) & 1) << (7 - shift)
            cid >>= 3
        palette.extend([r, g, b])
    return palette


class DAVISExporter(BaseExporter):
    format_name = "davis"
    description = "DAVIS / YouTube-VOS per-frame indexed PNG masks"
    file_extensions = [".png"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(s.get("annotation_type") == "image_annotation"
                   for s in context.schemas):
            return False, "No image_annotation schema found in config"
        try:
            import PIL  # noqa: F401
        except ImportError:
            return False, (
                "Writing DAVIS masks needs Pillow. Install it with "
                "`pip install Pillow`.")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from PIL import Image

        options = options or {}
        warnings: List[str] = []
        files_written: List[str] = []

        by_image: Dict[str, list] = {}
        for ann in context.annotations:
            instance_id = ann.get("instance_id", "")
            for _schema, objects in extract_image_annotations(ann):
                by_image.setdefault(instance_id, []).extend(objects)

        # Ids must be stable ACROSS frames, so they are assigned once for the
        # whole export rather than per frame -- otherwise object 1 in frame 0
        # and object 1 in frame 1 would be unrelated, which is the one thing
        # this format exists to express.
        id_by_key = self._assign_ids(by_image, warnings)
        palette = _davis_palette()

        num_masks = 0
        overflow = 0
        for instance_id, objects in sorted(by_image.items()):
            item = context.items.get(instance_id, {})
            width, height = get_image_dimensions(item)
            if width <= 0 or height <= 0:
                warnings.append(
                    f"{instance_id} has no image dimensions; skipped.")
                continue

            canvas = [0] * (width * height)
            for obj in objects:
                bitmap = self._bitmap(obj, width, height)
                if bitmap is None:
                    continue
                object_id = id_by_key.get(self._key(obj), 0)
                if object_id > MAX_OBJECT_ID:
                    overflow += 1
                    continue
                for i, on in enumerate(bitmap):
                    if on:
                        canvas[i] = object_id
                num_masks += 1

            sequence = str(item.get("sequence") or DEFAULT_SEQUENCE)
            frame = item.get("frame")
            try:
                name = f"{int(frame):05d}.png"
            except (TypeError, ValueError):
                name = f"{os.path.splitext(str(instance_id))[0]}.png"

            seq_dir = os.path.join(output_path, "Annotations", sequence)
            os.makedirs(seq_dir, exist_ok=True)
            out_file = os.path.join(seq_dir, name)

            # Mode 'P' with an explicit palette: the pixel VALUES are the ids.
            # An RGB save would look identical and be unreadable as a mask.
            image = Image.new("P", (width, height))
            image.putdata(canvas)
            image.putpalette(palette)
            image.save(out_file)
            files_written.append(out_file)

        if overflow:
            warnings.append(
                f"{overflow} object(s) exceeded id {MAX_OBJECT_ID} and were "
                f"omitted: an indexed PNG reserves 0 for background and 255 "
                f"for void, so it cannot hold more objects than that.")

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={"num_images": len(files_written), "num_annotations": num_masks},
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _key(obj) -> str:
        attrs = obj.get("attributes") or {}
        identity = attrs.get("track_id", obj.get("instance"))
        if identity is not None:
            return f"id:{identity}"
        return f"label:{obj.get('label', '')}"

    def _assign_ids(self, by_image, warnings) -> Dict[str, int]:
        """One id per distinct object identity, stable across every frame."""
        explicit: Dict[str, int] = {}
        fallback: List[str] = []
        for objects in by_image.values():
            for obj in objects:
                key = self._key(obj)
                if key in explicit or key in fallback:
                    continue
                if key.startswith("id:"):
                    try:
                        explicit[key] = int(key[3:])
                        continue
                    except ValueError:
                        pass
                fallback.append(key)

        used = set(explicit.values())
        next_id = 1
        for key in sorted(fallback):
            while next_id in used:
                next_id += 1
            explicit[key] = next_id
            used.add(next_id)

        if fallback:
            warnings.append(
                f"{len(fallback)} object(s) had no instance or track id, so "
                f"ids were assigned per label and held constant across the "
                f"sequence. That is consistent but arbitrary: two different "
                f"cats annotated as 'cat' become one object.")
        return explicit

    @staticmethod
    def _bitmap(obj, width, height):
        """A flat 0/1 bitmap for any geometry type DAVIS can represent."""
        obj_type = obj.get("type", "")
        if obj_type == "mask":
            rle = obj.get("rle") or {}
            if not rle.get("counts"):
                return None
            return decode_rle(rle, width, height)

        canon = normalize_annotation_object(obj, width, height)
        if canon is None:
            return None
        if obj_type == "bbox":
            x, y, w, h = canon["bbox"]
            points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        else:
            points = canon.get("points") or []
        if len(points) < 3:
            return None
        rle = polygons_to_rle([points], height, width)
        return decode_rle(rle, width, height)
