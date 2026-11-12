"""Snapshots, diffs and the three-way merge behind a shared team answer.

A team's answer for an item lives in the team user's ``UserState`` like any
annotator's. Everything here works on a flat *snapshot* of that answer:

    {"L:<schema>:::<label>": value,          # labels, including blob "_data"
     "S:<span id>":          {"span": {...}, "value": v},
     "K:<link id>":          {...},          # span links
     "E:<event id>":         {...}}          # event annotations

A key is one thing a person can change on its own. ``diff`` turns two
snapshots into ops ``{key, before, after}``; the session log keeps those ops,
which is both the per-item history and how ``state_at`` reconstructs what the
answer looked like at an earlier revision.

Why a server-side merge: ``/updateinstance`` receives the page's whole answer
for the item, not a delta. A member whose page has not yet shown a teammate's
change would send that change's *old* value back, and storing the payload as
sent would undo the teammate's work. ``merge_payload`` compares the payload
with the revision the member's page reflects (the base) and keeps only what
the member changed since then.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

LABEL = "L:"
SPAN = "S:"
LINK = "K:"
EVENT = "E:"

# Values the core treats as "no answer" for a label.
_EMPTY = (None, "")


def label_key(schema: str, label: str) -> str:
    return f"{LABEL}{schema}:::{label}"


def split_label_key(key: str) -> Tuple[str, str]:
    schema, _, label = key[len(LABEL):].partition(":::")
    return schema, label


def _jsonable(value: Any) -> Any:
    """Values as they survive a JSON round trip, so before/after compare."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def item_snapshot(user_state, instance_id: str) -> Dict[str, Any]:
    """The flat snapshot of one item's answer in ``user_state``."""
    snap: Dict[str, Any] = {}
    labels = user_state.get_label_annotations(instance_id) or {}
    for label, value in labels.items():
        if value in _EMPTY:
            continue
        snap[label_key(label.get_schema(), label.get_name())] = _jsonable(value)
    spans = user_state.get_span_annotations(instance_id) or {}
    for span, value in spans.items():
        snap[SPAN + str(span.get_id())] = {"span": _jsonable(span.to_dict()),
                                           "value": _jsonable(value)}
    getter = getattr(user_state, "get_link_annotations", None)
    for link_id, link in ((getter(instance_id) or {}).items() if getter else ()):
        snap[LINK + str(link_id)] = _jsonable(link.to_dict())
    getter = getattr(user_state, "get_event_annotations", None)
    for event_id, event in ((getter(instance_id) or {}).items() if getter else ()):
        snap[EVENT + str(event_id)] = _jsonable(event.to_dict())
    return snap


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ops turning ``before`` into ``after``, in a stable key order."""
    ops = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            ops.append({"key": key, "before": old, "after": new})
    return ops


def unapply(snapshot: Dict[str, Any], ops: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Undo ``ops`` (given in the order they were applied) on a copy."""
    snap = dict(snapshot)
    for op in reversed(list(ops)):
        if op.get("before") is None:
            snap.pop(op["key"], None)
        else:
            snap[op["key"]] = op["before"]
    return snap


def labels_of(snapshot: Dict[str, Any]) -> Dict[Tuple[str, str], Any]:
    return {split_label_key(k): v for k, v in snapshot.items() if k.startswith(LABEL)}


def spans_of(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {k[len(SPAN):]: v for k, v in snapshot.items() if k.startswith(SPAN)}


# ----------------------------------------------------------------------
# The merge


def payload_span_id(span_data: Dict[str, Any]) -> Optional[str]:
    """The id ``/updateinstance`` will give this span (same formula)."""
    try:
        fc = span_data.get("format_coords") or {}
        return str(span_data.get("id") or span_data.get("span_id") or
                   (f"{span_data['schema']}_{span_data['name']}_"
                    f"{fc.get('anchor_kind', '')}_{fc.get('page', '')}_"
                    f"{span_data['start']}_{span_data['end']}"))
    except (KeyError, TypeError, AttributeError):
        return None


def _span_signature(span: Dict[str, Any], value: Any) -> Tuple:
    """What makes two spans with one id the same answer."""
    return (span.get("schema"), span.get("name"), _int(span.get("start")),
            _int(span.get("end")), json.dumps(_jsonable(value), sort_keys=True),
            json.dumps(_jsonable(span.get("additional_parts") or []), sort_keys=True))


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


class MergeResult:
    """A rewritten payload plus what it overrode."""

    def __init__(self, payload: Dict[str, Any], conflicts: List[Dict[str, Any]],
                 changed: bool):
        self.payload = payload
        #: keys where this save replaced a teammate's newer value:
        #: {key, base, theirs, mine}
        self.conflicts = conflicts
        #: False when the save, measured against its base, changes nothing.
        self.changed = changed


def merge_payload(payload: Dict[str, Any], base: Dict[str, Any], current: Dict[str, Any],
                  *, split_key, is_single_select, is_multiselect,
                  keep_theirs: bool = False) -> MergeResult:
    """Rewrite a frontend-format ``/updateinstance`` payload against ``current``.

    ``base`` is the snapshot the member's page reflects, ``current`` the team's
    answer now. The result carries only the member's own changes since
    ``base``, laid over ``current``:

    - a key the member did not change takes the current value, so a stale
      page cannot revert a teammate's edit;
    - a single-select scheme is one key (its chosen option);
    - a span the payload repeats unchanged from the base is dropped, so a span
      a teammate deleted is not put back by a page that still shows it;
    - removals are written out explicitly (``""`` for a label), because the
      core only clears exclusive schemes by absence.

    ``split_key``, ``is_single_select`` and ``is_multiselect`` are the server's
    own readers, passed in so this module has no Flask or config imports.

    ``keep_theirs`` (``conflict_policy: reject``) settles every conflict for
    the current value instead of the member's: the conflicts are still
    reported, and the member's changes nobody else touched still go in.
    """
    payload = copy.deepcopy(payload)
    conflicts: List[Dict[str, Any]] = []

    # ---------------- labels
    raw = payload.get("annotations") or {}
    if not isinstance(raw, dict):
        return MergeResult(payload, [], True)
    cleared = payload.get("cleared_schemas") or []
    cleared = {c for c in cleared if isinstance(c, str)} if isinstance(cleared, list) else set()

    sent: Dict[Tuple[str, str], Any] = {}
    for key, value in raw.items():
        parsed = split_key(key)
        if parsed is None:
            continue
        sent[(parsed[0], parsed[1])] = value
    schemas_sent = {s for s, _ in sent} | cleared

    base_labels, cur_labels = labels_of(base), labels_of(current)

    def scheme_labels(labels, schema):
        return {l: v for (s, l), v in labels.items() if s == schema}

    final: Dict[str, Dict[str, Any]] = {}   # schema -> its whole final answer
    for schema in sorted(schemas_sent):
        base_s = scheme_labels(base_labels, schema)
        cur_s = scheme_labels(cur_labels, schema)
        mine_given = {l: v for (s, l), v in sent.items() if s == schema}
        if is_single_select(schema) or is_multiselect(schema):
            # The payload is the scheme's complete answer.
            mine_s = {l: v for l, v in mine_given.items() if v not in _EMPTY}
        else:
            # Only the keys sent say anything; the rest are untouched.
            mine_s = dict(base_s)
            for l, v in mine_given.items():
                if v in _EMPTY:
                    mine_s.pop(l, None)
                else:
                    mine_s[l] = v
        mine_s = {l: _jsonable(v) for l, v in mine_s.items()}

        if is_single_select(schema):
            if _norm(mine_s) == _norm(base_s):
                continue
            if _norm(cur_s) != _norm(base_s) and _norm(cur_s) != _norm(mine_s):
                conflicts.append({"key": f"{LABEL}{schema}", "base": base_s,
                                  "theirs": cur_s, "mine": mine_s})
                if keep_theirs:
                    continue
            final[schema] = mine_s
            continue

        result = dict(cur_s)
        touched = False
        for l in set(base_s) | set(mine_s):
            if _same(base_s.get(l), mine_s.get(l)):
                continue
            theirs = cur_s.get(l)
            blob = merge_blob(base_s.get(l), mine_s.get(l), theirs, keep_theirs=keep_theirs)
            if blob is not None:
                # A drawing: merged element by element, so two members' shapes
                # both survive and only a shape both changed is a conflict.
                merged_value, element_conflicts = blob
                for c in element_conflicts:
                    conflicts.append(dict(c, key=label_key(schema, l), element=c["element"]))
                if merged_value is not None and _same(merged_value, theirs):
                    continue                  # nothing of mine survived the merge
                touched = True
                if merged_value is not None:
                    result[l] = merged_value
                elif mine_s.get(l) is not None:
                    result[l] = mine_s[l]     # the page's own empty drawing, as sent
                else:
                    result.pop(l, None)
                continue
            if not _same(theirs, base_s.get(l)) and not _same(theirs, mine_s.get(l)):
                conflicts.append({"key": label_key(schema, l), "base": base_s.get(l),
                                  "theirs": theirs, "mine": mine_s.get(l)})
                if keep_theirs:
                    continue
            touched = True
            if mine_s.get(l) is None:
                result.pop(l, None)
            else:
                result[l] = mine_s[l]
        if touched:
            final[schema] = result

    annotations: Dict[str, Any] = {}
    new_cleared = []
    for schema, answer in final.items():
        for l, v in answer.items():
            annotations[f"{schema}:::{l}"] = v
        for l in scheme_labels(cur_labels, schema):
            if l not in answer:
                annotations[f"{schema}:::{l}"] = ""
        if not answer and is_multiselect(schema):
            new_cleared.append(schema)
    payload["annotations"] = annotations
    payload["cleared_schemas"] = new_cleared

    # ---------------- spans
    base_spans, cur_spans = spans_of(base), spans_of(current)
    kept_spans = []
    for span_data in payload.get("span_annotations") or []:
        if not isinstance(span_data, dict):
            continue
        sid = payload_span_id(span_data)
        if sid is None:
            kept_spans.append(span_data)
            continue
        value = span_data.get("value")
        in_base = base_spans.get(sid)
        if value is None:
            # A deletion: only meaningful if the span existed for this page.
            if in_base is None and sid not in cur_spans:
                continue
            kept_spans.append(span_data)
            continue
        if in_base is not None and (_span_signature(in_base["span"], in_base["value"])
                                    == _span_signature(span_data, value)):
            continue  # unchanged since the base: say nothing about it
        theirs = cur_spans.get(sid)
        if in_base is not None and theirs != in_base:
            conflicts.append({"key": SPAN + sid, "base": in_base, "theirs": theirs,
                              "mine": {"span": span_data, "value": value}})
            if keep_theirs:
                continue
        kept_spans.append(span_data)
    if "span_annotations" in payload:
        payload["span_annotations"] = kept_spans

    changed = bool(annotations or new_cleared or kept_spans
                   or payload.get("link_annotations") or payload.get("event_annotations"))
    return MergeResult(payload, conflicts, changed)


def _canon(value: Any) -> Any:
    """A value in a form where equal answers compare equal.

    Blob schemes (image, audio, video, ...) store a JSON string, and a widget
    that re-serializes an unchanged answer may order keys differently. Read
    as text, that is a change, and a change wins over a teammate's newer one.
    """
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        # An empty drawing is no drawing. A widget that serializes its empty
        # canvas as "[]" must not read as a page that cleared a teammate's
        # shapes.
        if parsed in ([], {}):
            return None
        return json.dumps(parsed, sort_keys=True)
    if value == "":
        return None
    return value


def _same(a: Any, b: Any) -> bool:
    return _canon(a) == _canon(b)


def _norm(answer: Dict[str, Any]) -> Dict[str, Any]:
    return {l: _canon(v) for l, v in answer.items() if v not in _EMPTY}


def changed_keys(ops: Iterable[Dict[str, Any]]) -> Set[str]:
    return {op["key"] for op in ops}


# ----------------------------------------------------------------------
# Writing snapshot values back (revert, restore)


def write_values(user_state, instance_id: str, values: Dict[str, Any]) -> None:
    """Set each snapshot key to a value, or remove it when the value is None.

    Removals go first: a single-select scheme's revert removes one option and
    adds another, and adding first would leave the store briefly holding both
    (and the add evicts siblings, which the later removal would then miss).
    """
    from potato.item_state_management import EventAnnotation, Label, SpanAnnotation, SpanLink

    def remove(key):
        if key.startswith(LABEL):
            schema, label = split_label_key(key)
            user_state.remove_label_annotation(instance_id, Label(schema, label))
        elif key.startswith(SPAN):
            sid = key[len(SPAN):]
            spans = user_state.instance_id_to_span_to_value.get(instance_id, {})
            for span in [s for s in spans if str(s.get_id()) == sid]:
                del spans[span]
        elif key.startswith(LINK):
            user_state.remove_link_annotation(instance_id, key[len(LINK):])
        elif key.startswith(EVENT):
            user_state.remove_event_annotation(instance_id, key[len(EVENT):])

    def put(key, value):
        if key.startswith(LABEL):
            schema, label = split_label_key(key)
            user_state.add_label_annotation(instance_id, Label(schema, label), value)
        elif key.startswith(SPAN):
            remove(key)
            d = value.get("span") or {}
            span = SpanAnnotation(
                d["schema"], d["name"], d.get("title", d["name"]),
                int(d["start"]), int(d["end"]), id=d.get("id") or key[len(SPAN):],
                target_field=d.get("target_field"), format_coords=d.get("format_coords"),
                additional_parts=d.get("additional_parts"), kb_id=d.get("kb_id"),
                kb_source=d.get("kb_source"), kb_label=d.get("kb_label"))
            user_state.add_span_annotation(instance_id, span, value.get("value"))
        elif key.startswith(LINK):
            user_state.add_link_annotation(instance_id, SpanLink.from_dict(value))
        elif key.startswith(EVENT):
            user_state.add_event_annotation(instance_id, EventAnnotation.from_dict(value))

    for key, value in values.items():
        if value is None:
            remove(key)
    for key, value in values.items():
        if value is not None:
            put(key, value)


# ----------------------------------------------------------------------
# Comparing whole answers (blind-first reveal)
#
# A *unit* is one question a member answers: a label scheme, the spans of
# one span scheme, the links of one type, the events of one type. Two
# members agree on a unit when their answers to it are the same, whatever
# ids their pages gave the spans.

_ID_FIELDS = {"id", "span_id", "link_id", "event_id", "created_at", "updated_at",
              "timestamp", "annotator", "created_by"}


def unit_of(key: str, value: Any) -> str:
    if key.startswith(LABEL):
        return LABEL + split_label_key(key)[0]
    if key.startswith(SPAN):
        span = (value or {}).get("span") or {}
        return SPAN + str(span.get("schema") or "")
    if key.startswith(LINK):
        return LINK + str((value or {}).get("link_type") or (value or {}).get("schema") or "")
    if key.startswith(EVENT):
        return EVENT + str((value or {}).get("event_type") or (value or {}).get("schema") or "")
    return key


def _strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items() if k not in _ID_FIELDS}
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def _unit_item(key: str, value: Any) -> Any:
    """One snapshot entry as it counts toward its unit's answer."""
    if key.startswith(LABEL):
        return [split_label_key(key)[1], _canon(value)]
    if key.startswith(SPAN):
        span = (value or {}).get("span") or {}
        return [span.get("name"), _int(span.get("start")), _int(span.get("end")),
                span.get("target_field"), _canon((value or {}).get("value"))]
    return json.dumps(_strip_ids(value), sort_keys=True, default=str)


def answer_units(snapshot: Dict[str, Any]) -> Dict[str, str]:
    """unit -> a canonical string of the answer to it (absent when unanswered)."""
    grouped: Dict[str, List[Any]] = {}
    for key, value in snapshot.items():
        item = _unit_item(key, value)
        if key.startswith(LABEL) and item[1] is None:
            continue
        grouped.setdefault(unit_of(key, value), []).append(item)
    return {unit: json.dumps(sorted(items, key=lambda i: json.dumps(i, default=str)),
                             default=str)
            for unit, items in grouped.items() if items}


def compare_answers(answers: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Agreement between members' own answers to one item.

    ``answers`` maps username -> snapshot. Members with an empty answer are
    left out. Returns ``{"units": {unit: {"agree": bool, "members": [...]}},
    "agreement": fraction of units all answering members agree on (None with
    fewer than two), "answered": [...]}``.
    """
    per_member = {u: answer_units(s) for u, s in answers.items()}
    answered = sorted(u for u, units in per_member.items() if units)
    units: Dict[str, Any] = {}
    all_units = sorted({unit for u in answered for unit in per_member[u]})
    for unit in all_units:
        values = [per_member[u].get(unit) for u in answered]
        units[unit] = {"agree": len(answered) >= 2 and len(set(values)) == 1,
                       "members": [u for u in answered if per_member[u].get(unit)]}
    agreement = (sum(1 for u in units.values() if u["agree"]) / len(units)
                 if len(answered) >= 2 and units else None)
    return {"units": units, "agreement": agreement, "answered": answered}


def agreed_values(answers: Dict[str, Dict[str, Any]], comparison: Dict[str, Any]
                  ) -> Dict[str, Any]:
    """Snapshot entries for every unit all answering members agree on.

    Taken from the first answering member's snapshot, so the team answer
    starts from something a member actually gave.
    """
    agreed = {unit for unit, info in comparison["units"].items() if info["agree"]}
    if not agreed or not comparison["answered"]:
        return {}
    source = answers[comparison["answered"][0]]
    return {key: value for key, value in source.items() if unit_of(key, value) in agreed}


# ----------------------------------------------------------------------
# Drawings and media answers: element-level merge
#
# A drawing scheme (image boxes, audio segments, video keyframes, ...)
# stores its whole answer as one JSON value. Merged as one value, two
# members drawing at once lose one member's shapes. ``merge_blob`` merges
# it element by element instead.
#
# The JSON is read as *collections* of elements: a top-level array is one
# collection; in an object, each list of objects and each mapping of objects
# is a collection, and every other key is a plain field merged as a whole.
# An element is known by its ``id``; one without an id (an answer saved
# before ids existed, or a widget that has none) is known by a hash of its
# content, so a moved box without an id reads as one removed and one added --
# which still merges right unless two members moved the same box.


def _parse_blob(value: Any) -> Any:
    """The parsed JSON of a blob value, ``None`` for no answer, or a marker."""
    if value is None or value == "":
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except ValueError:
            return _NOT_BLOB
    return _NOT_BLOB


_NOT_BLOB = object()


def _explicit_id(element: Any) -> Optional[str]:
    if isinstance(element, dict):
        for key in ("id", "_id", "uid"):
            if element.get(key) not in (None, ""):
                return str(element[key])
    return None


def element_id(element: Any) -> str:
    explicit = _explicit_id(element)
    if explicit is not None:
        return explicit
    digest = hashlib.sha1(json.dumps(element, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()[:16]
    return f"h_{digest}"


# Fields that name an element when it has no id: one record per step, turn
# or frame. Matching on them lets two members' edits to one step's record
# meet as one change instead of a removal and an addition (which kept both).
# (Not ``t``: microscopy regions carry ``t`` as the time point they were
# drawn on, and two regions on one time point are two elements.)
NATURAL_KEYS = ("step_index", "turn_id", "turn_index", "step", "turn", "frame", "index")


def _natural_key(lists: List[List[Dict[str, Any]]]) -> Optional[str]:
    """The field every element of these lists is keyed by, if there is one.

    Only for elements without ids, and only when the field is a scalar in
    every element and no two elements of one list share a value: a list with
    several records per step is keyed by content instead.
    """
    elements = [e for lst in lists for e in lst]
    if not elements or any(_explicit_id(e) is not None for e in elements):
        return None
    for key in NATURAL_KEYS:
        def scalar(e):
            v = e.get(key, _ABSENT)
            return isinstance(v, (str, int, float)) and not isinstance(v, bool)
        if not all(scalar(e) for e in elements):
            continue
        if all(len({json.dumps(e[key]) for e in lst}) == len(lst) for lst in lists):
            return key
    return None


def _element_ids(lst: List[Dict[str, Any]], natural: Optional[str]) -> List[str]:
    """One id per element; a repeated id (two identical shapes saved before
    shapes had ids) gets a suffix, so neither copy is lost."""
    seen: Dict[str, int] = {}
    out = []
    for e in lst:
        eid = f"{natural}={json.dumps(e[natural])}" if natural else element_id(e)
        n = seen.get(eid, 0)
        seen[eid] = n + 1
        out.append(eid if n == 0 else f"{eid}#{n}")
    return out


def _is_element_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, dict) for v in value)


def _holds_elements(value: Any) -> bool:
    """A collection of elements, or something that contains one."""
    if isinstance(value, list):
        return bool(value) and all(isinstance(v, dict) for v in value)
    if isinstance(value, dict) and value:
        return all(isinstance(v, dict) for v in value.values()) or not _is_record(value)
    return False


def _is_record(value: Any) -> bool:
    """An element's own fields: no collection of elements anywhere inside."""
    return isinstance(value, dict) and not any(_holds_elements(v) for v in value.values())


def _is_element_map(value: Any) -> bool:
    """{key: record}: frame annotations by frame, tracks by id, ..."""
    return (isinstance(value, dict) and bool(value)
            and all(_is_record(v) for v in value.values()))


def _same_json(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True,
                                                                     default=str)


def _merge_elements(base: Dict[str, Any], mine: Dict[str, Any], cur: Dict[str, Any],
                    order_mine: List[str], order_cur: List[str], where: str,
                    conflicts: List[Dict[str, Any]],
                    keep_theirs: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    result = dict(cur)
    for eid in set(base) | set(mine):
        b, m = base.get(eid), mine.get(eid)
        if _same_json(b, m):
            continue                      # untouched by me: theirs stands
        c = cur.get(eid)
        if not _same_json(c, b) and not _same_json(c, m):
            if all(isinstance(v, dict) for v in (b, m, c)):
                # Both changed one element: field by field, so one member's
                # move and the other's relabel both stand.
                result[eid] = _merge_value(b, m, c, f"{where}{eid}/", conflicts, keep_theirs)
                continue
            conflicts.append({"element": f"{where}{eid}", "base": b, "theirs": c, "mine": m})
            if keep_theirs:
                continue
        if m is None:
            result.pop(eid, None)
        else:
            result[eid] = m
    order = [e for e in order_cur if e in result]
    order += [e for e in order_mine if e in result and e not in order]
    order += [e for e in result if e not in order]
    return result, order


_ABSENT = object()


def _container(v: Any) -> Optional[str]:
    if isinstance(v, list) and _is_element_list(v):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return None


def _merge_value(b: Any, m: Any, c: Any, where: str,
                 conflicts: List[Dict[str, Any]], keep_theirs: bool = False) -> Any:
    """Three-way merge of one part of a drawing answer (``_ABSENT`` = no key)."""
    norm = lambda v: None if v is _ABSENT else v
    if _same_json(norm(b), norm(m)):
        return c                          # untouched by me: theirs stands

    def whole():
        if not _same_json(norm(c), norm(b)) and not _same_json(norm(c), norm(m)):
            conflicts.append({"element": where.rstrip("/") or "*", "base": norm(b),
                              "theirs": norm(c), "mine": norm(m)})
            if keep_theirs:
                return c
        return m

    kind = _container(m)
    if m is _ABSENT or kind is None or _container(c) != kind:
        return whole()
    if b is _ABSENT or b is None:
        b = [] if kind == "list" else {}  # both added: merge against nothing
    elif _container(b) != kind:
        return whole()

    if kind == "list":
        natural = _natural_key([b, m, c])
        ids = {name: _element_ids(lst, natural) for name, lst in (("b", b), ("m", m), ("c", c))}
        by = lambda name, lst: dict(zip(ids[name], lst))
        merged, order = _merge_elements(by("b", b), by("m", m), by("c", c), ids["m"], ids["c"],
                                        where, conflicts, keep_theirs)
        return [merged[e] for e in order]
    # The answer's own top level is fields, never a collection: a mapping of
    # records there reads the same as an object of sub-objects.
    if where and any(_is_element_map(v) for v in (b, m, c)) and all(
            _is_element_map(v) or not v for v in (b, m, c)):
        merged, order = _merge_elements(b, m, c, list(m), list(c), where, conflicts,
                                        keep_theirs)
        return {e: merged[e] for e in order}
    out = {}
    for k in dict.fromkeys(list(c) + list(m) + list(b)):
        value = _merge_value(b.get(k, _ABSENT), m.get(k, _ABSENT), c.get(k, _ABSENT),
                             f"{where}{k}/", conflicts, keep_theirs)
        if value is not _ABSENT:
            out[k] = value
    return out


def _has_content(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return any(_has_content(v) for v in value.values())
    return value not in (None, "", _ABSENT)


def merge_blob(base: Any, mine: Any, current: Any, *, keep_theirs: bool = False
               ) -> Optional[Tuple[Optional[str], List[Dict[str, Any]]]]:
    """Merge one drawing answer element by element.

    Returns ``(merged JSON, or None for no answer; conflicts)``, or None when
    the values are not drawings of one shape (the caller merges them whole).
    """
    parsed = [_parse_blob(v) for v in (base, mine, current)]
    if any(p is _NOT_BLOB for p in parsed):
        return None
    present = [p for p in parsed if p is not None]
    if not present:
        return None
    if len({type(p) for p in present}) != 1:
        return None
    if isinstance(present[0], list) and not all(_is_element_list(p) for p in present):
        return None
    conflicts: List[Dict[str, Any]] = []
    out = _merge_value(*[_ABSENT if p is None else p for p in parsed], "", conflicts,
                       keep_theirs)
    if out is _ABSENT or out is None or not _has_content(out):
        return None, conflicts
    return json.dumps(out), conflicts


def revert_blob(op_before: Any, op_after: Any, current: Any) -> Tuple[bool, Optional[str]]:
    """Undo one edit to a drawing without undoing later ones.

    The edit took the drawing from ``op_before`` to ``op_after``; merging
    ``op_before`` in as if it were a save based on ``op_after`` takes back
    exactly that edit's elements. ``(False, None)`` when it is not a drawing.
    """
    merged = merge_blob(op_after, op_before, current)
    if merged is None:
        return False, None
    return True, merged[0]
