"""One readable line per change, for the session's activity panel.

"added span PERSON 'Obama'", "removed bbox car", "sentiment: neutral →
negative". Works from ops alone (``{key, before, after}``) plus the config's
scheme list, so the log can be re-described after the fact.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

from potato.collab.state import EVENT, LABEL, LINK, SPAN, split_label_key

_MAX_QUOTE = 40


def _schemes(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {s.get("name"): s for s in (config or {}).get("annotation_schemes") or []
            if isinstance(s, dict) and s.get("name")}


def _quote(text: Any) -> str:
    text = str(text)
    if len(text) > _MAX_QUOTE:
        text = text[:_MAX_QUOTE - 1] + "…"
    return f"'{text}'"


def _single_select(scheme: Optional[Dict[str, Any]]) -> bool:
    return bool(scheme) and scheme.get("annotation_type") in (
        "radio", "likert", "select", "confidence")


def _load(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _singular(key: str) -> str:
    return key[:-1] if key.endswith("s") and len(key) > 1 else key


def _walk(data: Any, kind: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    """(kind, element) for every drawn or listed element, at any depth.

    A list of objects is a collection (its key, singular, names the kind:
    ``segments`` -> segment, a tier ``words`` -> word); so is a mapping whose
    values are all flat records (frame annotations by frame, turns by id).
    Elements are not looked inside: a segment's own answers are part of it.
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(data, list):
        if data and all(isinstance(d, dict) for d in data):
            out.extend((kind, d) for d in data)
        return out
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        if isinstance(v, list):
            out.extend(_walk(v, _singular(str(k))))
        elif isinstance(v, dict) and v and all(
                isinstance(r, dict) and not any(isinstance(x, (dict, list)) for x in r.values())
                for r in v.values()):
            out.extend((_singular(str(k)), r) for r in v.values())
        elif isinstance(v, dict):
            out.extend(_walk(v, kind))
    return out


def _elements(value: Any) -> List[Tuple[str, str]]:
    """(kind, label) for each drawn element in a blob scheme's JSON."""
    out = []
    for kind, d in _walk(_load(value)):
        out.append((str(d.get("type") or kind or "item"),
                    str(d.get("label") or d.get("name") or d.get("text") or "")))
    return out


def _without_ids(counter: Counter) -> Counter:
    out: Counter = Counter()
    for text, n in counter.items():
        element = json.loads(text)
        if isinstance(element, dict):
            element = {k: v for k, v in element.items() if k != "id"}
        out[json.dumps(element, sort_keys=True)] += n
    return out


def _describe_blob(schema: str, before: Any, after: Any) -> List[str]:
    old_items, new_items = _walk(_load(before)), _walk(_load(after))
    key = lambda d: json.dumps(d, sort_keys=True)
    old = Counter(key(d) for _, d in old_items)
    new = Counter(key(d) for _, d in new_items)
    if old != new and _without_ids(old) == _without_ids(new):
        # A page gave ids to shapes stored before ids existed.
        return ["shape ids added, nothing moved"]
    added, removed = new - old, old - new
    if not added and not removed:
        return [f"changed {schema}"]

    def describe(items, wanted: Counter) -> Counter:
        left, out = Counter(wanted), Counter()
        for kind, d in items:
            if left[key(d)] > 0:
                left[key(d)] -= 1
                out[(str(d.get("type") or kind or "item"),
                     str(d.get("label") or d.get("name") or d.get("text") or ""))] += 1
        return out

    added_desc, removed_desc = describe(new_items, added), describe(old_items, removed)
    lines = []
    # An element whose kind and label survive is an edit (moved, resized).
    edited = added_desc & removed_desc
    for (kind, label), n in (added_desc - edited).items():
        lines.append(f"added {kind}{' ' + label if label else ''}"
                     + (f" ×{n}" if n > 1 else ""))
    for (kind, label), n in (removed_desc - edited).items():
        lines.append(f"removed {kind}{' ' + label if label else ''}"
                     + (f" ×{n}" if n > 1 else ""))
    for (kind, label), n in edited.items():
        lines.append(f"changed {kind}{' ' + label if label else ''}"
                     + (f" ×{n}" if n > 1 else ""))
    return lines


def _is_structured(value: Any) -> bool:
    return isinstance(value, str) and value[:1] in ("[", "{") and isinstance(
        _load(value), (list, dict))


def _describe_span(op: Dict[str, Any], item_text: Optional[str]) -> str:
    before, after = op.get("before"), op.get("after")
    span = (after or before or {}).get("span") or {}
    label = span.get("name") or "span"
    where = ""
    text = span.get("text")
    if not text and item_text and span.get("target_field") is None:
        try:
            text = item_text[int(span["start"]):int(span["end"])]
        except (KeyError, TypeError, ValueError):
            text = None
    if text:
        where = " " + _quote(text)
    elif span.get("start") is not None:
        where = f" [{span.get('start')}–{span.get('end')}]"
    if before is None:
        return f"added span {label}{where}"
    if after is None:
        return f"removed span {label}{where}"
    return f"changed span {label}{where}"


def describe_ops(ops: Iterable[Dict[str, Any]], config: Dict[str, Any],
                 item_text: Optional[str] = None) -> List[str]:
    """``item_text`` (the item's plain text) lets a span be quoted."""
    schemes = _schemes(config)
    lines: List[str] = []
    label_ops: Dict[str, List[Dict[str, Any]]] = {}
    for op in ops:
        key = op["key"]
        if key.startswith(LABEL):
            schema, _ = split_label_key(key)
            label_ops.setdefault(schema, []).append(op)
        elif key.startswith(SPAN):
            lines.append(_describe_span(op, item_text))
        elif key.startswith(LINK):
            link = op.get("after") or op.get("before") or {}
            verb = "added" if op.get("before") is None else (
                "removed" if op.get("after") is None else "changed")
            lines.append(f"{verb} link {link.get('link_type', '')}".rstrip())
        elif key.startswith(EVENT):
            ev = op.get("after") or op.get("before") or {}
            verb = "added" if op.get("before") is None else (
                "removed" if op.get("after") is None else "changed")
            lines.append(f"{verb} event {ev.get('event_type', '')}".rstrip())

    for schema, sops in label_ops.items():
        scheme = schemes.get(schema)
        blob = [op for op in sops if split_label_key(op["key"])[1] == "_data"]
        for op in blob:
            for line in _describe_blob(schema, op.get("before"), op.get("after")):
                lines.append(line if line == f"changed {schema}" else f"{line} ({schema})")
        rest = [op for op in sops if op not in blob]
        if not rest:
            continue
        if _single_select(scheme):
            old = [split_label_key(op["key"])[1] for op in rest if op.get("before") is not None]
            new = [split_label_key(op["key"])[1] for op in rest if op.get("after") is not None]
            if old and new:
                lines.append(f"{schema}: {', '.join(old)} → {', '.join(new)}")
            elif new:
                lines.append(f"{schema}: chose {', '.join(new)}")
            else:
                lines.append(f"{schema}: cleared {', '.join(old)}")
            continue
        for op in rest:
            label = split_label_key(op["key"])[1]
            before, after = op.get("before"), op.get("after")
            if _is_structured(before) or _is_structured(after):
                # A widget's JSON answer under a plain label (agent traces,
                # trees, graphs, ...): describe what it holds, not its text.
                for line in _describe_blob(schema, before, after):
                    lines.append(line if line == f"changed {schema}" else f"{line} ({schema})")
                continue
            kind = (scheme or {}).get("annotation_type")
            if kind in ("text", "textbox", "number", "slider", "vas") or (
                    isinstance(after, str) and after not in ("true", label)):
                if after is None:
                    lines.append(f"{schema}: cleared")
                elif before is None:
                    lines.append(f"{schema}: set to {_quote(after)}")
                else:
                    lines.append(f"{schema}: {_quote(before)} → {_quote(after)}")
            elif after is None:
                lines.append(f"{schema}: removed {label}")
            else:
                lines.append(f"{schema}: added {label}")
    return lines


# ----------------------------------------------------------------------
# Whole answers (the reveal panel, replay)


def unit_title(unit: str) -> str:
    """'stance', 'ner spans', 'links: supports'."""
    kind, name = unit[:2], unit[2:]
    if kind == LABEL:
        return name
    if kind == SPAN:
        return f"{name} spans" if name else "spans"
    if kind == LINK:
        return f"links: {name}" if name else "links"
    if kind == EVENT:
        return f"events: {name}" if name else "events"
    return unit


def describe_unit(unit: str, snapshot: Dict[str, Any], config: Dict[str, Any],
                  item_text: Optional[str] = None) -> str:
    """One member's answer to one unit, as a short phrase ('—' when none)."""
    from potato.collab.state import unit_of
    entries = [(k, v) for k, v in snapshot.items() if unit_of(k, v) == unit]
    if not entries:
        return "—"
    kind = unit[:2]
    if kind == LABEL:
        scheme = _schemes(config).get(unit[2:]) or {}
        parts = []
        for key, value in sorted(entries):
            label = split_label_key(key)[1]
            if label == "_data":
                counts = Counter(lbl or kind for kind, lbl in _elements(value))
                parts.append(", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
                             if counts else "—")
            elif scheme.get("annotation_type") in ("text", "textbox", "number", "slider",
                                                   "vas") or (
                    isinstance(value, str) and value not in ("true", label)):
                parts.append(_quote(value))
            else:
                parts.append(label)
        return ", ".join(parts)
    if kind == SPAN:
        parts = []
        for _, value in sorted(entries, key=lambda e: int(((e[1] or {}).get("span") or {})
                                                          .get("start") or 0)):
            span = (value or {}).get("span") or {}
            text = span.get("text")
            if not text and item_text and span.get("target_field") is None:
                try:
                    text = item_text[int(span["start"]):int(span["end"])]
                except (KeyError, TypeError, ValueError):
                    text = None
            parts.append(f"{span.get('name', 'span')} {_quote(text)}" if text
                         else f"{span.get('name', 'span')} [{span.get('start')}–{span.get('end')}]")
        return "; ".join(parts)
    return f"{len(entries)}"


def describe_snapshot(snapshot: Dict[str, Any], config: Dict[str, Any],
                      item_text: Optional[str] = None) -> List[str]:
    """The whole answer, one line per unit: 'stance: con'."""
    from potato.collab.state import answer_units
    return [f"{unit_title(unit)}: {describe_unit(unit, snapshot, config, item_text)}"
            for unit in sorted(answer_units(snapshot))]
