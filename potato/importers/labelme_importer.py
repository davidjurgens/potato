"""
LabelMe JSON importer.

One JSON per image::

    {"version": "5.2.1", "imagePath": "img.jpg",
     "imageWidth": 640, "imageHeight": 480,
     "imageData": "<base64, optional and large>",
     "shapes": [{"label": "cat", "shape_type": "polygon",
                 "points": [[x, y], ...], "group_id": null,
                 "flags": {}}]}

LabelMe is common in academic labs because it is a desktop tool that produces a
plain file per image, so it is a frequent migration source.

Two things worth knowing:

* **``shape_type`` carries real meaning.** ``rectangle`` stores two *opposite
  corners*, not four; ``circle`` stores centre and a point on the rim, so the
  radius is a distance rather than a stored value. Reading either as a generic
  polygon produces a two-point shape with no area.
* **``imageData`` is the whole image, base64-encoded, inline.** It is ignored
  here: keeping it would multiply the size of the generated project by the size
  of the corpus for no gain, since the annotation UI loads images by URL.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)


class LabelMeImporter(BaseAnnotationImporter):
    format_name = "labelme"
    description = "LabelMe JSON (one .json per image)"
    file_extensions = [".json"]

    def detect(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        # `shapes` alone is too generic; pair it with LabelMe's image fields.
        if not isinstance(data.get("shapes"), list):
            return False
        return any(k in data for k in
                   ("imagePath", "imageWidth", "imageData", "version"))

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        files = sorted(base.glob("*.json"))
        if not files:
            raise ValueError(f"No LabelMe .json files found under {base}")

        merged = ImportResult()
        labels: dict = {}
        tools: set = set()
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError) as exc:
                merged.warnings.append(f"{path.name}: unreadable ({exc})")
                continue
            if not self.detect(doc):
                continue
            one = self.parse(doc, options)
            merged.images.extend(one.images)
            merged.warnings.extend(one.warnings)
            for label in one.labels:
                labels.setdefault(label["name"], label)
            tools.update(one.tools)

        merged.labels = [labels[n] for n in sorted(labels)]
        merged.tools = sorted(tools)
        merged.summarize(num_warnings=len(merged.warnings))
        return merged

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError("Not a LabelMe document")

        result = ImportResult()
        file_name = data.get("imagePath") or "unknown.jpg"
        width = int(data.get("imageWidth") or 0)
        height = int(data.get("imageHeight") or 0)

        if width <= 0 or height <= 0:
            result.warnings.append(
                f"{file_name}: imageWidth/imageHeight missing, so coordinates "
                f"cannot be normalized; this image was skipped.")
            return result

        objects: List[dict] = []
        labels: dict = {}
        tools: set = set()

        for index, shape in enumerate(data.get("shapes") or []):
            if not isinstance(shape, dict):
                continue
            label = shape.get("label")
            if not label:
                result.warnings.append(f"{file_name}: shape {index} has no label")
                continue

            points = [[float(p[0]), float(p[1])]
                      for p in (shape.get("points") or [])
                      if isinstance(p, (list, tuple)) and len(p) >= 2]
            if not points:
                result.warnings.append(
                    f"{file_name}: shape {index} ('{label}') has no points")
                continue

            shape_type = (shape.get("shape_type") or "polygon").lower()
            obj, tool = self._convert(shape_type, label, points,
                                      width, height, file_name, index,
                                      result.warnings)
            if obj is None:
                continue

            # group_id is LabelMe's instance identifier: several shapes sharing
            # one id are parts of the same object.
            group_id = shape.get("group_id")
            if group_id is not None:
                obj["instance"] = int(group_id)

            objects.append(obj)
            labels.setdefault(label, {"name": label})
            tools.add(tool)

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

    def _convert(self, shape_type: str, label: str, points: List[List[float]],
                 width: int, height: int, file_name: str, index: int,
                 warnings: List[str]):
        """Map a LabelMe shape_type onto a Potato annotation type."""
        if shape_type == "rectangle":
            # TWO opposite corners, not four. min/max rather than points[0]
            # and points[1] directly, because the corners may be given in any
            # order depending on which way the user dragged.
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            obj = to_client_object("bbox", label, img_w=width, img_h=height,
                                   bbox=[x0, y0, x1 - x0, y1 - y0])
            return (obj, "bbox")

        if shape_type == "circle":
            # Centre plus a point on the rim: the radius is the distance
            # between them, not a stored field.
            if len(points) < 2:
                warnings.append(
                    f"{file_name}: circle {index} needs a centre and a rim point")
                return (None, "")
            (cx, cy), (rx, ry) = points[0], points[1]
            radius = math.hypot(rx - cx, ry - cy)
            obj = to_client_object(
                "ellipse", label, img_w=width, img_h=height,
                ellipse={"cx": cx, "cy": cy, "rx": radius, "ry": radius,
                         "angle": 0.0})
            return (obj, "ellipse")

        if shape_type == "point":
            obj = to_client_object("landmark", label, img_w=width,
                                   img_h=height, points=points[:1])
            return (obj, "landmark")

        if shape_type in ("line", "linestrip"):
            obj = to_client_object("polyline", label, img_w=width,
                                   img_h=height, points=points)
            return (obj, "polyline")

        if shape_type in ("polygon", "mask"):
            if len(points) < 3:
                warnings.append(
                    f"{file_name}: polygon {index} ('{label}') has "
                    f"{len(points)} points; at least 3 are needed")
                return (None, "")
            obj = to_client_object("polygon", label, img_w=width,
                                   img_h=height, points=points)
            return (obj, "polygon")

        warnings.append(
            f"{file_name}: shape {index} has unsupported shape_type "
            f"'{shape_type}'; imported as a polygon")
        obj = to_client_object("polygon", label, img_w=width, img_h=height,
                               points=points)
        return (obj, "polygon")
