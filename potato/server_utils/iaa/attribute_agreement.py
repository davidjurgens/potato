"""
Agreement over per-object attributes.

Two annotators who both drew the same car can still disagree about whether it
is partly occluded, and that disagreement is often where a driving or
detection dataset is least reliable. Every CV tool stores such attributes;
none reports whether the people filling them in agree.

For each attribute, the units are the objects two or more annotators drew in
the same place (matched by `geometry_agreement._matched_clusters`, the same
matching the classification alpha uses), and the values are what each of them
set. Krippendorff's alpha is computed at the level the attribute's type
implies, with raw percent agreement beside it, because a reader who has never
met chance correction needs to see what it corrected.

    select, bool   nominal
    number         interval
    multi          MASI distance over the chosen sets
    text           not scored (free text has no shared value space)

An object whose label the attribute does not apply to, or whose annotator left
the attribute blank, contributes no value for it.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, List

from potato.server_utils.iaa.alpha import krippendorff_alpha

LEVELS = {"select": "nominal", "bool": "nominal", "number": "interval", "multi": "masi"}


def _value(definition: Dict[str, Any], raw: Any):
    """A hashable value at the right level, or None when there is none."""
    if raw is None or raw == "" or raw == []:
        return None
    kind = definition["type"]
    if kind == "multi":
        values = raw if isinstance(raw, list) else [raw]
        return frozenset(str(v) for v in values) or None
    if kind == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes")
        return bool(raw)
    return str(raw)


def _applies(definition: Dict[str, Any], label: Any) -> bool:
    labels = definition.get("labels")
    return labels is None or label in labels


def attribute_agreement(rows: Dict[str, Dict[str, List[dict]]],
                        definitions: List[Dict[str, Any]],
                        threshold: float = 0.5,
                        to_canonical=None, similarity=None) -> Dict[str, Dict[str, Any]]:
    """Per-attribute agreement over the objects annotators matched.

    Args:
        rows: ``{instance_id: {annotator: [client-shaped objects]}}``, the
            shape `_gather_blobs` produces for an image scheme.
        definitions: normalized attribute definitions
            (`schemas.object_attributes.normalize_attributes`).
        threshold: geometric similarity two shapes need to count as the same
            object.
        to_canonical: client object -> canonical object, or None to skip it.
            Image shapes by default; `spatial_canonical` for point clouds,
            `track_canonical` for video tracks.
        similarity: canonical a, b -> [0, 1]. `geometry.similarity` by
            default, which covers image shapes and 3D objects.

    Returns:
        ``{attribute name: {"level", "alpha", "percent_agreement",
        "n_objects", "n_annotators", ["note"]}}``. ``note`` says why alpha is
        undefined when it is, which the /admin/iaa table prints in its place.
    """
    from potato.server_utils.iaa import geometry_agreement as ga

    to_canonical = to_canonical or ga.canonical_object
    scored = [d for d in definitions if d.get("type") in LEVELS]
    long_format: Dict[str, List[tuple]] = {d["name"]: [] for d in scored}

    for instance_id, per_user in rows.items():
        canonical: Dict[str, List[dict]] = {}
        for annotator, objects in (per_user or {}).items():
            converted = []
            for obj in objects or []:
                shape = to_canonical(obj) if isinstance(obj, dict) else None
                if shape is None:
                    continue
                shape = dict(shape)
                # Carried on the canonical copy so a matched cluster still
                # knows what each annotator set; geometry ignores both keys.
                shape["_attributes"] = obj.get("attributes") or {}
                shape["_label"] = obj.get("label")
                converted.append(shape)
            canonical[annotator] = converted

        for index, cluster in enumerate(ga._matched_clusters(canonical, threshold, similarity)):
            if len(cluster) < 2:
                continue
            unit = f"{instance_id}#{index}"
            for definition in scored:
                values = []
                for annotator, shape in cluster.items():
                    if not _applies(definition, shape["_label"]):
                        continue
                    value = _value(definition, shape["_attributes"].get(definition["name"]))
                    if value is not None:
                        values.append((annotator, unit, value))
                if len(values) >= 2:
                    long_format[definition["name"]].extend(values)

    report: Dict[str, Dict[str, Any]] = {}
    for definition in definitions:
        name = definition["name"]
        if definition.get("type") not in LEVELS:
            report[name] = {"level": "not scored",
                            "note": "free-text attributes are not scored"}
            continue
        rows_for = long_format[name]
        level = LEVELS[definition["type"]]
        units: Dict[str, List[Any]] = {}
        for _annotator, unit, value in rows_for:
            units.setdefault(unit, []).append(value)
        pairs = [(a, b) for values in units.values() for a, b in combinations(values, 2)]
        # alpha first: the /admin/iaa table captions the first measure with the
        # group's counts, and alpha is the number the row is for.
        entry: Dict[str, Any] = {
            "alpha": krippendorff_alpha(rows_for, level) if rows_for else float("nan"),
            "percent_agreement": (sum(1 for a, b in pairs if a == b) / len(pairs)
                                  if pairs else float("nan")),
            "n_objects": len(units),
            "n_annotators": len({a for a, _u, _v in rows_for}),
            "level": level,
        }
        if math.isnan(entry["alpha"]):
            if not rows_for:
                entry["note"] = (
                    "no object was matched across annotators with this attribute set "
                    "by two or more of them")
            elif len({v for _a, _u, v in rows_for}) < 2:
                entry["note"] = (
                    "every annotator gave the same value on every matched object, so "
                    "there is no variation for alpha to correct against. Perfect "
                    "agreement, not a failed computation.")
            else:
                entry["note"] = "too few matched objects for alpha to be defined"
        report[name] = entry
    return report


# ---------------------------------------------------------------------------
# Point clouds and video tracks
# ---------------------------------------------------------------------------

def spatial_objects_with_attributes(stored: Any) -> List[dict]:
    """The client objects in a stored ``spatial_annotation`` value."""
    from potato.server_utils.annotation_values import _parse_blob
    return [o for o in _parse_blob(stored) if isinstance(o, dict)]


def spatial_canonical(obj: dict):
    from potato.export.spatial_utils import normalize_spatial_object
    return normalize_spatial_object(obj)


def spatial_tracks_with_attributes(stored: Any) -> List[dict]:
    """The objects of a stored point-cloud value, one per track on a sequence.

    A single cloud's objects come back as they are. On a sequence (objects
    with `frame` and `track_id`) each track is one object, since a track's
    attributes are one value across its keyframes.
    """
    from potato.export import spatial_sequences as ss
    from potato.server_utils.iaa.structured import _is_sequence

    objects = spatial_objects_with_attributes(stored)
    if not _is_sequence(objects):
        return objects
    first: Dict[str, dict] = {}
    for obj in objects:
        if obj.get("track_id") not in (None, ""):
            first.setdefault(str(obj["track_id"]), obj)
    return [{"type": "track3d", "track_id": tid, "label": first[tid].get("label"),
             "attributes": first[tid].get("attributes") or {}, "keyframes": keyframes}
            for tid, keyframes in ss.tracks(objects).items()]


def spatial_track_canonical(obj: dict):
    if obj.get("type") == "track3d":
        frames = [f for f, _ in obj["keyframes"]]
        return {"type": "track3d", "keyframes": obj["keyframes"],
                "start": min(frames), "end": max(frames)}
    return spatial_canonical(obj)


def spatial_track_similarity(a: dict, b: dict) -> float:
    """Temporal IoU of two 3D tracks times their mean 3D similarity.

    The 3D counterpart of `track_similarity`: compared at every keyframe
    either track has, interpolating the other, over the frames both span.
    """
    from potato.export.spatial_sequences import object_at
    from potato.server_utils.iaa import geometry

    if a.get("type") != "track3d" or b.get("type") != "track3d":
        if a.get("type") == "track3d" or b.get("type") == "track3d":
            return 0.0
        return geometry.similarity(a, b)
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"]) + 1
    if overlap <= 0:
        return 0.0
    temporal = overlap / (max(a["end"], b["end"]) - min(a["start"], b["start"]) + 1)
    sims = []
    for frame in sorted({f for f, _ in a["keyframes"]} | {f for f, _ in b["keyframes"]}):
        oa, ob = object_at(a["keyframes"], frame), object_at(b["keyframes"], frame)
        if oa and ob:
            sims.append(geometry.similarity(oa, ob))
    return temporal * sum(sims) / len(sims) if sims else 0.0


def track_objects(stored: Any) -> List[dict]:
    """The tracks in a stored ``video_annotation`` value, one dict each."""
    import json
    raw = stored.get("_data") if isinstance(stored, dict) and "_data" in stored else stored
    if isinstance(raw, dict) and "tracks" not in raw:
        raw = next((v for v in raw.values() if isinstance(v, str) and "tracks" in v), raw)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    tracks = raw.get("tracks") if isinstance(raw, dict) else None
    if isinstance(tracks, dict):
        tracks = list(tracks.values())
    return [t for t in tracks or [] if isinstance(t, dict)]


def track_canonical(track: dict):
    """A track as {type, frames: {frame: normalized box or None}, start, end}."""
    keyframes = track.get("keyframes") or {}
    frames = {}
    for key, kf in keyframes.items():
        try:
            frame = int(kf.get("frame", key)) if isinstance(kf, dict) else int(key)
        except (TypeError, ValueError):
            continue
        frames[frame] = (kf.get("bboxNorm") if isinstance(kf, dict) else None)
    if not frames:
        return None
    return {"type": "track", "frames": frames, "start": min(frames), "end": max(frames)}


def _box_at(frames: Dict[int, Any], frame: int):
    """Linearly interpolated normalized box at ``frame``, or None."""
    known = sorted(f for f, b in frames.items() if isinstance(b, dict))
    if not known or frame < known[0] or frame > known[-1]:
        return None
    if frame in frames and isinstance(frames[frame], dict):
        return frames[frame]
    before = max(f for f in known if f <= frame)
    after = min(f for f in known if f >= frame)
    a, b = frames[before], frames[after]
    t = (frame - before) / (after - before) if after != before else 0.0
    return {k: a[k] + (b[k] - a[k]) * t for k in ("x", "y", "width", "height")}


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["width"], a["y"] + a["height"]
    bx2, by2 = b["x"] + b["width"], b["y"] + b["height"]
    w = max(0.0, min(ax2, bx2) - max(a["x"], b["x"]))
    h = max(0.0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = w * h
    union = a["width"] * a["height"] + b["width"] * b["height"] - inter
    return inter / union if union > 0 else 0.0


def track_similarity(a: dict, b: dict) -> float:
    """How much two tracks are the same object, in [0, 1].

    The overlap of their frame ranges (temporal IoU) times the mean IoU of
    their normalized boxes at the keyframes either has. A pair with no frame
    where both have a normalized box scores 0: on time alone a car and a
    pedestrian tracked over the same frames would look identical, and their
    attributes would be compared as if they were one object. The report
    counts such tracks instead (`n_tracks_without_normalized_boxes`).
    """
    if not a or not b or a.get("type") != "track" or b.get("type") != "track":
        return 0.0
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"]) + 1
    if overlap <= 0:
        return 0.0
    span = max(a["end"], b["end"]) - min(a["start"], b["start"]) + 1
    temporal = overlap / span
    ious = []
    for frame in sorted(set(a["frames"]) | set(b["frames"])):
        box_a, box_b = _box_at(a["frames"], frame), _box_at(b["frames"], frame)
        if box_a and box_b:
            ious.append(_iou(box_a, box_b))
    if not ious:
        return 0.0
    return temporal * sum(ious) / len(ious)


def has_normalized_box(track: dict) -> bool:
    """Whether a stored track has a keyframe with a normalized box."""
    canonical = track_canonical(track) if isinstance(track, dict) else None
    return bool(canonical) and any(isinstance(b, dict) for b in canonical["frames"].values())
