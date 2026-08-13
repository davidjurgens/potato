"""
COCO JSON Importer

Reads a stock COCO annotation file -- every segmentation encoding, no
preprocessing -- into Potato's client annotation shape.

The four encodings that appear in real COCO files:

===============================================  ==========================
``segmentation: [[x1, y1, x2, y2, ...]]``        polygon (one ring)
``segmentation: [[...], [...]]``                 polygon (multi-ring/holes)
``segmentation: {"counts": [ints], "size": ...}``  uncompressed RLE
``segmentation: {"counts": "ascii", "size": ...}`` compressed RLE
===============================================  ==========================

plus bbox-only annotations (``segmentation: []`` or absent) and ``keypoints``.

Crowd handling is the differentiator. Canonical COCO pairs ``iscrowd=1`` with
RLE, and V7's importer skips those annotations outright ("Darwin does not
support import of COCO crowd annotations"), so a stock file silently loses
exactly those instances. Here, crowd regions are merged per label into one
mask -- COCO permits at most one crowd annotation per category per image, and a
crowd region is already an unlabeled blob -- and re-export as ``iscrowd=1``.
Non-crowd RLE keeps a per-image instance index so N instances round trip as N
annotations.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from potato.export.cv_utils import (
    coco_rle_to_rle,
    decode_rle,
    rle_to_polygons,
    to_client_object,
)

from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Distinct, reasonably separable colors for generated label configs.
DEFAULT_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#808080", "#ffe119", "#00a0a0",
]


def _color_for(index: int) -> str:
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


def _merge_rle(a: dict, b: dict, width: int, height: int) -> dict:
    """Bitwise-OR two Potato RLE masks of the same size."""
    left = decode_rle(a, width, height)
    right = decode_rle(b, width, height)
    merged = [1 if (left[i] or right[i]) else 0 for i in range(width * height)]

    counts: List[int] = []
    current, run = 0, 0
    for v in merged:
        if v == current:
            run += 1
        else:
            counts.append(run)
            current = 1 - current
            run = 1
    counts.append(run)
    return {"counts": counts, "size": [height, width]}


class COCOImporter(BaseAnnotationImporter):
    format_name = "coco"
    description = (
        "COCO JSON object detection/segmentation "
        "(polygons, uncompressed RLE, compressed RLE, crowd regions, keypoints)"
    )
    file_extensions = [".json"]

    def detect(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        if not isinstance(data.get("images"), list):
            return False
        if not isinstance(data.get("annotations"), list):
            return False
        images = data["images"]
        if not images:
            # An empty-but-well-formed COCO file still has categories.
            return isinstance(data.get("categories"), list)
        first = images[0]
        return isinstance(first, dict) and "id" in first and "file_name" in first

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    def parse(self, data: Any,
              options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not isinstance(data, dict):
            raise ValueError("COCO input must be a JSON object")

        rle_as_polygon = bool(options.get("rle_as_polygon", False))
        merge_crowd = options.get("merge_crowd", True)
        want_keypoints = bool(options.get("keypoints", False))
        url_prefix = options.get("image_url_prefix") or ""

        warnings: List[str] = []
        result = ImportResult(warnings=warnings)

        labels, label_names, keypoint_names = self._build_labels(data)
        result.labels = labels

        images = {}
        for img in data.get("images", []):
            if not isinstance(img, dict) or "id" not in img:
                continue
            images[img["id"]] = img

        by_image: Dict[Any, List[dict]] = {}
        for ann in data.get("annotations", []):
            if isinstance(ann, dict) and "image_id" in ann:
                by_image.setdefault(ann["image_id"], []).append(ann)

        tools: set = set()
        multi_ring_warned = False

        for image_id, img in images.items():
            width = int(img.get("width") or 0)
            height = int(img.get("height") or 0)
            file_name = str(img.get("file_name") or "")

            if width <= 0 or height <= 0:
                raise ValueError(
                    f"Image '{file_name or image_id}' has no usable width/height "
                    f"in images[] (got {img.get('width')!r}x{img.get('height')!r}). "
                    f"COCO coordinates are absolute pixels, so they cannot be "
                    f"normalized without the image size. Fix the images[] entry, "
                    f"or re-run with --image-dir so the sizes can be read from "
                    f"the files."
                )

            objects: List[dict] = []
            # label -> merged crowd mask, so one crowd region per class per image
            crowd_masks: Dict[str, dict] = {}
            instance_counter: Dict[str, int] = {}

            for ann in by_image.get(image_id, []):
                label = label_names.get(ann.get("category_id"))
                if label is None:
                    warnings.append(
                        f"Annotation {ann.get('id')} references unknown "
                        f"category_id {ann.get('category_id')!r}; skipping"
                    )
                    continue

                color = self._label_color(labels, label)
                is_crowd = int(ann.get("iscrowd", 0) or 0) == 1
                seg = ann.get("segmentation")

                made, ring_warning = self._convert_segmentation(
                    ann, seg, label, color, width, height,
                    is_crowd=is_crowd,
                    merge_crowd=bool(merge_crowd),
                    rle_as_polygon=rle_as_polygon,
                    crowd_masks=crowd_masks,
                    instance_counter=instance_counter,
                    tools=tools,
                    warnings=warnings,
                )
                if ring_warning and not multi_ring_warned:
                    warnings.append(
                        "Multi-ring polygon segmentations were split into one "
                        "polygon per ring; holes become separate shapes"
                    )
                    multi_ring_warned = True
                objects.extend(made)

                if want_keypoints and ann.get("keypoints"):
                    objects.extend(self._convert_keypoints(
                        ann, label, color, width, height,
                        keypoint_names.get(ann.get("category_id")) or [],
                        tools,
                    ))

            # Emit the merged crowd masks, one per label.
            for label, rle in crowd_masks.items():
                obj = to_client_object(
                    "mask", label, self._label_color(labels, label),
                    img_w=width, img_h=height, rle=rle, iscrowd=1,
                )
                if obj:
                    objects.append(obj)
                    tools.update({"brush", "eraser", "fill"})

            instance_id = str(img.get("id"))
            image_url = file_name
            if url_prefix:
                image_url = url_prefix.rstrip("/") + "/" + file_name.lstrip("/")

            result.images.append(ImportedImage(
                instance_id=instance_id,
                file_name=file_name,
                width=width,
                height=height,
                objects=objects,
                extra={"image_url": image_url},
            ))

        result.tools = [
            t for t in ("bbox", "polygon", "brush", "eraser", "fill", "landmark")
            if t in tools
        ] or ["bbox"]

        result.stats = {
            "num_images": len(result.images),
            "num_annotations": result.num_objects,
            "num_categories": len(labels),
            "num_warnings": len(warnings),
        }
        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label_color(labels: List[dict], name: str) -> str:
        for label in labels:
            if label.get("name") == name:
                return label.get("color", "")
        return ""

    def _build_labels(self, data: dict) -> Tuple[List[dict], Dict[Any, str],
                                                 Dict[Any, List[str]]]:
        """Build label configs from ``categories[]``, preserving sparse IDs."""
        labels: List[dict] = []
        by_id: Dict[Any, str] = {}
        keypoint_names: Dict[Any, List[str]] = {}

        for index, cat in enumerate(data.get("categories", []) or []):
            if not isinstance(cat, dict):
                continue
            name = str(cat.get("name") or "").strip()
            if not name:
                continue
            cat_id = cat.get("id")
            by_id[cat_id] = name
            label = {"name": name, "color": _color_for(index)}
            if cat_id is not None:
                # Preserved so the exporter can emit the original (often
                # sparse -- COCO 2017 runs 1..90 with gaps) category IDs.
                label["label_id"] = cat_id
            if cat.get("supercategory"):
                label["supercategory"] = cat["supercategory"]
            labels.append(label)
            if cat.get("keypoints"):
                keypoint_names[cat_id] = list(cat["keypoints"])

        return labels, by_id, keypoint_names

    def _convert_segmentation(self, ann: dict, seg: Any, label: str, color: str,
                              width: int, height: int, *, is_crowd: bool,
                              merge_crowd: bool, rle_as_polygon: bool,
                              crowd_masks: Dict[str, dict],
                              instance_counter: Dict[str, int],
                              tools: set,
                              warnings: List[str]) -> Tuple[List[dict], bool]:
        """Convert one COCO annotation's geometry. Returns (objects, saw_multi_ring)."""
        objects: List[dict] = []
        multi_ring = False

        # --- polygon list -------------------------------------------------
        if isinstance(seg, list) and seg:
            rings = [r for r in seg if isinstance(r, (list, tuple)) and len(r) >= 6]
            if not rings:
                warnings.append(
                    f"Annotation {ann.get('id')} has a polygon segmentation with "
                    f"fewer than 3 points; falling back to its bbox"
                )
            else:
                if len(rings) > 1:
                    multi_ring = True
                for ring in rings:
                    points = [[float(ring[i]), float(ring[i + 1])]
                              for i in range(0, len(ring) - 1, 2)]
                    obj = to_client_object(
                        "polygon", label, color, img_w=width, img_h=height,
                        points=points, iscrowd=1 if is_crowd else 0,
                    )
                    if obj:
                        objects.append(obj)
                        tools.add("polygon")
                if objects:
                    return objects, multi_ring

        # --- RLE ----------------------------------------------------------
        elif isinstance(seg, dict) and seg.get("counts") is not None:
            try:
                rle = coco_rle_to_rle(seg)
            except (ValueError, TypeError) as exc:
                warnings.append(
                    f"Annotation {ann.get('id')} has an undecodable RLE "
                    f"segmentation ({exc}); falling back to its bbox"
                )
                rle = None

            if rle is not None:
                if rle_as_polygon:
                    rings = rle_to_polygons(rle, width, height)
                    if rings:
                        warnings.append(
                            f"Annotation {ann.get('id')}: RLE traced to "
                            f"{len(rings)} polygon(s) at the caller's request. "
                            f"Holes are dropped and the contour will not "
                            f"re-rasterize to the source mask"
                        )
                        for ring in rings:
                            obj = to_client_object(
                                "polygon", label, color,
                                img_w=width, img_h=height, points=ring,
                                iscrowd=1 if is_crowd else 0,
                            )
                            if obj:
                                objects.append(obj)
                                tools.add("polygon")
                        return objects, multi_ring
                    warnings.append(
                        f"Annotation {ann.get('id')}: RLE could not be traced to "
                        f"a polygon; kept as a mask"
                    )
                if is_crowd and merge_crowd:
                    existing = crowd_masks.get(label)
                    crowd_masks[label] = (
                        _merge_rle(existing, rle, width, height)
                        if existing else rle
                    )
                    return [], multi_ring

                instance = instance_counter.get(label, 0)
                instance_counter[label] = instance + 1
                obj = to_client_object(
                    "mask", label, color, img_w=width, img_h=height, rle=rle,
                    instance=instance, iscrowd=1 if is_crowd else 0,
                )
                if obj:
                    objects.append(obj)
                    tools.update({"brush", "eraser", "fill"})
                return objects, multi_ring

        # --- bbox fallback -------------------------------------------------
        bbox = ann.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            obj = to_client_object(
                "bbox", label, color, img_w=width, img_h=height,
                bbox=[float(b) for b in bbox[:4]],
                iscrowd=1 if is_crowd else 0,
            )
            if obj:
                objects.append(obj)
                tools.add("bbox")
        elif not objects:
            warnings.append(
                f"Annotation {ann.get('id')} has neither usable segmentation "
                f"nor bbox; skipping"
            )

        return objects, multi_ring

    def _convert_keypoints(self, ann: dict, label: str, color: str,
                           width: int, height: int,
                           keypoint_names: List[str],
                           tools: set) -> List[dict]:
        """COCO keypoints -> one landmark per visible point."""
        flat = ann.get("keypoints") or []
        objects: List[dict] = []
        for i in range(0, len(flat) - 2, 3):
            x, y, v = flat[i], flat[i + 1], flat[i + 2]
            if not v:  # v == 0 means "not labeled"
                continue
            idx = i // 3
            name = keypoint_names[idx] if idx < len(keypoint_names) else str(idx)
            obj = to_client_object(
                "landmark", f"{label}:{name}", color,
                img_w=width, img_h=height, points=[[float(x), float(y)]],
            )
            if obj:
                objects.append(obj)
                tools.add("landmark")
        return objects
