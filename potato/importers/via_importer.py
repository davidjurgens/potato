"""
VGG Image Annotator (VIA) project importer.

VIA is the workhorse of small academic labs: one HTML file, no server, a
project saved as a single JSON. Two layouts are in the wild and both are read
here — VIA 2's ``_via_img_metadata`` wrapper, and VIA 1's bare mapping of
``<filename><filesize>`` to image records.

Each region is ``{"shape_attributes": {...}, "region_attributes": {...}}``.
Points to be careful with:

* **The label is not a fixed field.** ``region_attributes`` is whatever the
  project author defined — ``class``, ``type``, ``species``, sometimes several
  at once. The key is taken from ``--via-label-key`` when given, otherwise
  inferred from the project's own ``_via_attributes.region`` definition, and
  the choice is reported. Guessing silently would relabel a whole corpus.
* **Ellipse ``theta`` is in RADIANS**; Potato's client contract stores degrees
  (fabric's convention). Copying the number across leaves a 30° ellipse at
  0.52°, which looks like an axis-aligned ellipse and reads as correct.
* **Polygons and polylines are parallel arrays**, ``all_points_x`` and
  ``all_points_y``. A ragged pair means a truncated export, so it is reported
  rather than zipped to the shorter length.
* **VIA circles have one radius** ``r``, which becomes a circular ellipse.

VIA stores no image dimensions, so absolute pixel coordinates cannot be
normalized without measuring the images. ``--image-dir`` is therefore
effectively required, and its absence is a loud warning, not a silent guess.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import (FALLBACK_SIZE, apply_url_prefix, find_image,
                      probe_image_size, safe_instance_id)
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Attribute keys that most often hold the class, tried in order when the
#: project does not declare its own region attributes.
LIKELY_LABEL_KEYS = ("class", "label", "type", "name", "category", "object")

#: Used when a region carries no usable label attribute at all.
DEFAULT_LABEL = "region"


class VIAImporter(BaseAnnotationImporter):
    format_name = "via"
    description = "VGG Image Annotator (VIA) project JSON"
    file_extensions = [".json"]

    def detect(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if "_via_img_metadata" in data or "_via_settings" in data:
            return True
        # VIA 1: a bare mapping whose values carry filename + regions.
        for value in list(data.values())[:5]:
            if (isinstance(value, dict) and "filename" in value
                    and isinstance(value.get("regions"), (list, dict))):
                return True
        return False

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        import json

        base = Path(root)
        for path in sorted(base.glob("*.json")) + sorted(base.rglob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                continue
            if self.detect(doc):
                opts = dict(options or {})
                opts.setdefault("image_root", str(base))
                return self.parse(doc, opts)
        raise ValueError(f"No VIA project JSON found under {base}")

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a VIA project: expected _via_img_metadata, or a mapping "
                "of image keys to records with filename and regions.")

        metadata = data.get("_via_img_metadata")
        if not isinstance(metadata, dict):
            metadata = {k: v for k, v in data.items()
                        if isinstance(v, dict) and "filename" in v}

        label_key, key_source = self._label_key(data, metadata, options)
        image_root = Path(options.get("image_root") or options.get("image_dir")
                          or ".")

        result = ImportResult()
        labels: Dict[str, dict] = {}
        tools: set = set()
        unmeasured: List[str] = []

        for record in metadata.values():
            if not isinstance(record, dict):
                continue
            file_name = str(record.get("filename") or "").strip()
            if not file_name:
                continue

            size = self._measure(image_root, file_name)
            if size is None:
                unmeasured.append(file_name)
                size = FALLBACK_SIZE
            width, height = size

            objects: List[dict] = []
            for region in self._regions(record):
                obj = self._object(region, width, height, label_key,
                                   file_name, result.warnings)
                if obj is None:
                    continue
                objects.append(obj)
                labels.setdefault(obj["label"], {"name": obj["label"]})
                tools.add(obj["type"])

            result.images.append(ImportedImage(
                instance_id=safe_instance_id(Path(file_name).stem),
                file_name=file_name,
                width=width,
                height=height,
                objects=objects,
                extra={
                    "image_url": apply_url_prefix(file_name, options),
                    **{k: v for k, v in (record.get("file_attributes") or {}).items()
                       if isinstance(k, str)},
                },
            ))

        result.warnings.append(
            f"Region labels were read from the '{label_key}' attribute "
            f"({key_source}). Pass --via-label-key to choose a different one.")
        if unmeasured:
            shown = ", ".join(unmeasured[:3])
            more = f" (+{len(unmeasured) - 3} more)" if len(unmeasured) > 3 else ""
            result.warnings.append(
                f"Could not measure {len(unmeasured)} image(s) — {shown}{more}. "
                f"VIA stores absolute pixel coordinates and no dimensions, so "
                f"those regions were normalized against an assumed "
                f"{FALLBACK_SIZE[0]}x{FALLBACK_SIZE[1]} and will be in the "
                f"wrong place. Re-run with --image-dir and Pillow installed.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize()
        return result

    # ------------------------------------------------------------------

    def _label_key(self, data, metadata, options):
        """Which region attribute holds the class."""
        explicit = options.get("via_label_key")
        if explicit:
            return explicit, "given on the command line"

        declared = ((data.get("_via_attributes") or {}).get("region") or {})
        if isinstance(declared, dict) and declared:
            for candidate in LIKELY_LABEL_KEYS:
                if candidate in declared:
                    return candidate, "declared by the project"
            return sorted(declared)[0], "the project's only region attribute"

        seen: Dict[str, int] = {}
        for record in list(metadata.values())[:50]:
            for region in self._regions(record if isinstance(record, dict) else {}):
                for key in (region.get("region_attributes") or {}):
                    seen[key] = seen.get(key, 0) + 1
        for candidate in LIKELY_LABEL_KEYS:
            if candidate in seen:
                return candidate, "inferred from the regions"
        if seen:
            return max(seen, key=seen.get), "the most common region attribute"
        return DEFAULT_LABEL, "no region attributes found; every region is 'region'"

    @staticmethod
    def _regions(record: dict):
        """VIA 2 stores regions as a list; VIA 1 sometimes as an index->dict."""
        regions = record.get("regions")
        if isinstance(regions, dict):
            return [v for _k, v in sorted(regions.items())
                    if isinstance(v, dict)]
        return [r for r in (regions or []) if isinstance(r, dict)]

    @staticmethod
    def _measure(image_root: Path, file_name: str):
        candidate = image_root / file_name
        if candidate.exists():
            return probe_image_size(candidate)
        found = find_image(image_root, Path(file_name).stem)
        return probe_image_size(found) if found else None

    def _object(self, region, width, height, label_key, file_name, warnings):
        shape = region.get("shape_attributes") or {}
        attrs = region.get("region_attributes") or {}
        kind = str(shape.get("name") or "").lower()

        raw_label = attrs.get(label_key)
        if isinstance(raw_label, dict):
            # VIA checkbox attributes are {"value": true} maps.
            chosen = [k for k, v in raw_label.items() if v]
            raw_label = chosen[0] if chosen else None
        label = str(raw_label).strip() if raw_label not in (None, "") else DEFAULT_LABEL

        def num(key, default=0.0):
            try:
                return float(shape.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        obj = None
        if kind == "rect":
            obj = to_client_object("bbox", label, img_w=width, img_h=height,
                                   bbox=[num("x"), num("y"),
                                         num("width"), num("height")])
        elif kind == "circle":
            r = num("r")
            obj = to_client_object(
                "ellipse", label, img_w=width, img_h=height,
                ellipse={"cx": num("cx"), "cy": num("cy"),
                         "rx": r, "ry": r, "angle": 0.0})
        elif kind == "ellipse":
            obj = to_client_object(
                "ellipse", label, img_w=width, img_h=height,
                ellipse={"cx": num("cx"), "cy": num("cy"),
                         "rx": num("rx"), "ry": num("ry"),
                         # VIA's theta is RADIANS; the client contract is
                         # degrees. Copying it across silently flattens the
                         # rotation to near zero.
                         "angle": math.degrees(num("theta"))})
        elif kind in ("polygon", "polyline"):
            points = self._points(shape, file_name, warnings)
            if points is None:
                return None
            obj_type = "polygon" if kind == "polygon" else "polyline"
            obj = to_client_object(obj_type, label, img_w=width, img_h=height,
                                   points=points)
        elif kind == "point":
            obj = to_client_object("landmark", label, img_w=width, img_h=height,
                                   points=[[num("cx"), num("cy")]])
        elif kind:
            warnings.append(
                f"Unsupported VIA shape '{kind}' in {file_name}; skipped.")
            return None
        else:
            return None

        if obj is None:
            return None
        extra = {k: v for k, v in attrs.items() if k != label_key}
        if extra:
            obj["attributes"] = extra
        return obj

    @staticmethod
    def _points(shape, file_name, warnings):
        xs = shape.get("all_points_x") or []
        ys = shape.get("all_points_y") or []
        if len(xs) != len(ys):
            warnings.append(
                f"Ragged polygon in {file_name}: {len(xs)} x-values against "
                f"{len(ys)} y-values, which means a truncated export. Skipped "
                f"rather than zipped to the shorter one, which would silently "
                f"change the shape.")
            return None
        try:
            return [[float(x), float(y)] for x, y in zip(xs, ys)]
        except (TypeError, ValueError):
            warnings.append(f"Non-numeric polygon in {file_name}; skipped.")
            return None
