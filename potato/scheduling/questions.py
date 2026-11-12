"""
The questions a scheduled session asks (a wave, an experience-sampling
prompt).

Session pages are short questionnaires that a participant answers many times
(a daily prompt) or weeks apart (a wave), so their answers are kept per
session in the schedule store rather than as phase-page answers in
``user_state.json``, which holds one answer per question and is rewritten in
full on every save.

A question is written like an annotation scheme, with the subset of types a
repeated questionnaire needs::

    - annotation_type: likert          # radio | likert | multiselect |
      name: mood                       # slider | number | text
      description: "How do you feel right now?"
      size: 7
      min_label: "Very bad"
      max_label: "Very good"
      required: true                   # or label_requirement: {required: true}

``questions_file`` may name a JSON or YAML file holding such a list, in the
same format as a phase-page survey file.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

QUESTION_TYPES = ("radio", "likert", "multiselect", "slider", "number", "text")
_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TEXT_MAX = 4000

_KEYS = {
    "common": {"name", "annotation_type", "description", "required", "label_requirement"},
    "radio": {"labels", "horizontal"},
    "multiselect": {"labels"},
    "likert": {"size", "min_label", "max_label"},
    "slider": {"min_value", "max_value", "starting_value", "step", "min_label", "max_label"},
    "number": {"min_value", "max_value", "integer"},
    "text": {"multiline", "max_length"},
}


def _labels(q: dict) -> List[Tuple[str, str]]:
    out = []
    for lab in q.get("labels") or []:
        if isinstance(lab, dict):
            name = str(lab.get("name", ""))
            out.append((name, str(lab.get("text") or name)))
        else:
            out.append((str(lab), str(lab)))
    return out


def is_required(q: dict) -> bool:
    if q.get("required") is True:
        return True
    lr = q.get("label_requirement")
    return isinstance(lr, dict) and lr.get("required") is True


def validate_questions(questions: Any, where: str) -> List[dict]:
    """Check a question list and return it normalised. Raises ValueError."""
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"{where} must be a non-empty list of questions")
    seen = set()
    out = []
    for i, q in enumerate(questions):
        at = f"{where}[{i}]"
        if not isinstance(q, dict):
            raise ValueError(f"{at} must be a mapping")
        qtype = q.get("annotation_type")
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"{at}.annotation_type must be one of {', '.join(QUESTION_TYPES)} "
                             f"(got {qtype!r})")
        name = q.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError(f"{at}.name must be letters, digits, _ or - (got {name!r})")
        if name in seen:
            raise ValueError(f"{at}.name {name!r} is used twice")
        seen.add(name)
        if not isinstance(q.get("description"), str) or not q["description"].strip():
            raise ValueError(f"{at}.description must be the question text")
        unknown = set(q) - _KEYS["common"] - _KEYS[qtype]
        if unknown:
            raise ValueError(f"{at} has keys a {qtype} question does not read: "
                             f"{', '.join(sorted(map(str, unknown)))}")
        if "required" in q and not isinstance(q["required"], bool):
            raise ValueError(f"{at}.required must be true or false")
        if qtype in ("radio", "multiselect"):
            labels = _labels(q)
            if len(labels) < 2 or any(not n for n, _t in labels):
                raise ValueError(f"{at}.labels must list at least two named options")
            if any(isinstance(lab, bool) for lab in q.get("labels") or []):
                raise ValueError(f"{at}.labels holds true/false: YAML reads a bare Yes/No as "
                                 "a boolean, so quote them (\"Yes\")")
            if len({n for n, _t in labels}) != len(labels):
                raise ValueError(f"{at}.labels has a repeated option")
        elif qtype == "likert":
            size = q.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or not 2 <= size <= 11:
                raise ValueError(f"{at}.size must be a whole number from 2 to 11")
        elif qtype in ("slider", "number"):
            lo, hi = q.get("min_value", 0 if qtype == "slider" else None), \
                q.get("max_value", 100 if qtype == "slider" else None)
            for key, val in (("min_value", lo), ("max_value", hi)):
                if val is not None and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                    raise ValueError(f"{at}.{key} must be a number")
            if lo is not None and hi is not None and hi <= lo:
                raise ValueError(f"{at}.max_value must be greater than min_value")
            if qtype == "slider":
                step = q.get("step", 1)
                if not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0:
                    raise ValueError(f"{at}.step must be a positive number")
                start = q.get("starting_value", lo)
                if not isinstance(start, (int, float)) or not lo <= start <= hi:
                    raise ValueError(f"{at}.starting_value must lie between min_value and max_value")
        elif qtype == "text":
            ml = q.get("max_length", 1000)
            if not isinstance(ml, int) or isinstance(ml, bool) or not 1 <= ml <= TEXT_MAX:
                raise ValueError(f"{at}.max_length must be a whole number from 1 to {TEXT_MAX}")
        out.append(dict(q))
    return out


def load_questions(entry: dict, where: str, config_dir: Optional[str]) -> List[dict]:
    """``questions`` inline or from ``questions_file`` (relative to the
    config's directory, which must contain it)."""
    has_inline = "questions" in entry
    has_file = "questions_file" in entry
    if has_inline == has_file:
        raise ValueError(f"{where} needs exactly one of questions or questions_file")
    if has_inline:
        return validate_questions(entry["questions"], f"{where}.questions")
    rel = entry["questions_file"]
    if not isinstance(rel, str) or not rel:
        raise ValueError(f"{where}.questions_file must be a path")
    path = resolve_file(rel, config_dir, f"{where}.questions_file")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith((".yaml", ".yml")):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return validate_questions(data, f"{where}.questions_file ({rel})")


def resolve_file(rel: str, config_dir: Optional[str], where: str) -> str:
    """An existing file under the config directory, through the shared path
    security check."""
    base = os.path.abspath(config_dir or ".")
    candidate = rel if os.path.isabs(rel) else os.path.join(base, rel)
    try:
        from potato.server_utils.config_module import validate_path_security
        validate_path_security(candidate, base)
    except ImportError:  # pragma: no cover
        pass
    except Exception as exc:
        raise ValueError(f"{where}: {exc}")
    real = os.path.realpath(candidate)
    if not os.path.isfile(real):
        raise ValueError(f"{where}: file not found: {rel}")
    if os.path.getsize(real) > 2 * 1024 * 1024:
        raise ValueError(f"{where}: {rel} is larger than 2 MB")
    return real


# --------------------------------------------------------------------------
# Rendering helpers (the template does the HTML; this prepares the values)
# --------------------------------------------------------------------------

def view_model(questions: List[dict], answers: Optional[dict] = None) -> List[dict]:
    """What session.html needs for each question, with any saved answer."""
    answers = answers or {}
    out = []
    for q in questions:
        qtype = q["annotation_type"]
        item = {"name": q["name"], "type": qtype, "text": q["description"],
                "required": is_required(q), "value": answers.get(q["name"])}
        if qtype in ("radio", "multiselect"):
            item["options"] = [{"name": n, "text": t} for n, t in _labels(q)]
            item["horizontal"] = bool(q.get("horizontal"))
        elif qtype == "likert":
            item["options"] = [{"name": str(v), "text": str(v)} for v in range(1, q["size"] + 1)]
            item["min_label"] = q.get("min_label", "")
            item["max_label"] = q.get("max_label", "")
        elif qtype == "slider":
            item.update(min=q.get("min_value", 0), max=q.get("max_value", 100),
                        step=q.get("step", 1), start=q.get("starting_value", q.get("min_value", 0)),
                        min_label=q.get("min_label", ""), max_label=q.get("max_label", ""))
        elif qtype == "number":
            item.update(min=q.get("min_value"), max=q.get("max_value"),
                        step=1 if q.get("integer") else "any")
        elif qtype == "text":
            item.update(multiline=bool(q.get("multiline", True)),
                        max_length=q.get("max_length", 1000))
        out.append(item)
    return out


def parse_answers(questions: List[dict], form) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Answers from a submitted form, and ``{question: problem}``.

    ``form`` is a werkzeug MultiDict (or a dict of lists). Values outside the
    question's options or range are refused rather than stored."""
    def getlist(key):
        if hasattr(form, "getlist"):
            return form.getlist(key)
        v = form.get(key)
        return v if isinstance(v, list) else ([] if v is None else [v])

    answers: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for q in questions:
        name, qtype = q["name"], q["annotation_type"]
        raw = [v for v in getlist(name) if isinstance(v, str)]
        value: Any = None
        if qtype in ("radio", "likert"):
            allowed = ([n for n, _t in _labels(q)] if qtype == "radio"
                       else [str(v) for v in range(1, q["size"] + 1)])
            if raw and raw[0] != "":
                if raw[0] not in allowed:
                    errors[name] = "Choose one of the options."
                    continue
                value = int(raw[0]) if qtype == "likert" else raw[0]
        elif qtype == "multiselect":
            allowed = [n for n, _t in _labels(q)]
            chosen = [v for v in raw if v]
            if any(v not in allowed for v in chosen):
                errors[name] = "Choose from the options."
                continue
            value = [n for n in allowed if n in chosen] or None
        elif qtype in ("slider", "number"):
            touched = qtype == "number" or (getlist(f"{name}__touched") or [""])[0] == "1"
            if raw and raw[0].strip() != "" and touched:
                try:
                    num = float(raw[0])
                except ValueError:
                    errors[name] = "Enter a number."
                    continue
                lo = q.get("min_value", 0 if qtype == "slider" else None)
                hi = q.get("max_value", 100 if qtype == "slider" else None)
                if (lo is not None and num < lo) or (hi is not None and num > hi):
                    errors[name] = f"Enter a value from {lo} to {hi}."
                    continue
                if qtype == "number" and q.get("integer") and num != int(num):
                    errors[name] = "Enter a whole number."
                    continue
                value = int(num) if num == int(num) else num
        elif qtype == "text":
            text = (raw[0] if raw else "").strip()
            if len(text) > q.get("max_length", 1000):
                errors[name] = f"Keep the answer under {q.get('max_length', 1000)} characters."
                continue
            value = text or None
        if value is None:
            if is_required(q):
                errors[name] = "This question needs an answer."
            continue
        answers[name] = value
    return answers, errors
