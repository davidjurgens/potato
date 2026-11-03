"""Model predictions for hidden-input and slider schemes, as input values.

The annotation page restores a returning annotator's answer by walking the
DOM and filling inputs named ``<scheme>:::<label>``. A prelabel takes the
same path: ``render_page_with_annotations`` puts ``{label: value}`` under the
scheme and the walk fills the input and marks it server-set, which is what
each widget's restore code reads.

This module turns a trained model's payload into those values for the types
whose answer is one or a few hidden inputs: a ranking's order, a BWS best
and worst, a soft label's sliders, an interlinear gloss and a conversation
tree. Pairwise scale needs the annotator's presentation order, so the page
handles it itself.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["PRELABEL_TYPES", "prelabel_values", "valid_shape", "client_shapes",
           "client_spatial"]

PRELABEL_TYPES = ("ranking", "bws", "soft_label", "interlinear_gloss",
                  "tree_annotation", "microscopy", "gui_trajectory",
                  "grounding_eval", "region_caption", "speech_transcript",
                  "volume_annotation", "video_annotation")


def _label_names(scheme: Dict[str, Any]) -> List[str]:
    return [str(l.get("name") if isinstance(l, dict) else l)
            for l in scheme.get("labels") or []]


def _order(payload: Any) -> List[str]:
    if isinstance(payload, dict):
        payload = payload.get("order", payload.get("rank_order"))
    if isinstance(payload, str):
        payload = payload.split(",")
    return [str(p) for p in payload] if isinstance(payload, list) else []


def _integer_masses(shares: Dict[str, float], labels: List[str],
                    total: int) -> Dict[str, int]:
    """Shares as whole slider values summing to *total*, by largest
    remainder, so the sliders read as the model's distribution and the
    widget's sum check passes."""
    weights = {label: max(0.0, float(shares.get(label, 0.0) or 0.0))
               for label in labels}
    whole = sum(weights.values())
    if whole <= 0:
        return {}
    exact = {label: total * w / whole for label, w in weights.items()}
    masses = {label: int(v) for label, v in exact.items()}
    short = total - sum(masses.values())
    for label in sorted(labels, key=lambda l: exact[l] - masses[l],
                        reverse=True)[:short]:
        masses[label] += 1
    return masses


#: Shapes the vision widgets take, and a little slack past the image edge
#: for a shape drawn up to it.
_SHAPE_TYPES = ("bbox", "polygon", "landmark", "ellipse", "freeform", "mask", "polyline",
                "keypoint_set", "cuboid_2d")
_EDGE = 0.01


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _inside(*values: Optional[float]) -> bool:
    return all(v is not None and -_EDGE <= v <= 1 + _EDGE for v in values)


def valid_shape(obj: Any, labels: Optional[List[str]] = None) -> bool:
    """Whether a predicted image shape can be shown as it is: a known type,
    finite normalized coordinates on the image, a box with a positive size,
    and one of the scheme's labels when it lists them.

    A widget handed anything else repairs it as it draws (clamps a box,
    drops a point), the repair changes its input, and the page saved the
    repaired prediction as the annotator's answer on arrival."""
    if not isinstance(obj, dict) or obj.get("type") not in _SHAPE_TYPES:
        return False
    if labels and str(obj.get("label")) not in labels:
        return False
    coords = obj.get("coordinates")
    kind = obj["type"]
    if kind == "mask":
        return isinstance(obj.get("rle"), dict)
    if kind == "bbox":
        if not isinstance(coords, dict):
            return False
        x, y = _number(coords.get("x")), _number(coords.get("y"))
        w, h = _number(coords.get("width")), _number(coords.get("height"))
        return (w is not None and h is not None and w > 0 and h > 0
                and _inside(x, y) and _inside(x + w, y + h))
    if kind == "landmark":
        return isinstance(coords, dict) and _inside(_number(coords.get("x")),
                                                    _number(coords.get("y")))
    if kind in ("polygon", "polyline"):
        points = coords if isinstance(coords, list) else []
        return len(points) >= (3 if kind == "polygon" else 2) and all(
            isinstance(p, dict) and _inside(_number(p.get("x")), _number(p.get("y")))
            for p in points)
    return isinstance(coords, (dict, list))


def client_shapes(objects: Any, labels: Optional[List[str]] = None) -> tuple:
    """``(shapes, dropped)``: an image prediction's shapes in the image
    widget's form, and how many were left out.

    A normalized ``points: [[x, y], ...]`` outline or ``bbox: [x, y, w, h]``
    is converted to ``coordinates``. The canvas reads only ``coordinates``,
    so such a polygon vanished at load, and the next edit saved the item
    without it. Anything else :func:`valid_shape` refuses is left out."""
    out, dropped = [], 0
    for obj in objects if isinstance(objects, list) else []:
        if isinstance(obj, dict) and "coordinates" not in obj:
            obj = dict(obj)
            points, box = obj.pop("points", None), obj.pop("bbox", None)
            try:
                if isinstance(points, list) and all(len(p) >= 2 for p in points):
                    obj["coordinates"] = ([{"x": float(points[0][0]), "y": float(points[0][1])}]
                                          if obj.get("type") == "landmark" and len(points) == 1
                                          else [{"x": float(p[0]), "y": float(p[1])}
                                                for p in points])
                    if obj.get("type") == "landmark":
                        obj["coordinates"] = obj["coordinates"][0]
                elif isinstance(box, list) and len(box) == 4:
                    obj.setdefault("type", "bbox")
                    obj["coordinates"] = dict(zip(("x", "y", "width", "height"),
                                                  (float(v) for v in box)))
            except (TypeError, ValueError, IndexError):
                pass
        if valid_shape(obj, labels):
            out.append(obj)
        else:
            dropped += 1
    return out, dropped


def _planes(scheme: Dict[str, Any], item: Optional[Dict[str, Any]],
            config: Optional[Dict[str, Any]]) -> Optional[tuple]:
    """``(size_z, size_t)`` of the item's microscopy image, or None."""
    if not item or not config:
        return None
    try:
        from potato.science.converters.ome import open_ome
        from potato.science.microscopy_routes import resolve_item_path
        path = resolve_item_path(config, item.get(scheme.get("image_key", "image")))
        if not path:
            return None
        image = open_ome(path, max_pixels=int(scheme.get("max_pixels") or 64_000_000))
        return image.size_z, image.size_t
    except Exception:  # noqa: BLE001 - the widget reports an unreadable image itself
        return None


def client_spatial(objects: List[Any], labels: Optional[List[str]] = None
                   ) -> Tuple[List[Dict[str, Any]], int]:
    """``(objects the point-cloud viewer can show, number left out)``. An
    object whose geometry does not parse, or whose label the scheme does not
    have, was dropped by the viewer at load and the next save stored the
    scan without it."""
    from potato.export.spatial_utils import normalize_spatial_object
    kept, dropped = [], 0
    for obj in objects:
        canonical = normalize_spatial_object(obj) if isinstance(obj, dict) else None
        if not canonical or (labels and str(canonical.get("label")) not in labels):
            dropped += 1
            continue
        raw_size = ((obj.get("coordinates") or {}).get("size")
                    if isinstance(obj.get("coordinates"), dict) else None)
        sizes = list(canonical.get("size") or []) + list(raw_size or [])
        if canonical["type"] == "cuboid_3d" and not (
                canonical.get("size") and all(math.isfinite(float(v)) and float(v) > 0
                                              for v in sizes)):
            dropped += 1
            continue
        kept.append(obj)
    return kept, dropped


def prelabel_values(scheme: Dict[str, Any], payload: Any,
                    item: Optional[Dict[str, Any]] = None,
                    config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
    """``{label_name: input value}`` for one scheme's prediction, or None
    when the payload does not fit the scheme (logged). *item* and *config*
    let a microscopy prediction be checked against the image's planes."""
    atype = scheme.get("annotation_type")
    name = str(scheme.get("name") or "")
    if atype == "ranking":
        known = _label_names(scheme)
        order = [o for o in _order(payload) if o in known]
        # The widget shows every option; a partial order would drop some.
        if sorted(order) != sorted(known):
            logger.warning("Ranking prediction for %r does not order every "
                           "option; not shown", name)
            return None
        return {"rank_order": ",".join(order)}
    if atype == "bws":
        if not isinstance(payload, dict):
            return None
        best, worst = str(payload.get("best") or ""), str(payload.get("worst") or "")
        if not best or not worst or best == worst:
            return None
        return {"best": best, "worst": worst}
    if atype == "soft_label":
        shares = payload.get("distribution", payload) if isinstance(payload, dict) else None
        if not isinstance(shares, dict):
            return None
        try:
            total = int(scheme.get("total", 100) or 100)
        except (TypeError, ValueError):
            total = 100
        masses = _integer_masses(shares, _label_names(scheme), total)
        return {label: str(v) for label, v in masses.items()} or None
    if atype == "interlinear_gloss":
        if not isinstance(payload, dict) or not isinstance(payload.get("words"), list):
            return None
        return {name: json.dumps({"words": payload["words"],
                                  "translation": str(payload.get("translation") or "")},
                                 ensure_ascii=False)}
    if atype == "tree_annotation":
        if not isinstance(payload, dict):
            return None
        values = {}
        if isinstance(payload.get("path"), list) and payload["path"]:
            values["selected_path"] = json.dumps([str(p) for p in payload["path"]])
        if isinstance(payload.get("nodes"), dict) and payload["nodes"]:
            values["node_annotations"] = json.dumps(payload["nodes"])
        return values or None
    if atype == "microscopy":
        # ROIs on their planes; the widget redraws them on its canvas.
        if not isinstance(payload, dict) or not isinstance(payload.get("rois"), list):
            return None
        labels = _label_names(scheme)
        planes = _planes(scheme, item, config)

        def on_a_plane(roi):
            try:
                z, t = int(roi.get("z") or 0), int(roi.get("t") or 0)
            except (TypeError, ValueError):
                return False
            if z < 0 or t < 0:
                return False
            return planes is None or (z < planes[0] and t < planes[1])

        rois = [r for r in payload["rois"] if valid_shape(r, labels) and on_a_plane(r)]
        if len(rois) < len(payload["rois"]):
            logger.warning("Microscopy prediction for %r: %d ROI(s) left out that are not "
                           "shapes on this image's planes", name,
                           len(payload["rois"]) - len(rois))
        answer = {"rois": rois}
        if isinstance(payload.get("image"), dict):
            answer["image"] = payload["image"]
        return {name: json.dumps(answer, ensure_ascii=False)} if answer["rois"] else None
    if atype == "gui_trajectory":
        # A suggested verdict per step, keyed by index like the stored list.
        options = [str(o) for o in scheme.get("verdict_options") or
                   ("correct", "wrong_element", "wrong_action", "hallucinated")]
        steps_in_item = (item or {}).get(scheme.get("steps_key", "steps"))
        n_steps = len(steps_in_item) if isinstance(steps_in_item, list) else None
        steps = []
        for entry in payload if isinstance(payload, list) else []:
            if not isinstance(entry, dict) or str(entry.get("verdict")) not in options:
                continue
            try:
                index = int(entry.get("index"))
            except (TypeError, ValueError):
                continue
            if index < 0 or (n_steps is not None and index >= n_steps):
                continue
            steps.append({"index": index, "step": index,
                          "verdict": str(entry["verdict"]), "notes": ""})
        return {name: json.dumps(steps)} if steps else None
    if atype == "grounding_eval":
        if not isinstance(payload, dict) or not isinstance(payload.get("regions"), dict):
            return None
        regions = {str(k): [r for r in v if valid_shape(r)]
                   for k, v in payload["regions"].items() if isinstance(v, list)}
        regions = {k: v for k, v in regions.items() if v}
        if not regions and not payload.get("absent"):
            return None
        return {"_data": json.dumps({
            "regions": regions,
            "absent": [str(a) for a in payload.get("absent") or []
                       if isinstance(a, (str, int)) and not isinstance(a, bool)],
            "verdicts": {},
            "region_type": str(scheme.get("region_type") or "box")}, ensure_ascii=False)}
    if atype == "speech_transcript":
        # A suggested correction per turn, keyed by index like the stored
        # list, on turns the item has; the times are the item's. The error
        # types are the ones the widget offers: a pill it does not show, or
        # one listed twice, could not be cleared.
        error_types = [str(e) for e in (scheme["error_types"] if "error_types" in scheme else
                       ("asr_error", "tts_artifact", "mispronunciation", "disfluency"))]
        turns = None
        if item:
            from potato.training.audio import transcript_turns
            turns = {t["index"]: t for t in transcript_turns(
                scheme, item, (config or {}).get("task_dir"))["turns"]}
        entries, seen = [], set()
        offered = payload if isinstance(payload, list) else []
        for entry in offered:
            if not isinstance(entry, dict) or not isinstance(entry.get("correction"), str):
                continue
            index = entry.get("index")
            if isinstance(index, float) and index.is_integer():
                index = int(index)
            if isinstance(index, str) and index.strip().isdecimal():
                try:
                    index = int(index)
                except ValueError:
                    continue
            # 1.7 or True is no turn's index.
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                continue
            correction = entry["correction"].strip()
            if not correction or index in seen or (turns is not None and index not in turns):
                continue
            seen.add(index)
            turn = turns[index] if turns is not None else entry
            if turn.get("unread"):
                # An unreadable transcript file's stand-in, not a turn.
                continue
            errors = []
            for e in entry.get("errors") or []:
                if e in error_types and e not in errors:
                    errors.append(e)
            entries.append({"index": index, "start": turn.get("start"), "end": turn.get("end"),
                            "errors": errors, "correction": correction})
        if len(entries) < len(offered):
            logger.warning("Transcript prediction for %r: %d of %d suggestion(s) left out "
                           "(no such turn, a repeated turn, or no correction)",
                           name, len(offered) - len(entries), len(offered))
        return {name: json.dumps(entries, ensure_ascii=False)} if entries else None
    if atype == "video_annotation":
        # Tracks, for a tracking or combined scheme: a box per keyframe as
        # fractions of the picture. A box off the picture, or a label the
        # scheme does not have, would be drawn and then saved as it is.
        if str(scheme.get("mode") or "").lower() not in ("tracking", "combined"):
            return None
        tracks = payload.get("tracks") if isinstance(payload, dict) else None
        if not isinstance(tracks, dict):
            return None
        labels = set(_label_names(scheme))
        kept, dropped = {}, 0
        for track_id, track in tracks.items():
            if not isinstance(track, dict) or (labels and str(track.get("label")) not in labels):
                dropped += 1
                continue
            keyframes = {}
            for key, kf in (track.get("keyframes") or {}).items():
                box = kf.get("bboxNorm") if isinstance(kf, dict) else None
                try:
                    x, y, w, h = (float(box[k]) for k in ("x", "y", "width", "height"))
                    frame = int(kf.get("frame", key))
                except (TypeError, ValueError, KeyError):
                    dropped += 1
                    continue
                if (not all(math.isfinite(v) for v in (x, y, w, h))
                        or w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001
                        or y + h > 1.0001):
                    dropped += 1
                    continue
                # No canvas box: the page computes it in its own pixels.
                keyframes[str(frame)] = dict({k: v for k, v in kf.items() if k != "bbox"},
                                             frame=frame, type="bbox")
            if keyframes:
                frames = [int(f) for f in keyframes]
                kept[str(track_id)] = dict(track, keyframes=keyframes,
                                           startFrame=min(frames), endFrame=max(frames))
        if dropped:
            logger.warning("Track prediction for %r: %d track(s) or keyframe(s) left out",
                           name, dropped)
        if not kept:
            return None
        meta = payload.get("video_metadata") if isinstance(payload.get("video_metadata"), dict) \
            else {}
        return {"_data": json.dumps({"video_metadata": meta, "segments": [],
                                     "frame_annotations": {}, "keyframes": [], "tracking": {},
                                     "tracks": kept}, ensure_ascii=False)}
    if atype == "volume_annotation":
        # Painted masks, per label and axial slice. A slice whose runs do not
        # add up to the volume's slice, or past its last slice, would be
        # decoded across the wrong voxels by the widget, then saved.
        if not isinstance(payload, dict) or not isinstance(payload.get("masks"), dict):
            return None
        try:
            ni, nj, nk = (int(n) for n in payload.get("shape") or ())
        except (TypeError, ValueError):
            return None
        if min(ni, nj, nk) <= 0:
            return None
        labels = set(_label_names(scheme))
        masks, dropped = {}, 0
        for label, slices in payload["masks"].items():
            if str(label) not in labels or not isinstance(slices, dict):
                dropped += 1
                continue
            kept = {}
            for k, counts in slices.items():
                try:
                    index = int(k)
                    total = sum(int(c) for c in counts)
                except (TypeError, ValueError, OverflowError):
                    dropped += 1
                    continue
                if 0 <= index < nk and total == ni * nj and all(int(c) >= 0 for c in counts):
                    kept[str(index)] = [int(c) for c in counts]
                else:
                    dropped += 1
            if kept:
                masks[str(label)] = kept
        if dropped:
            logger.warning("Volume prediction for %r: %d label(s) or slice(s) left out that "
                           "do not fit the scheme or the volume", name, dropped)
        if not masks:
            return None
        return {"_data": json.dumps({
            "volume": str(payload.get("volume") or ""), "shape": [ni, nj, nk],
            "labels": [l for l in _label_names(scheme)], "masks": masks, "shapes": [],
            "prefilled_from": "model"})}
    if atype == "region_caption":
        captions = payload.get("captions") if isinstance(payload, dict) else None
        captions = [c for c in captions if isinstance(c, dict) and valid_shape(c.get("region"))
                    and isinstance(c.get("caption"), str)] if isinstance(captions, list) else []
        if not captions:
            return None
        return {"_data": json.dumps({"captions": captions}, ensure_ascii=False)}
    return None
