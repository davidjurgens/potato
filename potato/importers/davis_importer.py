"""
DAVIS / YouTube-VOS importer — per-frame indexed PNG masks.

Layout (DAVIS 2017)::

    JPEGImages/480p/<sequence>/00000.jpg
    Annotations/480p/<sequence>/00000.png     indexed PNG

Each annotation PNG is a **palette image whose pixel VALUES are object ids**,
not colours: 0 is background, 1..N are the tracked objects, and the palette
merely makes it look sensible in an image viewer. This is the single most
common way to misread the format — opening the PNG as RGB and clustering the
colours appears to work, produces the right number of objects on easy frames,
and quietly merges objects whose palette entries are close. The mask is
therefore read in ``P`` mode, or converted to it, so the ids come out exactly.

An object's id is stable across the frames of a sequence: id 3 in frame 0 is
the same physical object as id 3 in frame 50. That identity is the whole point
of the dataset, so it is carried into each object's ``instance`` field, and the
per-frame masks are keyed ``object_<id>#<id>`` accordingly.

Requires Pillow to read the PNGs. Without it the import fails with the install
command rather than silently importing zero annotations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import bitmap_to_rle, to_client_object

from ._common import apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Pixel value reserved for background in every VOS mask convention.
BACKGROUND = 0

#: 255 is the standard "void"/ignore value in DAVIS and YouTube-VOS masks; it
#: marks boundary pixels excluded from evaluation, not a 255th object.
VOID = 255

#: Guard against opening a full-resolution 4K mask set by accident. Decoding is
#: pure Python, so a very large frame is slow enough to look like a hang.
MAX_PIXELS = 4_000_000


class DAVISImporter(BaseAnnotationImporter):
    format_name = "davis"
    description = "DAVIS / YouTube-VOS per-frame indexed PNG masks"
    file_extensions = [".png"]

    def detect(self, data: Any) -> bool:
        return isinstance(data, dict) and "davis_sequences" in data

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        sequences = self._find_sequences(base)
        if not sequences:
            raise ValueError(
                f"No DAVIS sequences under {base}. Expected an Annotations/ "
                f"tree of per-sequence directories holding indexed PNG masks "
                f"(Annotations/480p/<sequence>/00000.png).")
        return self.parse({"davis_sequences": sequences, "root": base}, options)

    @staticmethod
    def _find_sequences(base: Path) -> List[Path]:
        """Every directory of numbered PNGs beneath an Annotations/ root."""
        roots = [base / "Annotations", base]
        for candidate in roots:
            if not candidate.is_dir():
                continue
            # Annotations/480p/<seq> and Annotations/<seq> are both in the wild.
            found = sorted({p.parent for p in candidate.rglob("*.png")})
            if found:
                return found
        return []

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a DAVIS dataset. Point --input at the directory holding "
                "Annotations/, not at a single PNG.")

        try:
            from PIL import Image
        except ImportError:
            raise ValueError(
                "Reading DAVIS masks needs Pillow, which is not installed. "
                "Install it with `pip install Pillow` and re-run.")

        result = ImportResult()
        sequences: List[Path] = list(data["davis_sequences"])
        root = Path(data.get("root") or ".")
        multi = len(sequences) > 1
        all_ids: set = set()
        void_frames = 0
        oversized: List[str] = []

        for seq_dir in sequences:
            frames = sorted(seq_dir.glob("*.png"))
            seq_ids: set = set()
            for frame_index, mask_path in enumerate(frames):
                try:
                    with Image.open(mask_path) as img:
                        width, height = img.size
                        if width * height > MAX_PIXELS:
                            oversized.append(f"{seq_dir.name}/{mask_path.name}")
                            continue
                        # 'P' keeps the pixel VALUES, which are the object ids.
                        # Converting to RGB would replace them with palette
                        # colours and silently merge nearby objects.
                        if img.mode not in ("P", "L", "I", "I;16"):
                            img = img.convert("P")
                        pixels = list(img.getdata())
                except Exception as exc:
                    result.warnings.append(
                        f"Could not read {mask_path.name}: {exc}")
                    continue

                objects, ids, saw_void = self._objects_from_pixels(
                    pixels, width, height, result.warnings, mask_path.name)
                seq_ids |= ids
                void_frames += int(saw_void)

                image_name = self._image_name(seq_dir, mask_path, root, multi)
                result.images.append(ImportedImage(
                    instance_id=safe_instance_id(
                        f"{seq_dir.name}_{mask_path.stem}"),
                    file_name=image_name,
                    width=width,
                    height=height,
                    objects=objects,
                    extra={
                        "image_url": apply_url_prefix(image_name, options),
                        "sequence": seq_dir.name,
                        "frame": frame_index,
                    },
                ))
            all_ids |= seq_ids

        if oversized:
            result.warnings.append(
                f"{len(oversized)} mask(s) exceed {MAX_PIXELS:,} pixels and "
                f"were skipped; decoding is pure Python and would appear to "
                f"hang. Use the 480p annotation set.")
        if void_frames:
            result.warnings.append(
                f"{void_frames} frame(s) contain value {VOID}, which DAVIS uses "
                f"for boundary pixels excluded from evaluation. Those pixels "
                f"were left out of every object rather than becoming a "
                f"'class {VOID}'.")
        if all_ids:
            result.warnings.append(
                f"{len(all_ids)} object id(s) found. An id is stable across a "
                f"sequence's frames, and is preserved in each object's "
                f"`instance` field — but the per-frame masks are separate "
                f"items, so editing one frame does not propagate.")

        result.labels = [{"name": f"object_{i}"} for i in sorted(all_ids)]
        result.tools = ["brush", "eraser"]
        result.summarize(num_objects=len(all_ids))
        return result

    # ------------------------------------------------------------------

    def _objects_from_pixels(self, pixels, width, height, warnings, name):
        """One mask per distinct non-background object id in the frame."""
        present = set(pixels)
        present.discard(BACKGROUND)
        saw_void = VOID in present
        present.discard(VOID)

        objects: List[dict] = []
        for object_id in sorted(present):
            bitmap = [1 if p == object_id else 0 for p in pixels]
            rle = bitmap_to_rle(bitmap, height, width)
            obj = to_client_object(
                "mask", f"object_{object_id}",
                img_w=width, img_h=height,
                rle=rle,
                instance=int(object_id),
                # A VOS object is one instance, not a crowd region. Saying so
                # explicitly stops a COCO export promoting it back to iscrowd=1
                # and collapsing instance segmentation.
                iscrowd=0,
            )
            if obj is not None:
                objects.append(obj)
        return objects, present, saw_void

    @staticmethod
    def _image_name(seq_dir: Path, mask_path: Path, root: Path,
                    multi: bool) -> str:
        """
        The JPEG beside the mask. DAVIS mirrors the Annotations/ tree under
        JPEGImages/ with the same sequence and frame names.
        """
        rel = f"{seq_dir.name}/{mask_path.stem}.jpg"
        return f"JPEGImages/{rel}" if multi else rel
