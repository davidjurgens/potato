"""
V7 Darwin JSON v2 importer — the direct migration path off V7.

One JSON per item::

    {"version": "2.0",
     "item": {"name": "img.jpg",
              "slots": [{"width": 640, "height": 480}]},
     "annotations": [
       {"name": "car", "bounding_box": {"x": 10, "y": 20, "w": 90, "h": 180}},
       {"name": "road", "polygon": {"paths": [[{"x": 1, "y": 2}, ...]]}},
       {"name": "cell", "ellipse": {"center": {...}, "radius": {...}, "angle": 0}},
       {"name": "tip", "keypoint": {"x": 5, "y": 6}},
       {"name": "lane", "line": {"path": [{"x": .., "y": ..}, ...]}},
       {"name": "scene", "tag": {}}
     ]}

The shape of the annotation object is its own discriminator: there is no
``type`` field, so which key is present *is* the type. Reading it any other way
means guessing.

Two things worth stating:

* **``polygon.paths`` is a list of RINGS, not one outline.** The first is the
  exterior and any others are holes — V7's "complex polygon". Potato's polygon
  type has no hole concept, so the exterior is imported and each dropped hole is
  reported. Silently unioning the rings would fill the holes back in.
* **Item dimensions live in ``item.slots``**, not at the top level, because a V7
  item can have several slots (multi-view / multi-modal). Only the first is read,
  and an item with more than one says so.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)


def _pts(raw) -> List[List[float]]:
    return [[float(p["x"]), float(p["y"])]
            for p in (raw or [])
            if isinstance(p, dict) and "x" in p and "y" in p]


class DarwinImporter(BaseAnnotationImporter):
    format_name = "darwin"
    description = "V7 Darwin JSON v2 (one .json per item)"
    file_extensions = [".json"]

    #: Which annotation key means which Potato tool.
    SHAPE_KEYS = ("bounding_box", "polygon", "complex_polygon", "ellipse",
                  "keypoint", "line", "skeleton", "tag")

    def detect(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        # Darwin v2 always has `item` alongside `annotations`; v1 used `image`.
        if not isinstance(data.get("annotations"), list):
            return False
        return isinstance(data.get("item"), dict) or "dataset" in data

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        files = sorted(base.rglob("*.json"))
        if not files:
            raise ValueError(f"No Darwin .json files found under {base}")

        merged = ImportResult()
        labels: Dict[str, dict] = {}
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

        if not merged.images:
            raise ValueError(
                f"No file under {base} looks like Darwin JSON v2 "
                f"(an object with both `item` and `annotations`).")

        merged.labels = [labels[n] for n in sorted(labels)]
        merged.tools = sorted(tools)
        merged.summarize(num_warnings=len(merged.warnings))
        return merged

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError("Not a Darwin JSON v2 document")

        result = ImportResult()
        item = data.get("item") or {}
        name = item.get("name") or "unknown.jpg"

        slots = item.get("slots") or []
        if len(slots) > 1:
            result.warnings.append(
                f"{name}: the item has {len(slots)} slots (multi-view or "
                f"multi-modal); only the first was imported.")
        slot = slots[0] if slots else {}
        width = int(slot.get("width") or 0)
        height = int(slot.get("height") or 0)

        if width <= 0 or height <= 0:
            result.warnings.append(
                f"{name}: no width/height in item.slots, so coordinates cannot "
                f"be normalized; skipped.")
            return result

        objects: List[dict] = []
        labels: Dict[str, dict] = {}
        tools: set = set()

        for index, ann in enumerate(data.get("annotations") or []):
            if not isinstance(ann, dict):
                continue
            label = ann.get("name")
            if not label:
                result.warnings.append(f"{name}: annotation {index} has no name")
                continue

            converted = self._convert(ann, label, width, height, name,
                                      index, result.warnings)
            if converted is None:
                continue
            obj, tool = converted
            if obj is None:
                continue

            # V7's sub-annotations (text, attributes, instance id) carry the
            # study's actual variables in many projects; dropping them looks
            # like a clean import of half a dataset.
            for key in ("text", "attributes", "instance_id"):
                if ann.get(key) not in (None, "", [], {}):
                    obj[key] = ann[key]

            objects.append(obj)
            labels.setdefault(label, {"name": label})
            tools.add(tool)

        result.images.append(ImportedImage(
            instance_id=Path(name).stem,
            file_name=name,
            width=width,
            height=height,
            objects=objects,
            extra={"image_url": apply_url_prefix(name, options)},
        ))
        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize(num_warnings=len(result.warnings))
        return result

    def _convert(self, ann: dict, label: str, width: int, height: int,
                 name: str, index: int, warnings: List[str]):
        """The present key IS the type; Darwin has no `type` field."""
        if "bounding_box" in ann:
            b = ann["bounding_box"]
            # Origin plus size, like COCO -- unlike CVAT and VOC.
            obj = to_client_object(
                "bbox", label, img_w=width, img_h=height,
                bbox=[float(b.get("x", 0)), float(b.get("y", 0)),
                      float(b.get("w", 0)), float(b.get("h", 0))])
            return (obj, "bbox")

        if "polygon" in ann or "complex_polygon" in ann:
            poly = ann.get("polygon") or ann.get("complex_polygon") or {}
            paths = poly.get("paths")
            if paths is None and poly.get("path"):
                paths = [poly["path"]]
            paths = paths or []
            if not paths:
                warnings.append(f"{name}: polygon {index} ('{label}') has no path")
                return None

            if len(paths) > 1:
                # Rings 1..n are holes. Potato's polygon has no hole concept,
                # and unioning them would FILL the holes rather than preserve
                # them, which is a worse answer than an honest warning.
                warnings.append(
                    f"{name}: '{label}' is a complex polygon with "
                    f"{len(paths) - 1} hole(s); only the exterior ring was "
                    f"imported.")

            points = _pts(paths[0])
            if len(points) < 3:
                warnings.append(
                    f"{name}: polygon {index} ('{label}') has {len(points)} points")
                return None
            return (to_client_object("polygon", label, img_w=width,
                                     img_h=height, points=points), "polygon")

        if "ellipse" in ann:
            e = ann["ellipse"]
            centre = e.get("center") or {}
            radius = e.get("radius") or {}
            rx = float(radius.get("x", 0) or 0)
            ry = float(radius.get("y", rx) or rx)
            if rx <= 0 or ry <= 0:
                warnings.append(f"{name}: degenerate ellipse '{label}'")
                return None
            return (to_client_object(
                "ellipse", label, img_w=width, img_h=height,
                ellipse={"cx": float(centre.get("x", 0)),
                         "cy": float(centre.get("y", 0)),
                         "rx": rx, "ry": ry,
                         "angle": float(e.get("angle", 0) or 0)}), "ellipse")

        if "keypoint" in ann:
            k = ann["keypoint"]
            return (to_client_object(
                "landmark", label, img_w=width, img_h=height,
                points=[[float(k.get("x", 0)), float(k.get("y", 0))]]),
                "landmark")

        if "line" in ann:
            points = _pts((ann["line"] or {}).get("path"))
            if len(points) < 2:
                warnings.append(f"{name}: line {index} ('{label}') has "
                                f"{len(points)} points")
                return None
            return (to_client_object("polyline", label, img_w=width,
                                     img_h=height, points=points), "polyline")

        if "skeleton" in ann:
            nodes = (ann["skeleton"] or {}).get("nodes") or []
            keypoints = []
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                # V7 marks an unplaced node with occluded=true; map that onto
                # COCO's visibility flags so the ordering stays meaningful.
                visible = 1 if node.get("occluded") else 2
                keypoints.append([float(node.get("x", 0)),
                                  float(node.get("y", 0)), visible])
            if not keypoints:
                warnings.append(f"{name}: skeleton '{label}' has no nodes")
                return None
            return (to_client_object(
                "keypoint_set", label, img_w=width, img_h=height,
                keypoints=keypoints, skeleton=label), "keypoint_set")

        if "tag" in ann:
            # An image-level tag is a classification, not geometry. Reported
            # rather than dropped so the count reconciles against V7's.
            warnings.append(
                f"{name}: '{label}' is an image-level tag, which is a "
                f"classification rather than a region; add a radio or "
                f"multiselect schema for it.")
            return None

        warnings.append(
            f"{name}: annotation {index} ('{label}') has no recognised shape "
            f"key (expected one of {', '.join(self.SHAPE_KEYS)})")
        return None
