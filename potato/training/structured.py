"""Training targets for answers that are structures rather than labels.

A link, a coreference chain or an event is stored as references to span ids,
and those ids come from the annotator's browser: two annotators who drew the
same two spans and linked them the same way have different ids, colours and
link ids. Compared as stored, no two answers would ever agree, and a trainer
would have to chase ids into another scheme's spans.

So each answer is rewritten here, per annotator, into a canonical form that
refers to spans by position in a sorted span list. Two identical answers are
then identical JSON, which is what the bundle's vote and Dawid-Skene compare,
and a trainer reads offsets instead of ids.

Standard library only: the bundle is built in the server process.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["STRUCTURED_KINDS", "LINK_KINDS", "canonical_answer",
           "span_schema_of", "soft_target", "letter_index"]

#: Kinds whose answer refers to another scheme's spans.
LINK_KINDS = ("relation", "coreference", "event")

#: Kinds whose value map is rewritten by :func:`canonical_answer` before the
#: bundle votes on it.
STRUCTURED_KINDS = LINK_KINDS + ("distribution", "gloss", "conversation_tree")


def span_schema_of(scheme: Dict[str, Any]) -> str:
    """The span scheme a link, chain or event scheme draws on."""
    return str(scheme.get("span_schema") or "")


def _spans(raw: Sequence[Any]) -> Tuple[List[Dict[str, Any]],
                                          Dict[str, int], Dict[Tuple[int, int], int]]:
    """Sorted unique spans, and lookups from a span id and from offsets to
    a position in that list."""
    keyed: Dict[Tuple[int, int, str], Dict[str, Any]] = {}
    ids: Dict[Tuple[int, int, str], List[str]] = {}
    for span in raw or []:
        if not isinstance(span, dict):
            continue
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(span.get("name") or span.get("label") or "")
        key = (start, end, label)
        keyed.setdefault(key, {"start": start, "end": end, "label": label})
        if span.get("id"):
            ids.setdefault(key, []).append(str(span["id"]))
    order = sorted(keyed)
    spans = [keyed[k] for k in order]
    by_id: Dict[str, int] = {}
    by_offsets: Dict[Tuple[int, int], int] = {}
    for position, key in enumerate(order):
        for span_id in ids.get(key, []):
            by_id[span_id] = position
        by_offsets.setdefault((key[0], key[1]), position)
    return spans, by_id, by_offsets


def _resolver(by_id: Dict[str, int], by_offsets: Dict[Tuple[int, int], int]):
    def resolve(span_id: Any, position: Any = None) -> Optional[int]:
        if span_id is not None and str(span_id) in by_id:
            return by_id[str(span_id)]
        # A link keeps the offsets of the spans it joined, for when an id
        # has drifted (a span redrawn after the link was made).
        if isinstance(position, dict):
            try:
                return by_offsets.get((int(position["start"]),
                                       int(position["end"])))
            except (KeyError, TypeError, ValueError):
                return None
        return None
    return resolve


def _of_scheme(records: Any, name: str) -> List[Dict[str, Any]]:
    return [r for r in (records or []) if isinstance(r, dict)
            and str(r.get("schema", "")) in ("", name)]


def _link_answer(kind: str, name: str, spans_raw, links, events
                 ) -> Optional[Dict[str, Any]]:
    spans, by_id, by_offsets = _spans(spans_raw)
    resolve = _resolver(by_id, by_offsets)

    if kind == "event":
        out = []
        for event in _of_scheme(events, name):
            trigger = resolve(event.get("trigger_span_id"))
            if trigger is None:
                continue
            arguments = []
            for argument in event.get("arguments") or []:
                if not isinstance(argument, dict):
                    continue
                position = resolve(argument.get("span_id"))
                if position is not None and argument.get("role"):
                    arguments.append({"role": str(argument["role"]),
                                      "span": position})
            arguments.sort(key=lambda a: (a["span"], a["role"]))
            out.append({"type": str(event.get("event_type") or ""),
                        "trigger": trigger, "arguments": arguments})
        out.sort(key=lambda e: (e["trigger"], e["type"]))
        return {"spans": spans, "events": out} if spans else None

    resolved = []
    for link in _of_scheme(links, name):
        span_ids = list(link.get("span_ids") or [])
        positions = list((link.get("properties") or {}).get("span_positions") or [])
        members = [resolve(span_id, positions[n] if n < len(positions) else None)
                   for n, span_id in enumerate(span_ids)]
        if len(members) < (1 if kind == "coreference" else 2) \
                or any(m is None for m in members):
            continue
        resolved.append((link, members))

    if kind == "coreference":
        clusters = []
        for link, members in resolved:
            clusters.append({"type": str(link.get("link_type") or ""),
                             "spans": sorted(set(members))})
        clusters.sort(key=lambda c: c["spans"])
        return {"spans": spans, "clusters": clusters} if spans else None

    out_links = []
    for link, members in resolved:
        directed = str(link.get("direction") or "") == "directed"
        out_links.append({"type": str(link.get("link_type") or ""),
                          # An undirected link has no first span.
                          "spans": members if directed else sorted(members),
                          "directed": directed})
    out_links.sort(key=lambda l: (l["spans"], l["type"]))
    return {"spans": spans, "links": out_links} if spans else None


def _distribution(value_map: Any) -> Optional[Dict[str, float]]:
    """A soft_label answer, ``{label: "60", ...}``, as shares summing to 1."""
    if not isinstance(value_map, dict):
        return None
    masses = {}
    for label, value in value_map.items():
        try:
            masses[str(label)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    total = sum(masses.values())
    if total <= 0:
        return None
    return {label: round(mass / total, 6) for label, mass in sorted(masses.items())}


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _tree_answer(value_map: Any) -> Optional[Dict[str, Any]]:
    """A conversation-tree answer: the selected path, and each node's
    answers. Both are stored as JSON strings in hidden inputs."""
    if not isinstance(value_map, dict):
        return None
    path = _json_value(value_map.get("selected_path"))
    nodes = _json_value(value_map.get("node_annotations"))
    path = [str(p) for p in path] if isinstance(path, list) else []
    nodes = {str(k): v for k, v in nodes.items() if isinstance(v, dict) and v} \
        if isinstance(nodes, dict) else {}
    if not path and not nodes:
        return None
    return {"path": path, "nodes": nodes}


def canonical_answer(kind: str, scheme: Dict[str, Any], value_map: Any = None,
                     spans: Sequence[Any] = (), links: Sequence[Any] = (),
                     events: Sequence[Any] = ()) -> Optional[Any]:
    """One annotator's answer for a structured scheme, canonical, or None
    when they gave none.

    *spans* are that annotator's spans under the scheme's ``span_schema``;
    *links* and *events* their links and events on the item.
    """
    name = str(scheme.get("name") or "")
    if kind in LINK_KINDS:
        return _link_answer(kind, name, spans, links, events)
    if kind == "distribution":
        return _distribution(value_map)
    if kind == "gloss":
        from potato.igt import decode_answer
        answer = decode_answer(value_map)
        if not answer or not any((w.get("gloss") or "").strip()
                                 for w in answer["words"]):
            return None
        return answer
    if kind == "conversation_tree":
        return _tree_answer(value_map)
    return None


def is_tree_answer(answer: Any) -> bool:
    """Whether a relation answer is a dependency tree: every link directed
    with two spans, head first, no span with two heads, and one link fewer
    than spans (so one root)."""
    if not isinstance(answer, dict) or not answer.get("spans"):
        return False
    links = answer.get("links") or []
    if len(links) != len(answer["spans"]) - 1:
        return False
    dependents = set()
    for link in links:
        members = link.get("spans") or []
        if not link.get("directed") or len(members) != 2 or members[1] in dependents:
            return False
        dependents.add(members[1])
    return True


def letter_index(letter: Any) -> Optional[int]:
    """``"A"`` -> 0. BWS stores the tuple position the annotator picked."""
    text = str(letter or "").strip().upper()
    if len(text) == 1 and "A" <= text <= "Z":
        return ord(text) - ord("A")
    return None


def soft_target(kind: str, answers: Sequence[Any], labels_of=None) -> Optional[Dict[str, float]]:
    """The annotators' answers on one item as a distribution over labels.

    *answers* are per-annotator value maps (or, for ``distribution``, the
    canonical shares). Nominal and ordinal: the share of annotators who chose
    each label. Multilabel: the share who ticked each label, so the values
    do not sum to 1. Distribution: the mean of the annotators' shares.
    """
    if not answers:
        return None
    totals: Dict[str, float] = {}
    counted = 0
    for answer in answers:
        if kind == "distribution":
            if not isinstance(answer, dict):
                continue
            for label, share in answer.items():
                totals[str(label)] = totals.get(str(label), 0.0) + float(share)
            counted += 1
            continue
        chosen = labels_of(answer)
        if kind != "multilabel" and len(chosen) != 1:
            continue
        for label in chosen:
            totals[str(label)] = totals.get(str(label), 0.0) + 1.0
        counted += 1
    if not counted:
        return None
    return {label: round(value / counted, 6)
            for label, value in sorted(totals.items())}
