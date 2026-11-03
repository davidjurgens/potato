"""A trained model's links, chains and events, as the widgets' own records.

``hf-relation`` predicts in the canonical form of
:mod:`potato.training.structured`: spans as offsets and labels, and links,
chains or events referring to spans by position. The span_link, coreference
and event widgets read SpanLink and EventAnnotation records from
``/api/links`` and ``/api/events``, which refer to spans by id, and draw a
link only between span overlays that exist.

So a prediction becomes two things: spans for the scheme's ``span_schema``,
handed out by ``/api/spans`` with the other span prelabels, and links or
events referring to those spans' ids. The ids are made from the span's
schema, offsets and label, so every route derives the same one, and a span
predicted for two link schemes is one span.

These are prelabels: shown while the annotator has no spans of their own on
the item, flagged ``prelabel``, and stored as theirs only when they move on
(or edit), the way span prelabels are.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["LINK_TYPES", "prelabel_span_id", "predicted_spans",
           "predicted_links", "predicted_events"]

#: Annotation types whose prediction is a canonical link structure.
LINK_TYPES = ("span_link", "coreference", "event_annotation")


def prelabel_span_id(span_schema: str, span: Dict[str, Any]) -> str:
    return "pred_%s_%s_%s_%s" % (span_schema, span.get("start"), span.get("end"),
                                 span.get("label") or span.get("name") or "")


def _schemes(config: Dict[str, Any], pre_data: Optional[Dict[str, Any]], types):
    for scheme in config.get("annotation_schemes", []) or []:
        if scheme.get("annotation_type") not in types or not scheme.get("span_schema"):
            continue
        prediction = (pre_data or {}).get(scheme.get("name"))
        if isinstance(prediction, dict) and isinstance(prediction.get("spans"), list):
            yield scheme, prediction


def _spans(prediction: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for span in prediction.get("spans") or []:
        try:
            out.append({"start": int(span["start"]), "end": int(span["end"]),
                        "label": str(span.get("label") or span.get("name") or "")})
        except (KeyError, TypeError, ValueError):
            out.append(None)
    return out


def predicted_spans(pre_data: Optional[Dict[str, Any]],
                    config: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """``{span_schema: [span, ...]}`` from every link prediction, each span
    with its derived ``id``."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for scheme, prediction in _schemes(config, pre_data, LINK_TYPES):
        span_schema = scheme["span_schema"]
        for span in _spans(prediction):
            if span and span["label"]:
                span_id = prelabel_span_id(span_schema, span)
                out.setdefault(span_schema, {})[span_id] = dict(span, id=span_id)
    return {schema: list(spans.values()) for schema, spans in out.items()}


def _ids(scheme, prediction):
    return [None if s is None else prelabel_span_id(scheme["span_schema"], s)
            for s in _spans(prediction)]


def _position(spans, index):
    try:
        span = spans[int(index)]
    except (IndexError, TypeError, ValueError):
        return None
    return None if span is None else {"start": span["start"], "end": span["end"]}


def _covered(text: str, span) -> str:
    if span is None or not isinstance(text, str):
        return ""
    return text[span["start"]:span["end"]]


def predicted_links(pre_data: Optional[Dict[str, Any]],
                    config: Dict[str, Any], text: str = "") -> List[Dict[str, Any]]:
    """SpanLink records for the span_link and coreference predictions.
    *text* is the item's text, for the span texts a widget lists."""
    out = []
    for scheme, prediction in _schemes(config, pre_data, ("span_link", "coreference")):
        ids, spans = _ids(scheme, prediction), _spans(prediction)
        colours = {str(t.get("name")): t.get("color")
                   for t in scheme.get("link_types") or [] if isinstance(t, dict)}
        groups = (prediction.get("links") if scheme["annotation_type"] == "span_link"
                  else prediction.get("clusters")) or []
        for n, group in enumerate(groups):
            members = list(group.get("spans") or [])
            try:
                span_ids = [ids[int(m)] for m in members]
            except (IndexError, TypeError, ValueError):
                continue
            if None in span_ids or len(span_ids) < 2:
                continue
            directed = scheme["annotation_type"] == "span_link" and bool(group.get("directed"))
            members_spans = [spans[int(m)] for m in members]
            properties = {"span_positions": [_position(spans, m) for m in members],
                          "span_labels": [s["label"] for s in members_spans],
                          "span_texts": [_covered(text, s)[:30] for s in members_spans]}
            if colours.get(str(group.get("type"))):
                properties["color"] = colours[str(group.get("type"))]
            out.append({"id": "pred_link_%s_%d" % (scheme["name"], n),
                        "schema": scheme["name"],
                        "link_type": str(group.get("type") or ""),
                        "span_ids": span_ids,
                        "direction": "directed" if directed else "undirected",
                        "properties": properties, "prelabel": True})
    return out


def predicted_events(pre_data: Optional[Dict[str, Any]],
                     config: Dict[str, Any], text: str = "") -> List[Dict[str, Any]]:
    """EventAnnotation records for the event predictions, with the trigger
    and argument texts the event list shows (from *text*, the item's)."""
    out = []
    for scheme, prediction in _schemes(config, pre_data, ("event_annotation",)):
        ids, spans = _ids(scheme, prediction), _spans(prediction)
        for n, event in enumerate(prediction.get("events") or []):
            try:
                trigger = ids[int(event.get("trigger"))]
                trigger_span = spans[int(event.get("trigger"))]
            except (IndexError, TypeError, ValueError):
                continue
            if trigger is None:
                continue
            arguments = []
            for argument in event.get("arguments") or []:
                try:
                    span_id = ids[int(argument.get("span"))]
                    argument_span = spans[int(argument.get("span"))]
                except (IndexError, TypeError, ValueError):
                    continue
                if span_id and argument.get("role"):
                    arguments.append({"role": str(argument["role"]), "span_id": span_id,
                                      "text": _covered(text, argument_span)})
            out.append({"id": "pred_event_%s_%d" % (scheme["name"], n),
                        "schema": scheme["name"],
                        "event_type": str(event.get("type") or ""),
                        "trigger_span_id": trigger, "arguments": arguments,
                        "properties": {"trigger_text": _covered(text, trigger_span),
                                       "trigger_label": (trigger_span or {}).get("label", "")},
                        "prelabel": True})
    return out
