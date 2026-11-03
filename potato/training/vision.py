"""Training targets for the vision answers that are stored as one JSON blob.

``image_annotation`` reaches the bundle already parsed (the export loader
fills ``image_annotations``). The schemes here store their whole answer as a
JSON string in one hidden input instead -- microscopy, geo, region captions,
grounding, GUI step verdicts -- and nothing read them: a grounding scheme was
classified for training but its target was always empty, so every item was
skipped as unlabelled.

Each function takes the scheme's value map (``{label: json}``) and returns
the target the bundle stores, or None when the answer holds nothing to learn.
Standard library only: the bundle is built in the server process.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

__all__ = ["blob", "microscopy_target", "geo_target", "caption_target",
           "grounding_target", "gui_target", "gui_steps", "VISION_KINDS"]

#: Kinds whose target is built here rather than by ``dataset._target_for``.
VISION_KINDS = ("geo", "caption", "grounding", "gui_click")


#: Top-level keys of the answers themselves, which tell an already-parsed
#: one-key answer (``{"captions": [...]}``) from a one-key value map.
_ANSWER_KEYS = {"captions", "regions", "absent", "rois", "cells", "image",
                "features", "type", "spans",
                # A tiered answer, {"annotations": {tier: [...]}}.
                "annotations"}


def blob(value_map: Any) -> Any:
    """The JSON a blob scheme saved, from ``{label: json}`` or the value
    itself. A list (GUI verdicts) is returned as well as an object."""
    def parse(value):
        if isinstance(value, str) and value.strip()[:1] in ("{", "["):
            try:
                return json.loads(value)
            except ValueError:
                return None
        return None

    if isinstance(value_map, list):
        return value_map
    if isinstance(value_map, str):
        return parse(value_map)
    if not isinstance(value_map, dict):
        return None
    for value in value_map.values():
        parsed = parse(value)
        if parsed is not None:
            return parsed
    if len(value_map) == 1 and not set(value_map) & _ANSWER_KEYS:
        # {"_data": ...} or {scheme: ...}: a stored value map whose one value
        # did not parse, unless that value is already the parsed answer.
        only = next(iter(value_map.values()))
        return only if isinstance(only, (dict, list)) and only else None
    # Already the answer itself.
    return value_map or None


def microscopy_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """The ROIs of a microscopy answer: image-widget shapes normalized to the
    full-resolution plane, each with the ``z`` and ``t`` it was drawn on.
    Cell classifications refer to a label image, not to a shape, and are not
    a detection target."""
    answer = blob(value_map)
    if not isinstance(answer, dict):
        return None
    rois = [dict(r) for r in answer.get("rois") or []
            if isinstance(r, dict) and r.get("type") and r.get("label") not in (None, "")]
    return rois or None


def geo_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """The labelled features of a geo answer, GeoJSON in EPSG:4326.

    A ``classify_region`` answer (a label on a region the basemap outlines,
    with no geometry of its own) is not a shape to detect and is left out."""
    answer = blob(value_map)
    if isinstance(answer, dict) and answer.get("type") == "Feature":
        answer = {"features": [answer]}
    if not isinstance(answer, dict):
        return None
    features = []
    for feature in answer.get("features") or []:
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            continue
        label = (feature.get("properties") or {}).get("label")
        if label in (None, ""):
            continue
        features.append({"type": "Feature", "geometry": feature["geometry"],
                         "properties": {"label": str(label)}})
    return features or None


def caption_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """``[{region, caption}]`` from a region_caption answer, in the order the
    regions were drawn. A region nobody captioned is left out."""
    answer = blob(value_map)
    if not isinstance(answer, dict):
        return None
    out = []
    for entry in answer.get("captions") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("region"), dict):
            continue
        caption = str(entry.get("caption") or "").strip()
        if caption:
            out.append({"region": entry["region"], "caption": caption})
    return out or None


def _expressions(scheme: Dict[str, Any], item_data: Dict[str, Any],
                 answer: Dict[str, Any]) -> List[Dict[str, str]]:
    """The expressions an answer refers to by id: the item's list, numbered
    the way the page numbered them, or in spans mode the phrases the
    annotator selected."""
    if (scheme.get("expression_source") or "field") == "spans":
        return [{"id": str(s.get("id")), "text": str(s.get("text") or "")}
                for s in answer.get("spans") or []
                if isinstance(s, dict) and s.get("id") is not None]
    from potato.grounding.routes import normalize_expressions
    return [{"id": e["id"], "text": e["text"]} for e in normalize_expressions(
        item_data.get(scheme.get("expressions_field", "expressions")))]


def grounding_target(scheme: Dict[str, Any], value_map: Any,
                     item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``{"region_type", "expressions": [{id, text, regions, absent}]}``.

    Only expressions the annotator answered, with a region or as absent: an
    unanswered one says nothing about where the phrase points, and
    ``grounding.metrics`` excludes it from scoring for the same reason."""
    answer = blob(value_map)
    if not isinstance(answer, dict):
        return None
    regions = answer.get("regions") or {}
    absent = {str(a) for a in answer.get("absent") or []}
    out = []
    for expression in _expressions(scheme, item_data, answer):
        drawn = [r for r in regions.get(expression["id"]) or []
                 if isinstance(r, dict) and r.get("type")]
        if drawn or expression["id"] in absent:
            out.append(dict(expression, regions=drawn,
                            absent=not drawn and expression["id"] in absent))
    if not out:
        return None
    return {"region_type": str(answer.get("region_type")
                               or scheme.get("region_type") or "box"),
            "expressions": out}


def gui_steps(scheme: Dict[str, Any], item_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The trace's steps as the page reads them: screenshot, action text and
    the agent's click, if it has one. The click is in the trace's
    ``coord_space`` (0-1, or pixels of the screenshot)."""
    steps = item_data.get(scheme.get("steps_key", "steps"))
    screenshot_key = scheme.get("screenshot_key", "screenshot")
    action_key = scheme.get("action_key", "action")
    out = []
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        step = step if isinstance(step, dict) else {}
        point = None
        try:
            if step.get("x") is not None and step.get("y") is not None:
                point = {"x": float(step["x"]), "y": float(step["y"])}
            elif isinstance(step.get("click"), dict) and step["click"].get("x") is not None:
                point = {"x": float(step["click"]["x"]), "y": float(step["click"]["y"])}
        except (TypeError, ValueError):
            point = None
        out.append({"index": index,
                    "screenshot": str(step.get(screenshot_key) or step.get("image") or ""),
                    "action": str(step.get(action_key) or step.get("text")
                                  or step.get("content") or ""),
                    "point": point})
    return out


def gui_target(value_map: Any) -> Optional[List[Dict[str, Any]]]:
    """``[{index, verdict}]`` for the judged steps, keyed by ``index`` (the
    stored list holds only the judged steps, so position means nothing)."""
    answer = blob(value_map)
    if not isinstance(answer, list):
        return None
    out = []
    for entry in answer:
        if not isinstance(entry, dict) or entry.get("verdict") in (None, ""):
            continue
        try:
            index = int(entry.get("index", entry.get("step")))
        except (TypeError, ValueError):
            continue
        out.append({"index": index, "verdict": str(entry["verdict"])})
    return sorted(out, key=lambda e: e["index"]) or None
