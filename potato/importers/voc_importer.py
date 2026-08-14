"""
Pascal VOC XML importer.

One XML per image::

    <annotation>
      <filename>000001.jpg</filename>
      <size><width>353</width><height>500</height></size>
      <object>
        <name>dog</name>
        <difficult>0</difficult>
        <bndbox><xmin>48</xmin><ymin>240</ymin><xmax>195</xmax><ymax>371</ymax></bndbox>
      </object>
    </annotation>

Two details that are easy to lose:

* **VOC boxes are corners** (``xmin ymin xmax ymax``), not origin-plus-size.
  Treating ``xmax`` as a width produces a box that starts in the right place and
  extends far too far — plausible enough on screen to survive review.
* **VOC is 1-indexed** by its original convention, so a box at ``xmin=1`` is at
  pixel 0. Left as-is by default (a one-pixel shift is well inside annotation
  noise, and silently shifting everything would be worse), but recorded here so
  the choice is visible rather than accidental.

``difficult`` and ``truncated`` flags are carried through as annotation
attributes rather than dropped, because a benchmark that ignores difficult
examples cannot be reproduced if the flag is gone.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)


class VOCImporter(BaseAnnotationImporter):
    format_name = "pascal_voc"
    description = "Pascal VOC XML (one .xml per image)"
    file_extensions = [".xml"]

    def detect(self, data: Any) -> bool:
        """VOC's root element is <annotation> and it carries <object> or <size>."""
        root = self._as_root(data)
        if root is None:
            return False
        if root.tag != "annotation":
            return False
        return root.find("size") is not None or root.find("object") is not None

    @staticmethod
    def _as_root(data: Any):
        if isinstance(data, ET.Element):
            return data
        if isinstance(data, ET.ElementTree):
            return data.getroot()
        if isinstance(data, (str, bytes)):
            try:
                return ET.fromstring(data)
            except ET.ParseError:
                return None
        return None

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        """Read every .xml under ``root`` (including an Annotations/ subdir)."""
        base = Path(root)
        files = sorted(base.glob("*.xml"))
        if not files and (base / "Annotations").is_dir():
            files = sorted((base / "Annotations").glob("*.xml"))
        if not files:
            raise ValueError(f"No VOC .xml files found under {base}")

        merged = ImportResult()
        labels: dict = {}
        tools: set = set()
        for path in files:
            try:
                one = self.parse(ET.parse(path).getroot(), options)
            except ET.ParseError as exc:
                merged.warnings.append(f"{path.name}: malformed XML ({exc})")
                continue
            merged.images.extend(one.images)
            merged.warnings.extend(one.warnings)
            for label in one.labels:
                labels.setdefault(label["name"], label)
            tools.update(one.tools)

        merged.labels = [labels[name] for name in sorted(labels)]
        merged.tools = sorted(tools)
        merged.summarize(num_warnings=len(merged.warnings))
        return merged

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        root = self._as_root(data)
        if root is None or root.tag != "annotation":
            raise ValueError("Not a Pascal VOC <annotation> document")

        result = ImportResult()
        file_name = self._text(root, "filename") or "unknown.jpg"
        width = self._int(root, "size/width", 0)
        height = self._int(root, "size/height", 0)

        if width <= 0 or height <= 0:
            # Without dimensions the corner coordinates cannot be normalized,
            # and guessing would silently misplace every box.
            result.warnings.append(
                f"{file_name}: <size> is missing or zero, so annotations cannot "
                f"be normalized; this image was skipped.")
            return result

        objects: List[dict] = []
        labels: dict = {}
        tools: set = set()

        for node in root.findall("object"):
            name = self._text(node, "name")
            if not name:
                result.warnings.append(f"{file_name}: <object> with no <name>")
                continue

            box = node.find("bndbox")
            if box is None:
                result.warnings.append(
                    f"{file_name}: object '{name}' has no <bndbox>; "
                    f"VOC segmentation masks live in a separate directory and "
                    f"are not read here.")
                continue

            xmin = self._float(box, "xmin", 0.0)
            ymin = self._float(box, "ymin", 0.0)
            xmax = self._float(box, "xmax", 0.0)
            ymax = self._float(box, "ymax", 0.0)
            # Corners, not origin-plus-size.
            w = xmax - xmin
            h = ymax - ymin
            if w <= 0 or h <= 0:
                result.warnings.append(
                    f"{file_name}: object '{name}' has a degenerate box "
                    f"({xmin},{ymin})-({xmax},{ymax})")
                continue

            obj = to_client_object("bbox", name, img_w=width, img_h=height,
                                   bbox=[xmin, ymin, w, h])
            if obj is None:
                continue

            # Kept rather than dropped: a benchmark that excludes `difficult`
            # examples is not reproducible once the flag is gone.
            for flag in ("difficult", "truncated", "occluded"):
                value = self._text(node, flag)
                if value not in (None, ""):
                    try:
                        obj[flag] = int(value)
                    except ValueError:
                        pass
            pose = self._text(node, "pose")
            if pose and pose.lower() != "unspecified":
                obj["pose"] = pose

            objects.append(obj)
            labels.setdefault(name, {"name": name})
            tools.add("bbox")

        result.images.append(ImportedImage(
            instance_id=Path(file_name).stem,
            file_name=file_name,
            width=width,
            height=height,
            objects=objects,
            extra={"image_url": apply_url_prefix(file_name, options)},
        ))
        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize(num_warnings=len(result.warnings))
        return result

    # -- small XML helpers ------------------------------------------------

    @staticmethod
    def _text(node, path: str) -> Optional[str]:
        found = node.find(path)
        return found.text.strip() if found is not None and found.text else None

    def _int(self, node, path: str, default: int) -> int:
        try:
            return int(float(self._text(node, path)))
        except (TypeError, ValueError):
            return default

    def _float(self, node, path: str, default: float) -> float:
        try:
            return float(self._text(node, path))
        except (TypeError, ValueError):
            return default
