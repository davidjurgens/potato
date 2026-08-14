"""
One way to read a stored annotation value, whatever its schema.

Potato's subsystems each grew their own idea of what an annotation "is".
Categorical schemas store ``{label: value}``; spans store objects; image
annotation stores a single JSON string under one ``_data`` key. That last shape
is why vision is siloed: every subsystem that reasons about labels sees one key
whose name is identical for every annotator and every item, so comparing two
annotators' work looks like comparing ``{"_data"}`` with ``{"_data"}``.

Adjudication did exactly that and scored every image item 1.0 agreement — two
annotators who agreed on nothing were reported as agreeing perfectly, so no
image item could ever be routed for review.

Rather than teach six subsystems about geometry, they consume this:

    is_comparable(scheme)              -> can two annotators be compared at all?
    comparable_value(scheme, stored)   -> a value the caller can compare
    distance(scheme, a, b)             -> 0.0 identical .. 1.0 unrelated
    display_summary(scheme, stored)    -> "3 boxes, 1 mask (car, road)"
    geometry_objects(scheme, stored)   -> canonical objects, or []

Geometry goes through ``cv_utils.normalize_annotation_object`` and
``iaa.geometry``, so this module cannot drift from what the exporters read.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


#: Annotation types whose stored value is a geometry blob under a ``_data`` key.
GEOMETRY_TYPES = {"image_annotation"}

#: Annotation types whose ``_data`` blob is a timeline of labelled segments.
#: Audio and video serialize an identical ``{"segments": [{start_time, end_time,
#: label}]}`` payload through the same ``annotation-data-input`` convention as
#: image annotation, so they share this module's gathering and distance paths
#: and differ only in the similarity function.
TEMPORAL_TYPES = {"audio_annotation", "video_annotation"}

#: Types with no defined notion of agreement between two annotators. Free text
#: is excluded deliberately: two people never type the same sentence, and
#: pretending otherwise produces a confidently wrong number.
INCOMPARABLE_TYPES = {
    "pure_display", "video", "text", "textbox", "text_edit",
}


#: Values that mean "this option was not chosen" rather than being an answer.
FALSEY = (False, None, "", "false", "False", 0, "0")


def _annotation_type(scheme: Any) -> str:
    if isinstance(scheme, dict):
        return (scheme.get("annotation_type") or "").strip().lower()
    return (getattr(scheme, "annotation_type", "") or "").strip().lower()


def group_by_schema(label_data: Dict[Any, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Regroup a user state's flat label container into ``{schema: {name: value}}``.

    ``UserState.instance_id_to_label_to_value[iid]`` is **flat**, keyed by
    :class:`Label` objects — ``{Label(schema, name): value}`` — not nested by
    schema. Callers that assume nesting silently get nothing back, because a
    string key never hashes to a Label key and ``dict.get`` returns ``None``
    without ever invoking ``Label.__eq__``.

    That is not hypothetical: ``iaa.dispatcher._gather_labels`` did exactly this
    and so the overlap-IAA report returned NaN for every schema of every kind,
    for as long as the report has existed. Adjudication had grown its own
    correct copy of this loop; this is that copy, promoted so there is one.

    String keys are passed through unchanged so callers that already hold a
    grouped mapping (or a mysql-backed state) stay working.
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    for key, value in (label_data or {}).items():
        if hasattr(key, "get_schema"):
            grouped.setdefault(key.get_schema(), {})[key.get_name()] = value
        elif isinstance(key, str):
            # Already grouped, or a legacy flat mapping keyed by schema name.
            if isinstance(value, dict):
                grouped.setdefault(key, {}).update(value)
            else:
                grouped[key] = value
        else:
            grouped[str(key)] = value
    return grouped


def selected_labels(schema_values: Any) -> List[str]:
    """
    The label names a user actually chose for one schema.

    Potato stores one entry per rendered option, so "chosen" means the option's
    value is not one of :data:`FALSEY`. Radio stores ``{"positive": True}`` and
    likert stores ``{"2": "2"}`` — in both the *name* carries the answer, which
    is why this returns names rather than values.
    """
    if isinstance(schema_values, dict):
        return [str(name) for name, value in schema_values.items()
                if value not in FALSEY]
    if schema_values in FALSEY:
        return []
    return [str(schema_values)]


def is_comparable(scheme: Any) -> bool:
    """
    True when two annotators' values for this schema can be compared.

    A schema that is not comparable must be **omitted** from an agreement
    report, never scored. Absent is honest; 1.0 is not.
    """
    atype = _annotation_type(scheme)
    if not atype:
        return False
    if atype in INCOMPARABLE_TYPES:
        return False
    return True


def supports_geometry(scheme: Any) -> bool:
    """True when this schema's value is spatial geometry."""
    return _annotation_type(scheme) in GEOMETRY_TYPES


def supports_temporal(scheme: Any) -> bool:
    """True when this schema's value is a timeline of labelled segments."""
    return _annotation_type(scheme) in TEMPORAL_TYPES


def temporal_segments(scheme: Any, stored: Any) -> List[dict]:
    """
    Canonical ``{"start", "end", "label"}`` segments for an audio/video value.

    Both modalities serialize ``{"segments": [{start_time, end_time, label}]}``,
    so one reader covers them. Segments missing a usable time range are dropped
    rather than coerced to zero — a zero-length segment at the origin would
    silently agree with every other malformed segment.
    """
    if not supports_temporal(scheme):
        return []

    blobs = _parse_blob(stored)
    segments: List[dict] = []
    for blob in blobs:
        raw = blob.get("segments") if isinstance(blob, dict) else None
        for seg in raw or []:
            if not isinstance(seg, dict):
                continue
            try:
                start = float(seg.get("start_time"))
                end = float(seg.get("end_time"))
            except (TypeError, ValueError):
                continue
            if end < start:
                start, end = end, start
            segments.append({"start": start, "end": end,
                             "label": seg.get("label")})
    return segments


def _parse_blob(stored: Any) -> List[dict]:
    """
    Pull the annotation list out of a stored image-annotation value.

    Accepts the ``{"_data": "<json>"}`` mapping the label store holds, a raw
    JSON string, or an already-parsed list, because different call sites reach
    this with the value at different stages of unwrapping.
    """
    value = stored
    if isinstance(value, dict):
        # The label store keys by Label objects; by the time it reaches here it
        # is usually {"_data": "<json>"}.
        if "_data" in value:
            value = value["_data"]
        else:
            for key, item in value.items():
                if getattr(key, "name", None) == "_data" or key == "_data":
                    value = item
                    break

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []

    if isinstance(value, list):
        return [obj for obj in value if isinstance(obj, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def geometry_objects(scheme: Any, stored: Any,
                     img_w: float = 0, img_h: float = 0) -> List[dict]:
    """
    Canonical absolute-pixel objects for a stored geometry value.

    Falls back to the stored (normalized) objects when image dimensions are
    unknown; IoU between two annotators is scale-invariant, so comparisons stay
    valid as long as both sides are in the same space.
    """
    raw = _parse_blob(stored)
    if not raw:
        return []

    if img_w and img_h:
        try:
            from potato.export.cv_utils import normalize_annotation_object

            out = []
            for obj in raw:
                canonical = normalize_annotation_object(obj, img_w, img_h)
                if canonical:
                    out.append(canonical)
            return out
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not normalize geometry, using stored form: %s", exc)

    return [_as_canonical(obj) for obj in raw]


def _as_canonical(obj: dict) -> dict:
    """
    Shape a stored object like a canonical one, without rescaling.

    Only what the distance functions read: type, label, bbox, points, rle.
    """
    obj_type = obj.get("type")
    coords = obj.get("coordinates")
    canonical = {"type": obj_type, "label": obj.get("label")}

    if obj_type == "mask":
        canonical["rle"] = obj.get("rle") or {}
        return canonical

    if obj_type == "ellipse" and isinstance(coords, dict):
        # Give the distance functions the polygon they expect. Without image
        # dimensions the approximation stays in normalized space, which is fine:
        # IoU is scale-invariant as long as both sides use the same space.
        from potato.export.cv_utils import ellipse_to_polygon

        canonical["points"] = ellipse_to_polygon(
            float(coords.get("cx", 0) or 0), float(coords.get("cy", 0) or 0),
            float(coords.get("rx", 0) or 0), float(coords.get("ry", 0) or 0),
            float(coords.get("angle", 0) or 0),
        )
        return canonical

    if isinstance(coords, dict) and "width" in coords:
        canonical["bbox"] = [coords.get("x", 0), coords.get("y", 0),
                             coords.get("width", 0), coords.get("height", 0)]
    elif isinstance(coords, list):
        canonical["points"] = [[p.get("x", 0), p.get("y", 0)]
                               for p in coords if isinstance(p, dict)]
    elif isinstance(coords, dict) and "x" in coords:
        canonical["points"] = [[coords.get("x", 0), coords.get("y", 0)]]
        canonical["bbox"] = [coords.get("x", 0), coords.get("y", 0), 0, 0]

    return canonical


def comparable_value(scheme: Any, stored: Any) -> Any:
    """
    A value two annotators can be compared on.

    Categorical schemas collapse to the frozenset of selected labels, which is
    what adjudication already did. Geometry returns its object list, which is
    NOT hashable on purpose — callers must go through :func:`distance` rather
    than testing equality, because two annotators never draw identical pixels
    and exact comparison would report total disagreement.
    """
    if supports_geometry(scheme):
        return geometry_objects(scheme, stored)

    if supports_temporal(scheme):
        return temporal_segments(scheme, stored)

    if isinstance(stored, dict):
        return frozenset(selected_labels(stored))
    return stored


def distance(scheme: Any, value_a: Any, value_b: Any,
             match_threshold: float = 0.5) -> Optional[float]:
    """
    Distance in [0, 1] between two annotators' values. ``None`` if undefined.

    For geometry this is ``1 - mean IoU over matched instances``, with unmatched
    instances counted as full disagreement — so an annotator who misses half the
    objects is penalized even if the boxes they did draw are perfect.
    """
    if not is_comparable(scheme):
        return None

    if supports_geometry(scheme):
        return _matched_set_distance(value_a, value_b, match_threshold)

    if supports_temporal(scheme):
        from potato.server_utils.iaa import geometry

        return _matched_set_distance(value_a, value_b, match_threshold,
                                     sim_fn=geometry.temporal_similarity)

    if value_a is None or value_b is None:
        return None
    return 0.0 if value_a == value_b else 1.0


def _matched_set_distance(objects_a: Any, objects_b: Any, threshold: float,
                          sim_fn=None) -> float:
    """
    Distance between two annotators' *sets* of objects on one item.

    Shared by 2D geometry and temporal segments — only the similarity function
    differs. Unmatched objects on either side count as full disagreement, so an
    annotator who misses half the objects scores low even when the ones they did
    mark are perfect.
    """
    from potato.server_utils.iaa import geometry

    a = objects_a if isinstance(objects_a, list) else []
    b = objects_b if isinstance(objects_b, list) else []

    if not a and not b:
        return 0.0  # both annotators say "nothing here", which is agreement
    if not a or not b:
        return 1.0

    matches, unmatched_a, unmatched_b = geometry.match_instances(
        a, b, threshold, sim_fn=sim_fn)

    # Every object on either side contributes: matched ones their similarity,
    # unmatched ones zero.
    total = len(matches) + len(unmatched_a) + len(unmatched_b)
    if total == 0:
        return 0.0

    # A match between different labels agrees on location but not identity.
    score = 0.0
    for i, j, similarity in matches:
        same_label = a[i].get("label") == b[j].get("label")
        score += similarity if same_label else similarity * 0.5

    return max(0.0, min(1.0, 1.0 - score / total))


def display_summary(scheme: Any, stored: Any, max_labels: int = 4) -> str:
    """
    A short human-readable summary of a stored value.

    Adjudication used to render every image annotation as "N annotation(s)",
    so two annotators who drew completely different things looked identical in
    the review queue. Naming the shapes and labels is what makes the card
    scannable.
    """
    if supports_temporal(scheme):
        segments = temporal_segments(scheme, stored)
        if not segments:
            return "no segments"
        total = sum(s["end"] - s["start"] for s in segments)
        labels: List[str] = []
        for seg in segments:
            if seg.get("label") and seg["label"] not in labels:
                labels.append(seg["label"])
        summary = (f"{len(segments)} segment{'' if len(segments) == 1 else 's'}"
                   f", {total:.1f}s")
        if labels:
            shown = labels[:max_labels]
            suffix = (f" +{len(labels) - len(shown)} more"
                      if len(labels) > len(shown) else "")
            summary += f" ({', '.join(shown)}{suffix})"
        return summary

    if not supports_geometry(scheme):
        if isinstance(stored, dict):
            selected = selected_labels(stored)
            return ", ".join(selected) if selected else "no selection"
        return str(stored) if stored is not None else "no annotation"

    objects = _parse_blob(stored)
    if not objects:
        return "no annotations"

    plural = {"bbox": "boxes", "polygon": "polygons", "mask": "masks",
              "landmark": "points", "freeform": "freeform shapes",
              "polyline": "polylines", "ellipse": "ellipses"}
    singular = {"bbox": "box", "polygon": "polygon", "mask": "mask",
                "landmark": "point", "freeform": "freeform shape",
                "polyline": "polyline", "ellipse": "ellipse"}

    counts: Dict[str, int] = {}
    labels: List[str] = []
    for obj in objects:
        obj_type = obj.get("type") or "shape"
        counts[obj_type] = counts.get(obj_type, 0) + 1
        label = obj.get("label")
        if label and label not in labels:
            labels.append(label)

    parts = [
        f"{n} {(singular if n == 1 else plural).get(t, t)}"
        for t, n in sorted(counts.items())
    ]
    summary = ", ".join(parts)

    if labels:
        shown = labels[:max_labels]
        suffix = f" +{len(labels) - len(shown)} more" if len(labels) > len(shown) else ""
        summary += f" ({', '.join(shown)}{suffix})"
    return summary


def resolve_adopted(scheme: Any, adopted: Sequence[dict],
                    annotations_by_user: Dict[str, Any]) -> List[dict]:
    """
    Turn an adjudicator's picks into real annotation objects.

    The adjudication UI records a decision as ``[{annotator, idx}, ...]`` —
    references, not geometry. Stored that way, the adjudicated result is
    unusable: no CV exporter can read it, and the reference breaks if the
    annotator's own work later changes. This resolves the references into the
    client-contract objects the rest of the pipeline expects.
    """
    if not adopted:
        return []

    cache: Dict[str, List[dict]] = {}
    resolved: List[dict] = []

    for pick in adopted:
        if not isinstance(pick, dict):
            continue
        user = pick.get("annotator")
        if user is None:
            continue

        if user not in cache:
            cache[user] = _parse_blob(annotations_by_user.get(user))

        objects = cache[user]
        try:
            index = int(pick.get("idx"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(objects):
            obj = dict(objects[index])
            # Keep provenance: who drew it, so a published dataset can say.
            obj.setdefault("_adopted_from", user)
            resolved.append(obj)
        else:
            logger.warning(
                "Adjudication adopted annotation %s from %s, which no longer exists",
                index, user)

    return resolved
