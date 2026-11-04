"""Video object tracks as training targets, and tracking scores.

A ``video_annotation`` scheme in ``tracking`` or ``combined`` mode stores
tracks: a label and a box per keyframe, keyed by frame number at the
scheme's frame rate, the box both in the annotator's canvas pixels
(``bbox``) and as fractions of the picture (``bboxNorm``). Only the
normalized box means the same thing on every screen, so it is what is
trained on. Between keyframes a track is interpolated as the widget draws
it, by the track's own ``interpolation`` (linear, cubic or constant;
tracking-interpolation.js); before its first and after its last keyframe it
is absent.

The target is ``{fps, duration, width, height, tracks: [{id, label,
keyframes: [[frame, x, y, w, h], ...]}]}``.

Predictions go back as the widget's stored blob, ``tracks`` keyed
``track_<n>``, each keyframe with ``bboxNorm`` and no ``bbox``: the page
puts it in its own canvas pixels when it draws it (tracking-ui.js).

Held-out scores are CLEAR MOT and IDF1 against the annotated tracks, on the
frames both are sampled at, with ``iaa.identity`` (the measures agreement
uses between two annotators): MOTA, IDF1, ID switches, at IoU 0.5.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["track_target", "box_at", "associate", "track_payload", "score_tracks"]


def _blob(value_map: Any) -> Any:
    from potato.training.vision import blob
    return blob(value_map)


def track_target(value_map: Any, default_fps: float = 30.0) -> Optional[Dict[str, Any]]:
    """The annotated tracks with their normalized keyframe boxes; None when
    no track has a box keyframe."""
    answer = _blob(value_map)
    if not isinstance(answer, dict):
        return None
    tracks = answer.get("tracks")
    if isinstance(tracks, dict):
        tracks = list(tracks.values())
    meta = answer.get("video_metadata") if isinstance(answer.get("video_metadata"), dict) else {}
    out = []
    for track in tracks if isinstance(tracks, list) else []:
        if not isinstance(track, dict) or not track.get("label"):
            continue
        keyframes = []
        for key, kf in (track.get("keyframes") or {}).items():
            box = kf.get("bboxNorm") if isinstance(kf, dict) else None
            if not isinstance(box, dict):
                continue
            try:
                frame = int(kf.get("frame", key))
                x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
            except (TypeError, ValueError, KeyError):
                continue
            if w > 0 and h > 0 and all(math.isfinite(v) for v in (x, y, w, h)):
                keyframes.append([frame, x, y, w, h])
        if keyframes:
            entry = {"id": str(track.get("id") or len(out)), "label": str(track["label"]),
                     "keyframes": sorted(keyframes),
                     "interpolation": str(track.get("interpolation") or "linear")}
            # The widget's own bounds, when the track has them.
            for key, name in (("startFrame", "start"), ("endFrame", "end")):
                try:
                    if track.get(key) is not None:
                        entry[name] = int(track[key])
                except (TypeError, ValueError):
                    pass
            out.append(entry)
    if not out:
        return None
    try:
        fps = float(meta.get("fps") or default_fps)
    except (TypeError, ValueError):
        fps = default_fps
    return {"fps": fps, "duration": meta.get("duration"), "width": meta.get("width"),
            "height": meta.get("height"), "tracks": out}


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t)


def box_at(track: Dict[str, Any], frame: int) -> Optional[List[float]]:
    """``[x, y, w, h]`` normalized at *frame*, interpolated between keyframes
    the way the widget draws the track (tracking-interpolation.js); None
    outside the track. As there, a keyframe is drawn on its own frame even
    outside ``startFrame``/``endFrame``, a track with one keyframe holds it at
    every frame, and between a track's ``startFrame``/``endFrame`` and its
    first or last keyframe the nearest keyframe is held."""
    keyframes = track["keyframes"]
    for kf in keyframes:
        if kf[0] == frame:
            return list(kf[1:5])
    if len(keyframes) == 1:
        return list(keyframes[0][1:5])
    start = track.get("start", keyframes[0][0])
    end = track.get("end", keyframes[-1][0])
    if frame < start or frame > end:
        return None
    if frame < keyframes[0][0]:
        return list(keyframes[0][1:5])
    if frame > keyframes[-1][0]:
        return list(keyframes[-1][1:5])
    mode = track.get("interpolation") or "linear"
    for n, (before, after) in enumerate(zip(keyframes, keyframes[1:] + [keyframes[-1]])):
        if before[0] <= frame <= after[0]:
            if after[0] == before[0] or frame == before[0]:
                return list(before[1:5])
            if frame == after[0]:
                return list(after[1:5])
            if mode == "constant":
                return list(before[1:5])
            share = (frame - before[0]) / float(after[0] - before[0])
            if mode == "cubic":
                # The keyframes either side of the pair, or the pair's own ends.
                first = keyframes[n - 1] if n > 0 else before
                last = keyframes[n + 2] if n + 2 < len(keyframes) else after
                x, y, w, h = (_catmull_rom(first[i], before[i], after[i], last[i], share)
                              for i in range(1, 5))
                # The widget floors a size at 1 canvas pixel; normalized,
                # the screen is unknown, so only a positive size is kept.
                return [x, y, max(w, 1e-6), max(h, 1e-6)]
            return [b + (a - b) * share for b, a in zip(before[1:5], after[1:5])]
    return None


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    h = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = w * h
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def associate(detections: Sequence[Tuple[int, List[Dict[str, Any]]]], match_iou: float = 0.3,
              max_age: int = 2, new_track_score: float = 0.5,
              min_keyframes: int = 1) -> List[Dict[str, Any]]:
    """Tracks from per-frame detections, in frame order.

    *detections* is ``[(frame, [{label, box: [x, y, w, h], score}])]``. Each
    frame's detections are matched to the live tracks of the same label by
    IoU with the track's last box (best one-to-one assignment, at least
    *match_iou*); an unmatched detection of at least *new_track_score*
    starts a track; a track unmatched for more than *max_age* sampled frames
    ends; a track of fewer than *min_keyframes* detections is dropped (the
    widget holds a one-keyframe track at every frame, so one stray detection
    would cover the whole video). Returns
    ``[{label, keyframes: [[frame, x, y, w, h, score]]}]``.
    """
    from potato.training.structured_metrics import hungarian
    live: List[Dict[str, Any]] = []
    done: List[Dict[str, Any]] = []
    for frame, found in sorted(detections, key=lambda d: d[0]):
        found = [d for d in found if d.get("box")]
        taken_tracks, taken_dets = set(), set()
        if live and found:
            size = max(len(live), len(found))
            cost = [[0.0] * size for _ in range(size)]
            for t, track in enumerate(live):
                last = track["keyframes"][-1][1:5]
                for d, det in enumerate(found):
                    if det["label"] == track["label"]:
                        cost[t][d] = -_iou(last, det["box"])
            for t, d in hungarian(cost):
                if t < len(live) and d < len(found) and -cost[t][d] >= match_iou:
                    det = found[d]
                    live[t]["keyframes"].append([frame] + list(det["box"]) + [det.get("score")])
                    live[t]["age"] = 0
                    taken_tracks.add(t)
                    taken_dets.add(d)
        for t, track in enumerate(live):
            if t not in taken_tracks:
                track["age"] += 1
        done.extend(t for t in live if t["age"] > max_age)
        live = [t for t in live if t["age"] <= max_age]
        for d, det in enumerate(found):
            if d not in taken_dets and (det.get("score") or 0.0) >= new_track_score:
                live.append({"label": det["label"], "age": 0,
                             "keyframes": [[frame] + list(det["box"]) + [det.get("score")]]})
    return [{"label": t["label"], "keyframes": t["keyframes"]} for t in done + live
            if len(t["keyframes"]) >= min_keyframes]


def track_payload(tracks: List[Dict[str, Any]], fps: float, duration: float,
                  width: Optional[int], height: Optional[int],
                  model_version: str = "") -> Dict[str, Any]:
    """Tracks in the video widget's stored shape."""
    stored = {}
    for n, track in enumerate(tracks, start=1):
        keyframes = {}
        for frame, x, y, w, h, score in track["keyframes"]:
            kf = {"frame": int(frame), "time": round(frame / fps, 4), "type": "bbox",
                  "bboxNorm": {"x": round(x, 5), "y": round(y, 5),
                               "width": round(w, 5), "height": round(h, 5)},
                  "source": "ai"}
            if model_version:
                kf["ai_model"] = model_version
            if score is not None:
                kf["confidence"] = round(float(score), 4)
            keyframes[str(int(frame))] = kf
        frames = [int(k[0]) for k in track["keyframes"]]
        stored["track_%d" % n] = {
            "id": "track_%d" % n, "label": track["label"], "color": "",
            "interpolation": "linear", "startFrame": min(frames), "endFrame": max(frames),
            "attributes": {}, "keyframes": keyframes}
    meta = {"duration": round(float(duration), 3), "fps": fps}
    if width and height:
        meta.update(width=int(width), height=int(height))
    return {"video_metadata": meta, "segments": [], "frame_annotations": {}, "keyframes": [],
            "tracking": {}, "tracks": stored}


def _frames(target: Dict[str, Any], frames: Sequence[int]) -> Dict[int, List[Tuple[str, Any]]]:
    out: Dict[int, List[Tuple[str, Any]]] = {}
    for track in target.get("tracks") or []:
        for frame in frames:
            box = box_at(track, frame)
            if box is not None:
                out.setdefault(frame, []).append((track["id"], (track["label"], box)))
    return out


def score_tracks(gold: List[Any], predicted: List[Any], threshold: float = 0.5,
                 eval_fps: float = 2.0) -> Dict[str, float]:
    """MOTA, IDF1 and ID switches pooled over the videos, on frames sampled
    at *eval_fps* across each annotated video's tracks."""
    from potato.server_utils.iaa.identity import clear_mot, id_true_positives

    def similarity(a, b):
        return _iou(a[1], b[1]) if a[0] == b[0] else 0.0

    totals = {"reference": 0, "misses": 0, "extra": 0, "id_switches": 0,
              "idtp": 0, "n_gold": 0, "n_pred": 0}
    for target, payload in zip(gold, predicted):
        fps = float(target.get("fps") or 30.0)
        last = max(k[0] for t in target["tracks"] for k in t["keyframes"])
        step = max(1, int(round(fps / eval_fps)))
        # The annotated keyframes too: a track shorter than one step fell
        # between the sampled frames and was never scored.
        frames = sorted(set(range(0, last + 1, step))
                        | {k[0] for t in target["tracks"] for k in t["keyframes"]})
        predicted_target = track_target(payload if isinstance(payload, dict) else {},
                                        default_fps=fps) or {"tracks": []}
        reference, other = _frames(target, frames), _frames(predicted_target, frames)
        counts = clear_mot(reference, other, similarity, threshold)
        for key in ("reference", "misses", "extra", "id_switches"):
            totals[key] += counts[key]
        totals["idtp"] += id_true_positives(reference, other, similarity, threshold)
        totals["n_gold"] += sum(len(v) for v in reference.values())
        totals["n_pred"] += sum(len(v) for v in other.values())
    if not totals["reference"]:
        return {}
    mota = 1.0 - (totals["misses"] + totals["extra"] + totals["id_switches"]) \
        / float(totals["reference"])
    denominator = totals["n_gold"] + totals["n_pred"]
    return {"mota": mota, "idf1": 2.0 * totals["idtp"] / denominator if denominator else 0.0,
            "id_switches": float(totals["id_switches"]), "misses": float(totals["misses"]),
            "false_positives": float(totals["extra"])}
