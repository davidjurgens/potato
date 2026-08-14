"""
YOLO / Ultralytics dataset importer.

YOLO is not one file. A dataset is a ``data.yaml`` naming the classes plus a
directory of ``labels/*.txt``, one per image, each line being::

    <class_index> <cx> <cy> <w> <h>              # detection
    <class_index> <x1> <y1> <x2> <y2> ...        # segmentation (polygon)

Two properties make it easy to get subtly wrong, and both are handled here:

* **Coordinates are centre-based**, not top-left. A box is ``cx cy w h`` with
  the centre first, so reading it as ``x y w h`` shifts every annotation by half
  its own size — the kind of error that still looks plausible on screen.
* **Class identity is positional.** The integer index means nothing without
  ``data.yaml``'s ``names``. Import without it and every label is ``class_3``.

Values are already normalized to [0, 1], which is the same space Potato's client
contract uses — but they still go through ``to_client_object`` rather than being
copied across, so there is exactly one definition of the client shape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Extensions we will look for when pairing a label file with its image.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")

#: Assumed when an image file cannot be found or measured. YOLO stores
#: normalized coordinates, so this only affects the recorded pixel dimensions,
#: never the geometry itself.
FALLBACK_SIZE = (1000, 1000)


class YOLOImporter(BaseAnnotationImporter):
    format_name = "yolo"
    description = "YOLO / Ultralytics dataset (data.yaml + labels/*.txt)"
    file_extensions = [".yaml", ".yml", ".txt"]

    def detect(self, data: Any) -> bool:
        """
        A YOLO dataset is a directory, so ``data`` is a dict we assemble in
        :meth:`parse_directory`. Detection keys on that shape.
        """
        return (isinstance(data, dict)
                and "label_files" in data
                and "names" in data)

    # ------------------------------------------------------------------
    # Directory entry point
    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        """
        Read a YOLO dataset rooted at ``root``.

        Accepts either the dataset directory or the ``data.yaml`` inside it.
        """
        options = options or {}
        path = Path(root)
        yaml_path = path if path.is_file() else self._find_data_yaml(path)
        base = yaml_path.parent if yaml_path else path

        names, warnings = self._read_names(yaml_path)

        label_dirs = self._label_dirs(base)
        if not label_dirs:
            raise ValueError(
                f"No labels/ directory found under {base}. A YOLO dataset needs "
                f"one .txt per image; point at the dataset root or its data.yaml."
            )

        label_files: List[Path] = []
        for d in label_dirs:
            label_files.extend(sorted(d.glob("*.txt")))

        return self.parse({"label_files": label_files, "names": names,
                           "root": base, "warnings": warnings}, options)

    @staticmethod
    def _find_data_yaml(root: Path) -> Optional[Path]:
        for candidate in ("data.yaml", "data.yml", "dataset.yaml"):
            if (root / candidate).exists():
                return root / candidate
        found = sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))
        return found[0] if found else None

    @staticmethod
    def _label_dirs(base: Path) -> List[Path]:
        """Every labels/ directory, including the train/val/test splits."""
        dirs = []
        if (base / "labels").is_dir():
            dirs.append(base / "labels")
        # labels/train, labels/val, ... and the split-first layout train/labels.
        dirs.extend(sorted(d for d in base.glob("labels/*") if d.is_dir()))
        dirs.extend(sorted(d for d in base.glob("*/labels") if d.is_dir()))
        return list(dict.fromkeys(dirs))

    def _read_names(self, yaml_path: Optional[Path]):
        """
        Class names from data.yaml, as either a list or an index->name mapping.

        Without them every label becomes ``class_0``, so a missing or
        unreadable data.yaml is a warning the user needs to see rather than a
        silent degradation.
        """
        warnings: List[str] = []
        if yaml_path is None or not yaml_path.exists():
            warnings.append(
                "No data.yaml found: class indices cannot be resolved to names, "
                "so labels are imported as class_0, class_1, ... Rename them in "
                "the generated config, or re-run with the data.yaml present.")
            return {}, warnings

        try:
            import yaml

            with open(yaml_path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception as exc:
            warnings.append(f"Could not read {yaml_path.name}: {exc}")
            return {}, warnings

        raw = doc.get("names")
        if isinstance(raw, dict):
            return {int(k): str(v) for k, v in raw.items()}, warnings
        if isinstance(raw, list):
            return {i: str(v) for i, v in enumerate(raw)}, warnings

        warnings.append(f"{yaml_path.name} has no usable `names` entry.")
        return {}, warnings

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "YOLO import expects a directory. Use parse_directory(), or "
                "pass {'label_files': [...], 'names': {...}}.")

        names: Dict[int, str] = data.get("names") or {}
        root: Path = Path(data.get("root") or ".")
        result = ImportResult(warnings=list(data.get("warnings") or []))
        tools: set = set()
        used_classes: set = set()

        for label_file in data["label_files"]:
            label_file = Path(label_file)
            width, height = self._image_size(label_file, root)
            objects: List[dict] = []

            for lineno, line in enumerate(
                    self._read_lines(label_file, result.warnings), start=1):
                parsed = self._parse_line(
                    line, names, width, height,
                    f"{label_file.name}:{lineno}", result.warnings)
                if parsed is None:
                    continue
                obj, class_index, tool = parsed
                objects.append(obj)
                used_classes.add(class_index)
                tools.add(tool)

            stem = label_file.stem
            image_name = self._image_name(label_file, root) or f"{stem}.jpg"
            result.images.append(ImportedImage(
                instance_id=stem,
                file_name=image_name,
                width=width,
                height=height,
                objects=objects,
                extra={"image_url": apply_url_prefix(image_name, options)},
            ))

        # Only classes that actually appear, in index order, so the generated
        # config is not padded with 79 unused COCO names.
        result.labels = [
            {"name": names.get(i, f"class_{i}"), "label_id": i}
            for i in sorted(used_classes)
        ]
        result.tools = sorted(tools)
        result.summarize(num_warnings=len(result.warnings))
        return result

    @staticmethod
    def _read_lines(path: Path, warnings: List[str]) -> List[str]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError as exc:
            warnings.append(f"Could not read {path.name}: {exc}")
            return []

    def _parse_line(self, line: str, names: Dict[int, str],
                    width: int, height: int, where: str,
                    warnings: List[str]):
        parts = line.split()
        if len(parts) < 5:
            warnings.append(f"{where}: expected at least 5 fields, got {len(parts)}")
            return None

        try:
            class_index = int(float(parts[0]))
            values = [float(v) for v in parts[1:]]
        except ValueError:
            warnings.append(f"{where}: non-numeric field")
            return None

        label = names.get(class_index, f"class_{class_index}")

        # 4 values is a box; more (and even) is a polygon outline.
        if len(values) == 4:
            cx, cy, w, h = values
            # Centre-based -> top-left. Reading these as x/y directly shifts
            # every box by half its own size, which still looks plausible.
            obj = to_client_object(
                "bbox", label, img_w=width, img_h=height,
                bbox=[(cx - w / 2) * width, (cy - h / 2) * height,
                      w * width, h * height],
            )
            return (obj, class_index, "bbox") if obj else None

        if len(values) >= 6 and len(values) % 2 == 0:
            points = [[values[i] * width, values[i + 1] * height]
                      for i in range(0, len(values), 2)]
            obj = to_client_object("polygon", label, img_w=width,
                                   img_h=height, points=points)
            return (obj, class_index, "polygon") if obj else None

        warnings.append(
            f"{where}: {len(values)} coordinates is neither a box (4) nor a "
            f"polygon (an even count >= 6)")
        return None

    # ------------------------------------------------------------------
    # Image pairing
    # ------------------------------------------------------------------

    def _image_path(self, label_file: Path, root: Path) -> Optional[Path]:
        """
        Find the image beside a label file.

        The convention is a parallel tree with ``labels`` swapped for
        ``images``, which is what Ultralytics itself does.
        """
        candidates = []
        swapped = Path(str(label_file.parent).replace("labels", "images", 1))
        candidates.append(swapped)
        candidates.append(label_file.parent)
        candidates.append(root / "images")

        for folder in candidates:
            for ext in IMAGE_EXTENSIONS:
                candidate = folder / f"{label_file.stem}{ext}"
                if candidate.exists():
                    return candidate
        return None

    def _image_name(self, label_file: Path, root: Path) -> Optional[str]:
        found = self._image_path(label_file, root)
        return found.name if found else None

    def _image_size(self, label_file: Path, root: Path):
        """
        Measure the image if we can find it and Pillow is available.

        YOLO coordinates are normalized, so a wrong size never moves an
        annotation relative to its image -- it only makes the recorded pixel
        dimensions wrong. That keeps Pillow genuinely optional.
        """
        path = self._image_path(label_file, root)
        if path is None:
            return FALLBACK_SIZE
        try:
            from PIL import Image

            with Image.open(path) as img:
                return img.width, img.height
        except Exception:
            return FALLBACK_SIZE
