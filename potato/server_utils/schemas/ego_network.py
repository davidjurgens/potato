"""
Ego network schema (``annotation_type: ego_network``).

Personal-network data collection as used in sociology and public health: the
respondent (the ego) names people (alters), answers questions about each of
them, says which of them know each other, and arranges them on a canvas.

One scheme holds an ordered list of ``stages``. All stages share one set of
alters:

=================  =========================================================
name_generator     a prompt ("Who did you talk to about important matters?")
                   and a way to name people: typed free entry, or picks from
                   a fixed ``roster`` / an item field (``roster_field``)
name_interpreter   questions asked about every alter (radio, multiselect,
                   number, text)
dyad_census        for every pair of alters: do they know each other?
                   (optionally: how strongly, with ``strength_labels``)
sociogram          alters as draggable nodes on an SVG canvas; click two
                   nodes to add or remove a tie; positions are saved
=================  =========================================================

The answer is one hidden input holding JSON::

    {"alters": [{"id": "a1", "name": "Ann", "named_in": ["discuss"]}, ...],
     "attributes": {"a1": {"closeness": "very_close"}},
     "ties": [["a1", "a2"], ["a1", "a3", "work"]],
     "positions": {"a1": [0.42, 0.31]},
     "census": {"a1|a2": true, "a1|a3": false},
     "tie_attributes": {"a1|a2": {"strength": "Strong"}}}

A tie is ``[a, b]`` for the default relation, ``[a, b, relation]`` when the
stage that drew it names a ``relation``. Census and tie-attribute keys are
``"a|b"`` or ``"a|b|relation"`` with the two ids in alter order.

``static/ego-network.js`` builds the interface from the normalized stage list
this module puts on the form, and declares what is still missing on the
form's ``data-incomplete-reason`` (see :func:`incomplete_reasons`, which the
exporter uses for the same rules).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .identifier_utils import (
    escape_html_content, generate_element_identifier, generate_layout_attributes,
    generate_validation_attribute, safe_generate_layout)

logger = logging.getLogger(__name__)

STAGE_TYPES = ("name_generator", "name_interpreter", "dyad_census", "sociogram")
QUESTION_TYPES = ("radio", "multiselect", "number", "text")
LAYOUTS = ("steps", "stacked")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

DEFAULT_TITLES = {
    "name_generator": "Name people",
    "name_interpreter": "About each person",
    "dyad_census": "Who knows whom",
    "sociogram": "Arrange your network",
}
DEFAULT_PROMPTS = {
    "name_generator": "Who are the people you talk to about important matters?",
    "name_interpreter": "Answer these questions about each person you named.",
    "dyad_census": "Do {a} and {b} know each other?",
    "sociogram": ("Drag people to arrange them. Click one person and then another "
                  "to draw a line between two people who know each other; do the "
                  "same again to remove it."),
}

_STAGE_KEYS = {
    "common": {"type", "id", "title", "prompt", "instructions"},
    "name_generator": {"min_alters", "max_alters", "roster", "roster_field", "sets",
                       "placeholder"},
    "name_interpreter": {"questions", "required"},
    "dyad_census": {"relation", "strength_labels", "strength_variable", "yes_label",
                    "no_label"},
    "sociogram": {"relation", "allow_ties", "rings"},
}
_QUESTION_KEYS = {"name", "description", "type", "labels", "required", "min", "max",
                  "step", "placeholder"}


class EgoNetworkConfigError(ValueError):
    """An ego_network scheme that cannot be rendered."""


def _label(entry: Any, where: str) -> Dict[str, str]:
    """A choice label as {"name": stored value, "text": shown text}."""
    if isinstance(entry, bool) or entry is None:
        raise EgoNetworkConfigError(
            f"{where}: a label must be a string or {{name, text}}, got {entry!r} "
            "(quote Yes/No in YAML, which reads them as true/false)")
    if isinstance(entry, (str, int, float)):
        text = str(entry).strip()
        if not text:
            raise EgoNetworkConfigError(f"{where}: empty label")
        return {"name": text, "text": text}
    if isinstance(entry, dict):
        name = entry.get("name", entry.get("value"))
        if name is None or isinstance(name, bool) or not str(name).strip():
            raise EgoNetworkConfigError(f"{where}: a label dict needs a non-empty `name`")
        text = entry.get("text") or entry.get("label") or name
        return {"name": str(name), "text": str(text)}
    raise EgoNetworkConfigError(f"{where}: a label must be a string or {{name, text}}")


def _int(value: Any, where: str, lo: int = 0, hi: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo or (hi is not None and value > hi):
        bound = f" between {lo} and {hi}" if hi is not None else f" of at least {lo}"
        raise EgoNetworkConfigError(f"{where} must be a whole number{bound}")
    return value


def _roster(raw: Any, where: str) -> List[Dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise EgoNetworkConfigError(f"{where} must be a non-empty list of names")
    out, ids = [], set()
    for i, entry in enumerate(raw):
        if isinstance(entry, str) and entry.strip():
            out.append({"name": entry.strip()})
            continue
        if isinstance(entry, dict) and str(entry.get("name", "")).strip():
            item = {"name": str(entry["name"]).strip()}
            if entry.get("id") is not None:
                rid = str(entry["id"])
                if rid in ids:
                    raise EgoNetworkConfigError(f"{where}[{i}]: duplicate id {rid!r}")
                ids.add(rid)
                item["id"] = rid
            out.append(item)
            continue
        raise EgoNetworkConfigError(f"{where}[{i}] must be a name or {{id, name}}")
    return out


def _question(raw: Any, where: str, stage_required: bool) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise EgoNetworkConfigError(f"{where} must be a mapping")
    unknown = set(raw) - _QUESTION_KEYS
    if unknown:
        raise EgoNetworkConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    name = raw.get("name")
    if not isinstance(name, str) or not _ID_RE.match(name):
        raise EgoNetworkConfigError(
            f"{where}.name must start with a letter and use letters, digits, _ or -")
    qtype = raw.get("type", "radio")
    if qtype not in QUESTION_TYPES:
        raise EgoNetworkConfigError(f"{where}.type must be one of {', '.join(QUESTION_TYPES)}")
    q: Dict[str, Any] = {"name": name, "type": qtype,
                         "description": str(raw.get("description") or name)}
    required = raw.get("required", stage_required)
    if not isinstance(required, bool):
        raise EgoNetworkConfigError(f"{where}.required must be true or false")
    q["required"] = required
    if qtype in ("radio", "multiselect"):
        labels = raw.get("labels")
        if not isinstance(labels, list) or len(labels) < 2:
            raise EgoNetworkConfigError(f"{where}.labels needs at least two options for a {qtype} question")
        q["labels"] = [_label(l, f"{where}.labels[{i}]") for i, l in enumerate(labels)]
        names = [l["name"] for l in q["labels"]]
        if len(set(names)) != len(names):
            raise EgoNetworkConfigError(f"{where}.labels has duplicate names")
    elif raw.get("labels") is not None:
        raise EgoNetworkConfigError(f"{where}.labels applies to radio and multiselect questions only")
    if qtype == "number":
        for key in ("min", "max", "step"):
            if key in raw:
                if isinstance(raw[key], bool) or not isinstance(raw[key], (int, float)):
                    raise EgoNetworkConfigError(f"{where}.{key} must be a number")
                q[key] = raw[key]
        if "min" in q and "max" in q and q["min"] > q["max"]:
            raise EgoNetworkConfigError(f"{where}: min is greater than max")
    elif any(k in raw for k in ("min", "max", "step")):
        raise EgoNetworkConfigError(f"{where}: min/max/step apply to number questions only")
    if raw.get("placeholder") is not None:
        q["placeholder"] = str(raw["placeholder"])
    return q


def normalize_stages(scheme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The scheme's stages with defaults filled in. Raises EgoNetworkConfigError."""
    stages = scheme.get("stages")
    if not isinstance(stages, list) or not stages:
        raise EgoNetworkConfigError("`stages` must be a non-empty list")
    out: List[Dict[str, Any]] = []
    ids, qnames = set(), set()
    seen_generator = False
    for i, raw in enumerate(stages):
        where = f"stages[{i}]"
        if not isinstance(raw, dict):
            raise EgoNetworkConfigError(f"{where} must be a mapping")
        stype = raw.get("type")
        if stype not in STAGE_TYPES:
            raise EgoNetworkConfigError(f"{where}.type must be one of {', '.join(STAGE_TYPES)}")
        unknown = set(raw) - _STAGE_KEYS["common"] - _STAGE_KEYS[stype]
        if unknown:
            raise EgoNetworkConfigError(
                f"{where} ({stype}): unknown key(s) {', '.join(sorted(unknown))}")
        sid = raw.get("id", f"{stype}_{i + 1}")
        if not isinstance(sid, str) or not _ID_RE.match(sid):
            raise EgoNetworkConfigError(
                f"{where}.id must start with a letter and use letters, digits, _ or -")
        if sid in ids:
            raise EgoNetworkConfigError(f"{where}.id {sid!r} is used by another stage")
        ids.add(sid)
        stage: Dict[str, Any] = {
            "type": stype, "id": sid,
            "title": str(raw.get("title") or DEFAULT_TITLES[stype]),
            "prompt": str(raw.get("prompt") or DEFAULT_PROMPTS[stype]),
        }
        if raw.get("instructions"):
            stage["instructions"] = str(raw["instructions"])
        if stype == "name_generator":
            seen_generator = True
            stage["min_alters"] = _int(raw.get("min_alters", 0), f"{where}.min_alters")
            if raw.get("max_alters") is not None:
                stage["max_alters"] = _int(raw["max_alters"], f"{where}.max_alters", lo=1)
                if stage["max_alters"] < stage["min_alters"]:
                    raise EgoNetworkConfigError(f"{where}: max_alters is less than min_alters")
            if raw.get("roster") is not None and raw.get("roster_field") is not None:
                raise EgoNetworkConfigError(f"{where}: use `roster` or `roster_field`, not both")
            if raw.get("roster") is not None:
                stage["roster"] = _roster(raw["roster"], f"{where}.roster")
            if raw.get("roster_field") is not None:
                if not isinstance(raw["roster_field"], str) or not raw["roster_field"]:
                    raise EgoNetworkConfigError(f"{where}.roster_field must be an item field name")
                stage["roster_field"] = raw["roster_field"]
            sets = raw.get("sets", {})
            if not isinstance(sets, dict) or not all(
                    isinstance(k, str) and _ID_RE.match(k)
                    and (v is None or isinstance(v, (str, int, float, bool)))
                    for k, v in sets.items()):
                raise EgoNetworkConfigError(
                    f"{where}.sets must map attribute names to plain values, e.g. {{support: true}}")
            if sets:
                stage["sets"] = dict(sets)
            if raw.get("placeholder"):
                stage["placeholder"] = str(raw["placeholder"])
        else:
            if not seen_generator:
                raise EgoNetworkConfigError(
                    f"{where} ({stype}) comes before any name_generator stage; "
                    "there is nobody to ask about yet")
        if stype == "name_interpreter":
            required = raw.get("required", False)
            if not isinstance(required, bool):
                raise EgoNetworkConfigError(f"{where}.required must be true or false")
            questions = raw.get("questions")
            if not isinstance(questions, list) or not questions:
                raise EgoNetworkConfigError(f"{where}.questions must be a non-empty list")
            stage["questions"] = []
            for j, q in enumerate(questions):
                nq = _question(q, f"{where}.questions[{j}]", required)
                if nq["name"] in qnames:
                    raise EgoNetworkConfigError(
                        f"{where}.questions[{j}]: name {nq['name']!r} is used by another question "
                        "(answers are stored per alter by question name)")
                qnames.add(nq["name"])
                stage["questions"].append(nq)
        if stype in ("dyad_census", "sociogram"):
            rel = raw.get("relation")
            if rel is not None:
                if not isinstance(rel, str) or not _ID_RE.match(rel):
                    raise EgoNetworkConfigError(
                        f"{where}.relation must start with a letter and use letters, digits, _ or -")
                stage["relation"] = rel
        if stype == "dyad_census":
            stage["yes_label"] = str(raw.get("yes_label") or "Yes")
            stage["no_label"] = str(raw.get("no_label") or "No")
            if raw.get("strength_labels") is not None:
                labels = raw["strength_labels"]
                if not isinstance(labels, list) or len(labels) < 2:
                    raise EgoNetworkConfigError(f"{where}.strength_labels needs at least two options")
                stage["strength_labels"] = [_label(l, f"{where}.strength_labels[{k}]")
                                            for k, l in enumerate(labels)]
                var = raw.get("strength_variable", "strength")
                if not isinstance(var, str) or not _ID_RE.match(var):
                    raise EgoNetworkConfigError(f"{where}.strength_variable must be a plain name")
                stage["strength_variable"] = var
            elif raw.get("strength_variable") is not None:
                raise EgoNetworkConfigError(f"{where}.strength_variable needs strength_labels")
        if stype == "sociogram":
            allow = raw.get("allow_ties", True)
            if not isinstance(allow, bool):
                raise EgoNetworkConfigError(f"{where}.allow_ties must be true or false")
            stage["allow_ties"] = allow
            stage["rings"] = _int(raw.get("rings", 3), f"{where}.rings", lo=0, hi=6)
        out.append(stage)
    return out


def normalize_scheme(scheme: Dict[str, Any]) -> Dict[str, Any]:
    """{"layout", "stages"} for the page. Raises EgoNetworkConfigError."""
    # `layout` is the universal grid-placement mapping every scheme accepts, so
    # the stage arrangement has a key of its own.
    if isinstance(scheme.get("layout"), str):
        raise EgoNetworkConfigError(
            "`layout` is the grid-placement mapping shared by every scheme; "
            f"write `stage_layout: {scheme['layout']}` to arrange the stages")
    layout = scheme.get("stage_layout", "steps")
    if layout not in LAYOUTS:
        raise EgoNetworkConfigError(f"stage_layout must be one of {', '.join(LAYOUTS)}")
    return {"layout": layout, "stages": normalize_stages(scheme)}


# ----------------------------------------------------------------------
# Reading an answer (shared with the exporter)
# ----------------------------------------------------------------------

def parse_answer(raw: Any) -> Optional[Dict[str, Any]]:
    """The stored JSON as a dict with every key present, or None."""
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or not isinstance(raw.get("alters"), list):
        return None
    alters = []
    for a in raw["alters"]:
        if isinstance(a, dict) and a.get("id") is not None:
            alters.append({"id": str(a["id"]), "name": str(a.get("name", "")),
                           "named_in": [str(s) for s in a.get("named_in") or []]})
    ids = {a["id"] for a in alters}
    ties = []
    for t in raw.get("ties") or []:
        if isinstance(t, (list, tuple)) and len(t) in (2, 3) and t[0] in ids and t[1] in ids and t[0] != t[1]:
            ties.append([str(t[0]), str(t[1])] + ([str(t[2])] if len(t) == 3 and t[2] else []))
    return {
        "alters": alters,
        "attributes": {k: v for k, v in (raw.get("attributes") or {}).items()
                       if k in ids and isinstance(v, dict)},
        "ties": ties,
        "positions": {k: v for k, v in (raw.get("positions") or {}).items()
                      if k in ids and isinstance(v, (list, tuple)) and len(v) == 2},
        "census": dict(raw.get("census") or {}),
        "tie_attributes": dict(raw.get("tie_attributes") or {}),
    }


def pair_key(a: str, b: str, relation: Optional[str], order: Dict[str, int]) -> str:
    if order.get(a, 0) > order.get(b, 0):
        a, b = b, a
    return f"{a}|{b}" + (f"|{relation}" if relation else "")


def _answered(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def incomplete_reasons(stages: List[Dict[str, Any]], answer: Optional[Dict[str, Any]]) -> List[str]:
    """What is still missing, in the words the page uses (empty when complete).

    The same rules as ``declare()`` in static/ego-network.js.
    """
    answer = answer or {"alters": [], "attributes": {}, "census": {}}
    alters = answer["alters"]
    order = {a["id"]: i for i, a in enumerate(alters)}
    reasons = []
    for stage in stages:
        if stage["type"] == "name_generator":
            here = [a for a in alters if stage["id"] in a["named_in"]]
            need = stage.get("min_alters", 0)
            if len(here) < need:
                reasons.append(f"{stage['title']}: name at least {need} "
                               f"{'person' if need == 1 else 'people'} ({len(here)} so far)")
        elif stage["type"] == "name_interpreter":
            for q in stage["questions"]:
                if not q.get("required"):
                    continue
                missing = sum(1 for a in alters
                              if not _answered((answer["attributes"].get(a["id"]) or {}).get(q["name"])))
                if missing:
                    text = q["description"].replace("{name}", "this person")
                    reasons.append(f"{stage['title']}: '{text}' unanswered for "
                                   f"{missing} {'person' if missing == 1 else 'people'}")
        elif stage["type"] == "dyad_census":
            n = len(alters)
            total = n * (n - 1) // 2
            done = 0
            for i in range(n):
                for j in range(i + 1, n):
                    key = pair_key(alters[i]["id"], alters[j]["id"], stage.get("relation"), order)
                    if key in answer["census"]:
                        done += 1
            if done < total:
                reasons.append(f"{stage['title']}: {done} of {total} pairs answered")
    return reasons


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------

def generate_ego_network_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    schema_name = annotation_scheme["name"]
    view = normalize_scheme(annotation_scheme)
    esc = escape_html_content(schema_name)
    identifiers = generate_element_identifier(schema_name, schema_name, "hidden")
    validation = generate_validation_attribute(annotation_scheme)
    layout_attrs = generate_layout_attributes(annotation_scheme)
    config = json.dumps({"schema": schema_name, **view})
    html = f"""
    <form id="{esc}" class="annotation-form ego-network" action="javascript:void(0)"
          data-annotation-type="ego_network" data-schema-name="{esc}"
          data-ego-config='{escape_html_content(config)}' {layout_attrs}>
        <fieldset schema="{esc}">
            <legend class="en-title">{escape_html_content(annotation_scheme["description"])}</legend>
            <div class="en-root">
                <p class="en-loading" role="status">Loading…</p>
            </div>
            <input type="hidden" class="annotation-input ego-network-input"
                   id="{identifiers['id']}" name="{identifiers['name']}"
                   schema="{identifiers['schema']}" label_name="{identifiers['label_name']}"
                   validation="{validation}" value="">
        </fieldset>
    </form>
    """
    return html, []
