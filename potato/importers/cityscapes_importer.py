"""
Cityscapes polygon importer (``*_gtFine_polygons.json``).

One JSON per image::

    {"imgHeight": 1024, "imgWidth": 2048,
     "objects": [{"label": "road",  "polygon": [[x, y], ...]},
                 {"label": "car",   "polygon": [[x, y], ...]}]}

Two properties of the format carry meaning that is easy to throw away:

* **Object order is painter's order** — back to front. A later polygon occludes
  an earlier one, which is how the label images are rasterized. Sorting the
  objects, or rendering them in an arbitrary order, changes what the scene
  means, so the source order is preserved and recorded on each object.
* **Labels ending in ``group``** (``cargroup``, ``persongroup``) are crowd
  regions: a single polygon covering several instances that were not worth
  separating. They are imported with ``iscrowd`` set, so exporting to COCO
  reproduces the distinction instead of asserting one giant car.

Cityscapes also ships rasterized ``*_labelIds.png`` / ``*_instanceIds.png``.
Those are derived from these polygons, so the polygons are the editable
source and what this importer reads; the PNGs need no separate path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Cityscapes' suffix convention. The image beside a polygons file swaps the
#: annotation suffix for this one.
POLYGON_SUFFIX = "_gtFine_polygons.json"
COARSE_SUFFIX = "_gtCoarse_polygons.json"
IMAGE_SUFFIX = "_leftImg8bit.png"

#: Labels the benchmark ignores in evaluation; kept, but flagged.
VOID_LABELS = {"unlabeled", "ego vehicle", "rectification border",
               "out of roi", "static", "dynamic", "ground", "license plate"}


class CityscapesImporter(BaseAnnotationImporter):
    format_name = "cityscapes"
    description = "Cityscapes polygons (*_gtFine_polygons.json)"
    file_extensions = [".json"]

    def detect(self, data: Any) -> bool:
        """
        A Cityscapes document has image dimensions plus an ``objects`` list
        whose entries carry a ``polygon``. COCO also has ``objects``-adjacent
        keys, so the polygon key is what makes this unambiguous.
        """
        if isinstance(data, dict) and "cityscapes_files" in data:
            return True
        if not isinstance(data, dict):
            return False
        if "imgHeight" not in data or "imgWidth" not in data:
            return False
        objects = data.get("objects")
        if not isinstance(objects, list):
            return False
        return not objects or any(
            isinstance(o, dict) and "polygon" in o for o in objects)

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        files = sorted(base.rglob(f"*{POLYGON_SUFFIX}"))
        files += sorted(base.rglob(f"*{COARSE_SUFFIX}"))
        if not files:
            # A directory of plain .json that still parse as Cityscapes.
            files = [p for p in sorted(base.rglob("*.json"))
                     if self._is_cityscapes_file(p)]
        if not files:
            raise ValueError(
                f"No Cityscapes polygon files under {base}. Expected "
                f"*{POLYGON_SUFFIX} (or *{COARSE_SUFFIX}).")
        return self.parse({"cityscapes_files": files, "root": base}, options)

    def _is_cityscapes_file(self, path: Path) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return self.detect(json.load(fh))
        except (OSError, ValueError):
            return False

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if isinstance(data, dict) and "cityscapes_files" in data:
            documents = []
            for path in data["cityscapes_files"]:
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        documents.append((path, json.load(fh)))
                except (OSError, ValueError) as exc:
                    logger.warning("Skipping %s: %s", path, exc)
            root = Path(data.get("root") or ".")
        elif self.detect(data):
            documents = [(Path("image.json"), data)]
            root = Path(".")
        else:
            raise ValueError(
                "Not a Cityscapes polygons document: expected imgWidth, "
                "imgHeight and an objects[] list of polygons.")

        result = ImportResult()
        labels: Dict[str, dict] = {}
        num_crowd = 0
        num_void = 0

        for path, doc in documents:
            width = int(doc.get("imgWidth") or 0)
            height = int(doc.get("imgHeight") or 0)
            if width <= 0 or height <= 0:
                result.warnings.append(
                    f"{path.name} has no usable imgWidth/imgHeight; skipped.")
                continue

            objects: List[dict] = []
            for order, raw in enumerate(doc.get("objects") or []):
                if not isinstance(raw, dict):
                    continue
                label = str(raw.get("label") or "").strip()
                polygon = raw.get("polygon") or []
                points = [[float(p[0]), float(p[1])] for p in polygon
                          if isinstance(p, (list, tuple)) and len(p) >= 2]
                if not label or len(points) < 3:
                    continue

                is_crowd = label.endswith("group")
                obj = to_client_object(
                    "polygon", label, img_w=width, img_h=height,
                    points=points, iscrowd=1 if is_crowd else 0)
                if obj is None:
                    continue

                # Painter's order is semantic: later polygons occlude earlier
                # ones. Preserve the index so it can be exported faithfully.
                obj["attributes"] = {"draw_order": order}
                if raw.get("deleted"):
                    obj["attributes"]["deleted"] = True
                num_crowd += int(is_crowd)
                num_void += int(label in VOID_LABELS)
                objects.append(obj)
                labels.setdefault(label, {"name": label})

            stem = self._image_stem(path)
            file_name = f"{stem}{IMAGE_SUFFIX}"
            result.images.append(ImportedImage(
                instance_id=safe_instance_id(stem),
                file_name=file_name,
                width=width,
                height=height,
                objects=objects,
                extra={
                    "image_url": apply_url_prefix(file_name, options),
                    "city": path.parent.name,
                },
            ))

        if num_crowd:
            result.warnings.append(
                f"{num_crowd} polygon(s) have a 'group' label, which Cityscapes "
                f"uses for regions covering several instances that were not "
                f"separated. They carry iscrowd=1, so a COCO export keeps the "
                f"distinction rather than claiming one large object.")
        if num_void:
            result.warnings.append(
                f"{num_void} polygon(s) use void labels ({', '.join(sorted(VOID_LABELS)[:3])}, "
                f"...) that the benchmark excludes from evaluation. They were "
                f"imported so the scene stays complete.")
        result.warnings.append(
            "Object order is painter's order (back to front) and is preserved "
            "in attributes.draw_order. Cityscapes rasterizes its label images "
            "in that order, so re-ordering changes the scene.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = ["polygon"]
        result.summarize()
        return result

    @staticmethod
    def _image_stem(path: Path) -> str:
        name = path.name
        for suffix in (POLYGON_SUFFIX, COARSE_SUFFIX):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return path.stem
