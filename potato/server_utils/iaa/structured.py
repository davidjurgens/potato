"""
Agreement for three structured families the per-kind measures did not cover.

* **3D objects** (``spatial_annotation``): cuboids, points and polylines in
  sensor space, matched across annotators by 3D IoU (``geometry.similarity``
  dispatches on shape).
* **Time segments** (``temporal_grounding``, ``tiered_annotation``): segments
  matched by temporal IoU. These store ``{"segments": [...]}`` like
  audio/video, but under type names ``annotation_values`` does not treat as
  temporal, so the TEMPORAL path read nothing for them.
* **Agent-trace steps** (``process_reward``, ``trajectory_eval``,
  ``tool_call_review``, ``failure_attribution``, ``gui_trajectory``): one label
  per step; Krippendorff's alpha and Cohen's kappa with each (item, step) as a
  unit, through ``potato.step_agreement``.

The set measures use ``annotation_values._matched_set_distance``, the same
matching the 2D geometry report uses, so an unmatched object counts as full
disagreement and a matched pair with different labels counts half. The
labeling engine's families parse values with the functions here, so a machine
is scored against a person exactly as two people are scored against each
other.
"""

from __future__ import annotations

import itertools
import json
from typing import Any, Callable, Dict, List, Optional

SPATIAL_TYPES = ("spatial_annotation",)
SEGMENT_TYPES = ("temporal_grounding", "tiered_annotation")
TRACE_TYPES = ("process_reward", "trajectory_eval", "tool_call_review",
               "failure_attribution", "gui_trajectory")

#: Match thresholds: two 3D boxes must overlap by a quarter of their union to
#: be the same object (3D IoU is far stricter than 2D for the same miss);
#: segments by half, as for audio and video.
SPATIAL_MATCH = 0.25
SEGMENT_MATCH = 0.5


def spatial_objects(stored: Any) -> List[dict]:
    """Canonical 3D objects from a stored ``spatial_annotation`` value."""
    from potato.export.spatial_utils import normalize_spatial_object
    from potato.server_utils.annotation_values import _parse_blob
    out = []
    for obj in _parse_blob(stored):
        n = normalize_spatial_object(obj)
        if n:
            # Kept so a sequence's objects stay on their frames: see
            # spatial_distance.
            if isinstance(obj, dict) and isinstance(obj.get("frame"), int):
                n = dict(n, frame=obj["frame"])
            out.append(n)
    return out


def segment_list(stored: Any) -> List[dict]:
    """``{"start", "end", "label"}`` segments from a stored segment value.

    Reads every widget's timeline shape (``annotation_values.segment_records``),
    inside a ``_data`` JSON string or not, and accepts
    ``start_time``/``end_time`` or ``start``/``end``. Segments without a usable range are
    dropped rather than coerced to zero.
    """
    from potato.server_utils.annotation_values import _parse_blob, segment_records
    raw = stored.get("_data") if isinstance(stored, dict) and "_data" in stored else stored
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, dict) and not {"segments", "events", "annotations"} & set(raw):
        # A bare {label: value} container wrapping the JSON (the shape the
        # annotation store hands back for hidden-input schemes).
        inner = [v for v in raw.values() if isinstance(v, (str, dict))]
        for v in inner:
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    continue
            if isinstance(v, dict) and {"segments", "events", "annotations"} & set(v):
                raw = v
                break
    segs = segment_records(raw) if isinstance(raw, dict) else _parse_blob(stored)
    out = []
    for sgm in segs or []:
        if not isinstance(sgm, dict):
            continue
        start = sgm.get("start_time", sgm.get("start"))
        end = sgm.get("end_time", sgm.get("end"))
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if end < start:
            continue
        out.append({"start": start, "end": end,
                    "label": sgm.get("label") or sgm.get("tier")})
    return out


def _by_frame(objects: List[dict]) -> Dict[int, List[dict]]:
    """A sequence's canonical objects on every frame, interpolated per track."""
    from potato.export.spatial_sequences import object_at

    tracks: Dict[str, List[Any]] = {}
    for obj in objects:
        if obj.get("track_id") not in (None, "") and isinstance(obj.get("frame"), int):
            tracks.setdefault(str(obj["track_id"]), []).append((obj["frame"], obj))
    out: Dict[int, List[dict]] = {}
    for keyframes in tracks.values():
        keyframes.sort(key=lambda pair: pair[0])
        for frame in range(keyframes[0][0], keyframes[-1][0] + 1):
            here = object_at(keyframes, frame)
            if here is not None:
                out.setdefault(frame, []).append(here)
    return out


def spatial_distance(a: List[dict], b: List[dict]) -> float:
    """1 - matched 3D overlap between two annotators' objects.

    On a sequence (objects with `frame` and `track_id`) this is the mean of
    the per-frame distances, with boxes interpolated between keyframes, over
    the frames either annotator has an object on. Comparing all frames at
    once would match a box on frame 0 with one on frame 9.
    """
    from potato.server_utils.annotation_values import _matched_set_distance
    a, b = a or [], b or []
    if _is_sequence(a) or _is_sequence(b):
        frames_a, frames_b = _by_frame(a), _by_frame(b)
        frames = sorted(set(frames_a) | set(frames_b))
        if not frames:
            return 0.0
        return sum(float(_matched_set_distance(frames_a.get(f, []), frames_b.get(f, []),
                                               SPATIAL_MATCH)) for f in frames) / len(frames)
    return float(_matched_set_distance(a, b, SPATIAL_MATCH))


def segment_distance(a: List[dict], b: List[dict]) -> float:
    from potato.server_utils.annotation_values import _matched_set_distance
    from potato.server_utils.iaa import geometry
    return float(_matched_set_distance(a or [], b or [], SEGMENT_MATCH,
                                       sim_fn=geometry.temporal_similarity))


def _set_report(rows: Dict[str, Dict[str, Any]], parse: Callable[[Any], List[dict]],
                dist: Callable[[List[dict], List[dict]], float]) -> Dict[str, Any]:
    """Mean pairwise agreement (1 - distance) over items with 2+ annotators."""
    agreements: List[float] = []
    count_diffs: List[float] = []
    annotators = set()
    n_items = 0
    for per_user in rows.values():
        parsed = {uid: parse(v) for uid, v in per_user.items()}
        if len(parsed) < 2:
            continue
        n_items += 1
        annotators.update(parsed)
        for (_, a), (_, b) in itertools.combinations(sorted(parsed.items()), 2):
            agreements.append(1.0 - dist(a, b))
            count_diffs.append(abs(len(a) - len(b)))
    if not agreements:
        return {"n_items": 0, "n_annotators": len(annotators), "n_pairs": 0,
                "note": "No item has two or more annotators yet."}
    return {"mean_agreement": sum(agreements) / len(agreements),
            "mean_object_count_diff": sum(count_diffs) / len(count_diffs),
            "n_items": n_items, "n_annotators": len(annotators),
            "n_pairs": len(agreements)}


def _is_sequence(objects: List[Any]) -> bool:
    return any(isinstance(o, dict) and o.get("track_id") not in (None, "") and "frame" in o
               for o in objects)


def spatial_report(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Mean pairwise agreement over 3D objects.

    A sequence item (objects with `frame` and `track_id`) is scored frame by
    frame, with the boxes between keyframes interpolated, so a box on frame 0
    is never matched with one on frame 9. Each (item, frame) that anyone
    annotated is a unit; `n_frames` counts them.
    """
    from potato.export.spatial_sequences import dense_frames
    from potato.server_utils.annotation_values import _parse_blob

    expanded: Dict[str, Dict[str, Any]] = {}
    sequence_items = set()
    for iid, per_user in rows.items():
        raw = {uid: [o for o in _parse_blob(v) if isinstance(o, dict)]
               for uid, v in per_user.items()}
        if not any(_is_sequence(objs) for objs in raw.values()):
            expanded[iid] = {uid: spatial_objects(v) for uid, v in per_user.items()}
            continue
        sequence_items.add(iid)
        last = max((int(o["frame"]) for objs in raw.values() for o in objs
                    if isinstance(o.get("frame"), int)), default=-1)
        dense = {uid: dense_frames(objs, last + 1) for uid, objs in raw.items()}
        for frame in range(last + 1):
            per_frame = {uid: frames[frame] for uid, frames in dense.items()}
            if any(per_frame.values()):
                expanded[f"{iid}@{frame}"] = per_frame
    report = _set_report(expanded, lambda value: value if isinstance(value, list)
                         else spatial_objects(value), spatial_distance)
    if sequence_items:
        units = [key for key in expanded if key.split("@")[0] in sequence_items]
        report["n_frames"] = len(units)
        report["n_items"] = len({key.split("@")[0] for key in expanded
                                 if len(expanded[key]) >= 2})
    return report


def segment_report(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return _set_report(rows, segment_list, segment_distance)


def trace_report(rows: Dict[str, Dict[str, Any]], scheme_name: str) -> Dict[str, Any]:
    """Step-level alpha and kappa, each (item, step) a unit."""
    from potato.step_agreement import compute_step_agreement, steps_from_stored
    annotations: Dict[str, Dict[str, Any]] = {}
    for iid, per_user in rows.items():
        parsed = {uid: steps_from_stored(v) for uid, v in per_user.items()}
        parsed = {uid: {scheme_name: {str(k): str(v) for k, v in steps.items()}}
                  for uid, steps in parsed.items() if steps}
        if len(parsed) >= 2:
            annotations[iid] = parsed
    if not annotations:
        return {"n_items": 0, "n_annotators": 0,
                "note": "No item has step labels from two or more annotators yet."}
    alpha = compute_step_agreement(annotations, scheme_name, metric="krippendorff_alpha")
    kappa = compute_step_agreement(annotations, scheme_name, metric="cohens_kappa")
    agree = total = 0
    for per_user in annotations.values():
        steps = [s[scheme_name] for s in per_user.values()]
        for a, b in itertools.combinations(steps, 2):
            for k in set(a) & set(b):
                total += 1
                agree += a[k] == b[k]
    return {"alpha_nominal": alpha["overall"], "cohen_kappa": kappa["overall"],
            "percent_agreement": agree / total if total else None,
            "n_items": len(annotations), "n_annotators": alpha["n_annotators"],
            "n_steps": alpha["n_steps"]}


def kind_note(atype: str) -> Optional[str]:
    if atype in SPATIAL_TYPES:
        return "3D objects matched by 3D IoU"
    if atype in SEGMENT_TYPES:
        return "time segments matched by temporal IoU"
    if atype in TRACE_TYPES:
        return "one label per step; each (item, step) is a unit"
    return None
