"""
Run every aggregation over a project's annotation records.

Input is the export pipeline's record list (``ExportContext.annotations``):
``{"instance_id", "user_id", "labels": {scheme: {label: value}},
"image_annotations": {scheme: [client objects]}, "_changes": [...]}``.
Image objects are read the way the browser stores them (``coordinates`` as
fractions of the image); objects in the older flat pixel shape need the image
size and are skipped with a warning without it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .config import ConsensusSettings
from .questions import (CATEGORICAL_TYPES, NUMERIC_TYPES, categorical_consensus,
                        gather_answers, numeric_consensus)

#: image_annotation object types the point and box consensus read.
POINT_TYPES = {"landmark"}
BOX_TYPES = {"bbox"}


def aggregatable_schemes(schemas: Sequence[Mapping[str, Any]],
                         settings: ConsensusSettings) -> List[Mapping[str, Any]]:
    supported = set(CATEGORICAL_TYPES) | NUMERIC_TYPES | {"image_annotation"}
    chosen = []
    for scheme in schemas or []:
        if not isinstance(scheme, Mapping) or not scheme.get("name"):
            continue
        if settings.schemes is not None and scheme["name"] not in settings.schemes:
            continue
        if scheme.get("annotation_type") in supported:
            chosen.append(scheme)
    return chosen


def _image_size(item: Optional[dict], config: Any,
                cache: Dict[str, Optional[Tuple[float, float]]],
                instance_id: str) -> Optional[Tuple[float, float]]:
    if instance_id in cache:
        return cache[instance_id]
    size = None
    if isinstance(item, dict):
        from potato.export.cv_utils import get_image_dimensions
        try:
            w, h = get_image_dimensions(item, config=config)
        except Exception:
            w, h = 0, 0
        if w and h and w > 0 and h > 0:
            size = (float(w), float(h))
    cache[instance_id] = size
    return size


def _fractions(obj: Mapping[str, Any], size: Optional[Tuple[float, float]]):
    """``("point", (x, y))`` / ``("box", [x, y, w, h])`` in image fractions,
    ``(None, reason)`` when unreadable."""
    from potato.export.cv_utils import normalize_annotation_object

    kind = obj.get("type")
    stored_as_fraction = obj.get("coordinates") is not None
    if not stored_as_fraction and not size:
        return None, "unknown_size"
    w, h = (1.0, 1.0) if stored_as_fraction else size
    canon = normalize_annotation_object(dict(obj), w, h)
    if canon is None:
        return None, "unreadable"
    if kind in POINT_TYPES:
        x, y = canon["points"][0]
        if not stored_as_fraction:
            x, y = x / size[0], y / size[1]
        return "point", (float(x), float(y))
    x, y, bw, bh = canon["bbox"]
    if not stored_as_fraction:
        x, y, bw, bh = x / size[0], y / size[1], bw / size[0], bh / size[1]
    if bw <= 0 or bh <= 0:
        return None, "unreadable"
    return "box", [float(x), float(y), float(bw), float(bh)]


def aggregate(config: Mapping[str, Any], annotations: Sequence[Mapping[str, Any]],
              items: Mapping[str, dict], schemas: Sequence[Mapping[str, Any]],
              settings: ConsensusSettings) -> Dict[str, Any]:
    """Everything the ``consensus`` export writes, as one dict.

    Returns ``{"settings", "questions", "numeric", "points", "boxes",
    "not_aggregated", "warnings"}``; the four result lists hold one row per
    item and scheme (questions, numeric) or per item, scheme and label
    (points, boxes).
    """
    from .boxes import box_consensus
    from .points import cluster_points

    warnings: List[str] = []
    questions: List[Dict[str, Any]] = []
    numeric: List[Dict[str, Any]] = []
    points_out: List[Dict[str, Any]] = []
    boxes_out: List[Dict[str, Any]] = []
    not_aggregated: Counter = Counter()
    sizes: Dict[str, Optional[Tuple[float, float]]] = {}
    no_size_items: set = set()
    unreadable = Counter()

    for scheme in aggregatable_schemes(schemas, settings):
        name, kind = scheme["name"], scheme.get("annotation_type")
        if kind in CATEGORICAL_TYPES or kind in NUMERIC_TYPES:
            by_item = gather_answers(scheme, annotations)
            for iid in sorted(by_item, key=_sort_key):
                if kind in NUMERIC_TYPES:
                    numeric.append({"instance_id": iid, "schema": name,
                                    **numeric_consensus(scheme, by_item[iid])})
                else:
                    questions.append({"instance_id": iid, "schema": name,
                                      **categorical_consensus(
                                          scheme, by_item[iid],
                                          settings.agreement_threshold,
                                          settings.min_classifiers)})
            continue

        # image_annotation: who drew on each item, and their marks by label.
        drawn: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        classifiers: Dict[str, set] = defaultdict(set)
        for record in annotations:
            objects = (record.get("image_annotations") or {}).get(name)
            if not isinstance(objects, list):
                continue
            iid, user = str(record.get("instance_id")), str(record.get("user_id"))
            classifiers[iid].add(user)
            for obj in objects:
                if not isinstance(obj, Mapping):
                    continue
                otype = obj.get("type")
                if otype not in POINT_TYPES and otype not in BOX_TYPES:
                    not_aggregated[str(otype or "unknown")] += 1
                    continue
                drawn[iid][str(obj.get("label") or "")].append((user, obj))

        for iid in sorted(classifiers, key=_sort_key):
            size = _image_size(items.get(iid), config, sizes, iid)
            n_classifiers = len(classifiers[iid])
            for label in sorted(drawn.get(iid, {})):
                pts, bxs = [], []
                for user, obj in drawn[iid][label]:
                    shape, value = _fractions(obj, size)
                    if shape == "point":
                        pts.append((user, value[0], value[1]))
                    elif shape == "box":
                        bxs.append((user, value))
                    else:
                        unreadable[value] += 1
                        if value == "unknown_size":
                            no_size_items.add(iid)
                base = {"instance_id": iid, "schema": name, "label": label}
                if pts:
                    if settings.eps_unit == "pixels" and not size:
                        no_size_items.add(iid)
                        points_out.append({**base, "n_classifiers": n_classifiers,
                                           "n_points": len(pts),
                                           "n_annotators": len({p[0] for p in pts}),
                                           "noise": None, "clusters": [],
                                           "skipped": "image size unknown; pixel eps "
                                                      "cannot be applied"})
                    else:
                        result = cluster_points(pts, eps=settings.eps,
                                                eps_unit=settings.eps_unit,
                                                min_samples=settings.min_samples,
                                                size=size)
                        result.pop("labels", None)
                        points_out.append({**base, "n_classifiers": n_classifiers,
                                           **result, "skipped": ""})
                if bxs:
                    boxes_out.append({**base, "n_classifiers": n_classifiers,
                                      "n_boxes": len(bxs),
                                      "groups": box_consensus(
                                          bxs, iou_threshold=settings.iou_threshold,
                                          n_classifiers=n_classifiers, size=size)})

    if no_size_items:
        listed = ", ".join(sorted(no_size_items, key=_sort_key)[:5])
        more = f" and {len(no_size_items) - 5} more" if len(no_size_items) > 5 else ""
        warnings.append(
            f"The image size of {len(no_size_items)} item(s) ({listed}{more}) is unknown, "
            "so points on them were not clustered with a pixel eps (or marks stored in "
            "pixels could not be read). Add image_width and image_height to the data, "
            "keep the images where the export can open them, or use eps_unit: fraction.")
    if unreadable.get("unreadable"):
        warnings.append(f"{unreadable['unreadable']} mark(s) had unusable geometry and "
                        "were left out.")
    if not_aggregated:
        kinds = ", ".join(f"{n} {k}" for k, n in sorted(not_aggregated.items()))
        warnings.append(f"Shapes other than points and boxes are not aggregated: {kinds}.")

    order = {s["name"]: i for i, s in enumerate(aggregatable_schemes(schemas, settings))}
    by_item = lambda row: (_sort_key(row["instance_id"]), order.get(row["schema"], 0))  # noqa: E731
    questions.sort(key=by_item)
    numeric.sort(key=by_item)
    return {"settings": settings.as_dict(), "questions": questions, "numeric": numeric,
            "points": points_out, "boxes": boxes_out,
            "not_aggregated": dict(not_aggregated), "warnings": warnings}


def _sort_key(instance_id: str):
    text = str(instance_id)
    return (0, int(text), text) if text.isdigit() else (1, 0, text)
