"""
KITTI 2D object-detection label importer.

A KITTI dataset is a directory of ``label_2/*.txt``, one per image, each line
being fifteen space-separated fields::

    type truncated occluded alpha  x1 y1 x2 y2  h w l  x y z  ry  [score]
     0      1         2       3    4  5  6  7   8 9 10 11 12 13  14   15

Three things make this easy to get subtly wrong, and all three are handled:

* **The box is corners, not origin+size.** Fields 4-7 are
  ``left top right bottom`` in absolute pixels. Reading them as ``x y w h``
  produces a box that starts in the right place and extends to roughly double
  the correct size — plausible enough on screen to survive review.
* **Coordinates are absolute**, so the image's real pixel dimensions are
  required to normalize. KITTI ships no width/height anywhere in the label
  file, so they are read from the image; when that is impossible the import
  says so rather than quietly assuming a size and skewing every box.
* **``DontCare`` is not a class.** KITTI uses it to mark regions excluded from
  evaluation — usually distant or ambiguous objects. It is imported under its
  own label so the exclusion survives, but it is never silently folded in with
  real objects.

The 3D fields (dimensions, location, rotation) describe a cuboid in camera
coordinates, which needs the calibration matrices and a 3D viewer to be
editable. They are preserved verbatim in each object's ``attributes`` so a
later 3D pass can use them, and the import reports that they are read-only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import FALLBACK_SIZE, apply_url_prefix, find_image, probe_image_size
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: KITTI's exclusion marker. Not an object class.
DONT_CARE = "DontCare"

#: Field indices, named so the corner/origin confusion cannot recur.
_TYPE, _TRUNCATED, _OCCLUDED, _ALPHA = 0, 1, 2, 3
_X1, _Y1, _X2, _Y2 = 4, 5, 6, 7

#: Occlusion codes, per the KITTI devkit readme.
OCCLUSION_LEVELS = {0: "fully_visible", 1: "partly_occluded",
                    2: "largely_occluded", 3: "unknown"}


class KITTIImporter(BaseAnnotationImporter):
    format_name = "kitti"
    description = "KITTI 2D object detection (label_2/*.txt)"
    file_extensions = [".txt"]

    def detect(self, data: Any) -> bool:
        """KITTI is a directory format; ``data`` is the dict parse_directory builds."""
        return isinstance(data, dict) and "kitti_label_files" in data

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        label_dir = self._label_dir(base)
        if label_dir is None:
            raise ValueError(
                f"No KITTI label directory found under {base}. Expected "
                f"label_2/ (or label/, training/label_2/) holding one .txt "
                f"per image.")
        files = sorted(label_dir.glob("*.txt"))
        if not files:
            raise ValueError(f"{label_dir} contains no .txt label files")
        return self.parse({"kitti_label_files": files, "root": base}, options)

    @staticmethod
    def _label_dir(base: Path) -> Optional[Path]:
        if base.is_file():
            return base.parent
        for candidate in ("label_2", "label", "labels",
                          "training/label_2", "training/label"):
            path = base / candidate
            if path.is_dir():
                return path
        return base if list(base.glob("*.txt")) else None

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a KITTI dataset. Point --input at the directory holding "
                "label_2/, not at a single file.")

        files: List[Path] = list(data["kitti_label_files"])
        root: Path = Path(data.get("root") or ".")

        result = ImportResult()
        labels: Dict[str, dict] = {}
        unmeasured: List[str] = []
        has_3d = False

        for path in files:
            stem = path.stem
            image_path = find_image(root, stem) or find_image(
                root / "image_2", stem) or find_image(root / "training", stem)
            size = probe_image_size(image_path) if image_path else None
            if size is None:
                unmeasured.append(stem)
                size = FALLBACK_SIZE
            width, height = size

            objects: List[dict] = []
            for lineno, raw in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                fields = raw.split()
                if not fields:
                    continue
                if len(fields) < 8:
                    result.warnings.append(
                        f"{path.name}:{lineno} has {len(fields)} fields; a "
                        f"KITTI line needs at least 8. Skipped.")
                    continue

                obj = self._object(fields, width, height, path.name, lineno,
                                   result.warnings)
                if obj is None:
                    continue
                if len(fields) >= 15:
                    has_3d = True
                objects.append(obj)
                labels.setdefault(obj["label"], {"name": obj["label"]})

            file_name = image_path.name if image_path else f"{stem}.png"
            result.images.append(ImportedImage(
                instance_id=stem,
                file_name=file_name,
                width=width,
                height=height,
                objects=objects,
                extra={"image_url": apply_url_prefix(file_name, options)},
            ))

        if unmeasured:
            shown = ", ".join(unmeasured[:3])
            more = f" (+{len(unmeasured) - 3} more)" if len(unmeasured) > 3 else ""
            result.warnings.append(
                f"Could not measure {len(unmeasured)} image(s) — {shown}{more}. "
                f"KITTI boxes are absolute pixels, so they were normalized "
                f"against an assumed {FALLBACK_SIZE[0]}x{FALLBACK_SIZE[1]} and "
                f"will be in the wrong place. Re-run with --image-dir pointing "
                f"at image_2/, with Pillow installed.")
        if has_3d:
            result.warnings.append(
                "3D fields (dimensions, location, rotation_y) were preserved on "
                "each object's attributes but are not editable: they are in "
                "camera coordinates and need the calib/ matrices plus a 3D "
                "viewer. Only the 2D box is annotatable.")
        if DONT_CARE in labels:
            result.warnings.append(
                f"{DONT_CARE} regions were imported under their own label. They "
                f"mark areas KITTI excludes from evaluation, not objects — keep "
                f"them separate when exporting.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = ["bbox"]
        result.summarize()
        return result

    # ------------------------------------------------------------------

    def _object(self, fields, width, height, file_name, lineno, warnings):
        label = fields[_TYPE]
        try:
            x1, y1 = float(fields[_X1]), float(fields[_Y1])
            x2, y2 = float(fields[_X2]), float(fields[_Y2])
        except ValueError:
            warnings.append(f"{file_name}:{lineno} has a non-numeric box. Skipped.")
            return None

        # Corners, not origin+size.
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            warnings.append(
                f"{file_name}:{lineno} box has non-positive extent "
                f"({w:.1f}x{h:.1f}). Skipped.")
            return None

        obj = to_client_object("bbox", label, img_w=width, img_h=height,
                               bbox=[x1, y1, w, h])
        if obj is None:
            return None

        attributes: Dict[str, Any] = {}
        try:
            attributes["truncated"] = float(fields[_TRUNCATED])
            occluded = int(float(fields[_OCCLUDED]))
            attributes["occluded"] = OCCLUSION_LEVELS.get(occluded, str(occluded))
            attributes["alpha"] = float(fields[_ALPHA])
        except (ValueError, IndexError):
            pass

        if len(fields) >= 15:
            try:
                attributes["dimensions_hwl"] = [float(v) for v in fields[8:11]]
                attributes["location_xyz"] = [float(v) for v in fields[11:14]]
                attributes["rotation_y"] = float(fields[14])
            except ValueError:
                pass
        if len(fields) >= 16:
            try:
                attributes["score"] = float(fields[15])
            except ValueError:
                pass

        if attributes:
            obj["attributes"] = attributes
        return obj
