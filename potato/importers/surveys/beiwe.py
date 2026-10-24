"""
Beiwe survey JSON into Potato survey pages.

Beiwe (the Onnela Lab's smartphone research platform) keeps a survey as a
list of questions under ``content``. Accepted:

* a study settings export: ``{"surveys": [...], "device_settings": ...}``
  (one page per tracking survey);
* one survey: ``{"content": [...], "settings": ..., "timings": ...}``;
* a list of surveys, or a bare ``content`` list of questions.

Mapped:

* ``info_text_box`` (display-only), ``slider`` (``min``/``max``),
  ``radio_button``, ``checkbox``, ``free_response`` (``NUMERIC`` to a number
  question, ``SINGLE_LINE_TEXT``, ``MULTI_LINE_TEXT`` to a text area).
* ``display_if``, the Beiwe JSON logic tree: ``and`` / ``or`` / ``not`` and
  ``[question_id, value]`` comparisons with ``== != < <= > >=``. Radio and
  checkbox answers are compared as 0-based indices into ``answers``, so an
  index becomes the label Potato stores: a radio ``>= 2`` is "one of the
  answers from the third on"; a checkbox ``==`` is "that answer is selected",
  ``!=`` "not selected", and ``<`` / ``>`` "some selected answer qualifies".
  As in the Beiwe app, a comparison on an unanswered question is false.
* ``settings.randomize`` (question order).

Reported, not mapped: ``date`` / ``time`` / ``date_time`` questions, audio
surveys, ``randomize_with_memory``, ``number_of_random_questions``, the
weekly / absolute / relative schedules and ``always_available`` /
``trigger_on_first_download`` (Potato schedules studies separately), and the
study's device settings and consent text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, combine,
    strip_html, unique_labels)

QUESTION_TYPES = {"info_text_box", "slider", "radio_button", "checkbox", "free_response",
                  "date", "time", "date_time"}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_WORD = re.compile(r"[A-Za-z0-9]+")
_COMPARATORS = {"==", "!=", "<", "<=", ">", ">="}
_NUMERIC_OPS = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "==": "equals"}
_TESTS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b,
          "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
          ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}

#: a translated logic node: a display_logic item, or a constant
Node = Union[Dict[str, Any], bool]


def _is_question(q: Any) -> bool:
    return isinstance(q, dict) and str(q.get("question_type", "")).lower() in QUESTION_TYPES


def _surveys(data: Any) -> Optional[List[Dict[str, Any]]]:
    """The surveys in a Beiwe document, or None when it is not one."""
    if isinstance(data, dict):
        if isinstance(data.get("surveys"), list):
            surveys = [s for s in data["surveys"] if isinstance(s, dict) and "content" in s]
            return surveys if surveys and any(_has_questions(s) or s.get("survey_type") == "audio_survey"
                                              for s in surveys) else None
        if isinstance(data.get("content"), list):
            return [data] if _has_questions(data) else None
        return None
    if isinstance(data, list) and data:
        if all(isinstance(s, dict) and isinstance(s.get("content"), list) for s in data):
            return data if any(_has_questions(s) for s in data) else None
        if all(isinstance(q, dict) for q in data) and any(_is_question(q) for q in data) \
                and all("question_type" in q for q in data):
            return [{"content": data}]
    return None


def _has_questions(survey: Dict[str, Any]) -> bool:
    content = survey.get("content")
    return isinstance(content, list) and any(_is_question(q) for q in content)


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() else v


class BeiweImporter:
    format_name = "beiwe"
    description = "Beiwe survey JSON (study settings export or one survey)"
    file_extensions = [".json"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".json":
            return False
        try:
            with path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        return _surveys(data) is not None

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        with Path(path).open(encoding="utf-8-sig") as f:
            data = json.load(f)
        return self.parse(data, options or {})

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> SurveyImportResult:
        surveys = _surveys(data)
        if surveys is None:
            raise ValueError("not a Beiwe survey: expected questions under `content` "
                             "with a Beiwe `question_type`")
        result = SurveyImportResult(source_format="Beiwe")
        self.result = result
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})

        if isinstance(data, dict) and isinstance(data.get("surveys"), list):
            if data.get("device_settings"):
                result.skip("study", "device settings, consent form and app text",
                            "passive sensing, consent_sections and button text are Beiwe app settings")
            if data.get("interventions"):
                result.skip("study", "interventions", ", ".join(map(str, data["interventions"])))

        for s_idx, survey in enumerate(surveys, start=1):
            stype = str(survey.get("survey_type") or "tracking_survey")
            label = str(survey.get("name") or "").strip()
            where = f"survey {s_idx}" + (f" '{label}'" if label else "")
            if stype == "audio_survey":
                prompt = " / ".join(strip_html(c.get("prompt", "")) for c in survey.get("content") or []
                                    if isinstance(c, dict))
                result.skip(where, "audio survey (voice recording)", prompt)
                self._settings(survey, where)
                continue
            if stype != "tracking_survey":
                result.skip(where, f"survey type '{stype}'")
                continue
            page = SurveyPage(name=self.page_names.take(label.lower() or survey.get("object_id")
                                                        or f"survey_{s_idx}", "survey"),
                              title=label)
            self._page(survey, page, where)
            if page.questions:
                result.pages.append(page)
            else:
                result.warnings.append(f"{where} has no questions Potato can show; no page written")
        if not result.pages:
            result.warnings.append("no tracking survey with questions was found")
        return result

    def _settings(self, survey: Dict[str, Any], where: str) -> Dict[str, Any]:
        settings = survey.get("settings") or {}
        if settings.get("randomize_with_memory"):
            self.result.skip(where, "randomize_with_memory (no repeats across sessions)")
        if settings.get("number_of_random_questions") not in (None, "", "None", 0):
            self.result.skip(where, "number_of_random_questions (ask a random subset)",
                             str(settings["number_of_random_questions"]))
        for key in ("always_available", "trigger_on_first_download"):
            if settings.get(key):
                self.result.skip(where, f"schedule setting '{key}'")
        timings = survey.get("timings") or []
        if any(day for day in timings if isinstance(day, list)):
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            detail = "; ".join(
                f"{days[i] if i < 7 else i}: " + ", ".join(f"{int(t) // 3600:02d}:{int(t) % 3600 // 60:02d}"
                                                          for t in day)
                for i, day in enumerate(timings) if isinstance(day, list) and day)
            self.result.skip(where, "weekly schedule (timings)", detail)
        for key in ("absolute_timings", "relative_timings"):
            if survey.get(key):
                self.result.skip(where, f"schedule ({key})", json.dumps(survey[key])[:200])
        return settings

    def _page(self, survey: Dict[str, Any], page: SurveyPage, where: str) -> None:
        settings = self._settings(survey, where)
        if settings.get("randomize"):
            page.randomize_questions = True
        self.questions: Dict[str, Tuple[str, Dict[str, Any], List[str]]] = {}
        pending = []
        for q_idx, q in enumerate(survey.get("content") or [], start=1):
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or f"q{q_idx}")
            qwhere = f"{where} / question {q_idx}"
            scheme = self._scheme(q, qid, q_idx, qwhere)
            if scheme is None:
                continue
            page.questions.append(scheme)
            self.result.name_map[qid] = scheme["name"]
            if q.get("display_if"):
                pending.append((scheme, q["display_if"], qwhere))
        # Logic last: Beiwe allows a reference to any question in the survey.
        for scheme, logic, qwhere in pending:
            try:
                node = self._logic(logic)
            except Untranslatable as e:
                self.result.skip(qwhere, "display_if", f"{json.dumps(logic)[:200]} ({e})")
                continue
            if node is True:
                continue
            if node is False:
                self.result.skip(qwhere, "display_if that is never true", json.dumps(logic)[:200])
                continue
            scheme["display_logic"] = self._as_rule(node)

    @staticmethod
    def _as_rule(item: Dict[str, Any]) -> Dict[str, Any]:
        for key, logic in (("all", "all"), ("any", "any")):
            if set(item) == {key}:
                return combine(item[key], logic)
        return combine([item], "all")

    def _qname(self, q: Dict[str, Any], qid: str, q_idx: int) -> str:
        if qid and not _UUID.match(qid):
            return self.names.take(qid, "q")
        words = _WORD.findall(strip_html(q.get("question_text", "")).lower())[:6]
        slug = "_".join(words)[:40].strip("_")
        return self.names.take(slug or f"q{q_idx}", "q")

    def _scheme(self, q: Dict[str, Any], qid: str, q_idx: int, where: str) -> Optional[Dict[str, Any]]:
        qtype = str(q.get("question_type", "")).lower()
        text = strip_html(q.get("question_text", "")) or qid
        if qtype in ("date", "time", "date_time"):
            self.result.skip(where, f"question type '{qtype}'", text[:200])
            return None
        if qtype not in QUESTION_TYPES:
            self.result.skip(where, f"question type '{qtype}'", text[:200])
            return None
        name = self._qname(q, qid, q_idx)
        if qtype == "info_text_box":
            self.questions[qid] = ("info", {}, [])
            return {"name": name, "annotation_type": "pure_display", "description": text}
        if qtype == "slider":
            lo, hi = _num(q.get("min")), _num(q.get("max"))
            if lo is None or hi is None or lo >= hi:
                self.result.skip(where, "slider range", f"min {q.get('min')!r}, max {q.get('max')!r}")
                lo, hi = (lo, lo + 10) if lo is not None else (0, 10)
            self.questions[qid] = ("number", {"name": name}, [])
            mid = lo + (hi - lo) // 2 if isinstance(lo, int) and isinstance(hi, int) else lo + (hi - lo) / 2
            self.result.warnings.append(f"{where}: the slider starts at its midpoint; Beiwe's "
                                        "starts unanswered")
            return {"name": name, "annotation_type": "slider", "description": text,
                    "min_value": lo, "max_value": hi,
                    "starting_value": int(mid) if float(mid).is_integer() else mid, "step": 1}
        if qtype in ("radio_button", "checkbox"):
            answers = [strip_html(a.get("text", "")) if isinstance(a, dict) else strip_html(a)
                       for a in q.get("answers") or []]
            if not answers:
                self.result.skip(where, f"{qtype} without answers", text[:200])
                return None
            labels = unique_labels(answers)
            kind = "single" if qtype == "radio_button" else "multi"
            self.questions[qid] = (kind, {"name": name}, labels)
            return {"name": name, "annotation_type": "radio" if kind == "single" else "multiselect",
                    "description": text, "labels": labels}
        field = str(q.get("text_field_type") or "SINGLE_LINE_TEXT").upper()
        if field == "NUMERIC":
            self.questions[qid] = ("number", {"name": name}, [])
            return {"name": name, "annotation_type": "number", "description": text}
        self.questions[qid] = ("text", {"name": name}, [])
        scheme = {"name": name, "annotation_type": "text", "description": text}
        if field == "MULTI_LINE_TEXT":
            scheme["textarea"] = {"on": True, "rows": 4}
        elif field != "SINGLE_LINE_TEXT":
            self.result.warnings.append(f"{where}: text_field_type '{field}' imported as one-line text")
        return scheme

    # ------------------------------------------------------------------
    # display_if

    def _logic(self, node: Any) -> Node:
        if node is None or node == {} or node == []:
            return True
        if not isinstance(node, dict) or len(node) != 1:
            raise Untranslatable("a logic node must be an object with one key")
        (op, arg), = node.items()
        op = str(op).lower()
        if op in ("and", "or"):
            if not isinstance(arg, list):
                raise Untranslatable(f"'{op}' needs a list")
            parts = [self._logic(a) for a in arg]
            if op == "and":
                if any(p is False for p in parts):
                    return False
                items = [p for p in parts if p is not True]
                if not items:
                    return True
                return items[0] if len(items) == 1 else {"all": items}
            if any(p is True for p in parts):
                return True
            items = [p for p in parts if p is not False]
            if not items:
                return False
            return items[0] if len(items) == 1 else {"any": items}
        if op == "not":
            inner = self._logic(arg)
            if isinstance(inner, bool):
                return not inner
            return {"not": inner}
        if op in _COMPARATORS:
            return self._compare(op, arg)
        raise Untranslatable(f"unknown operator {op!r}")

    def _compare(self, op: str, arg: Any) -> Node:
        if not isinstance(arg, list) or len(arg) != 2:
            raise Untranslatable(f"'{op}' needs [question_id, value]")
        qid, raw = str(arg[0]), arg[1]
        if qid not in self.questions:
            raise Untranslatable(f"unknown question {qid}")
        kind, ref, labels = self.questions[qid]
        if kind in ("info", "text"):
            raise Untranslatable(f"a comparison on a {'text' if kind == 'text' else 'display-only'} question")
        value = _num(raw)
        if value is None:
            raise Untranslatable(f"{raw!r} is not a number")
        schema = ref["name"]
        answered = {"schema": schema, "operator": "not_empty"}
        if kind == "number":
            if op == "!=":
                return {"all": [answered, {"not": {"schema": schema, "operator": "equals",
                                                   "value": value}}]}
            return {"schema": schema, "operator": _NUMERIC_OPS[op], "value": value}
        test = _TESTS[op]
        if kind == "single":
            match = [lab for i, lab in enumerate(labels) if test(i, value)]
            if not match:
                return False
            if len(match) == len(labels):
                return answered
            return {"schema": schema, "operator": "equals",
                    "value": match[0] if len(match) == 1 else match}
        # checkbox: == / != test whether that answer is selected; an ordering
        # holds when any selected answer satisfies it. Nothing selected: false.
        if op in ("==", "!="):
            idx = int(value) if float(value).is_integer() else None
            if idx is None or not 0 <= idx < len(labels):
                return False if op == "==" else answered
            leaf = {"schema": schema, "operator": "contains", "value": labels[idx]}
            return leaf if op == "==" else {"all": [answered, {"not": leaf}]}
        match = [lab for i, lab in enumerate(labels) if test(i, value)]
        if not match:
            return False
        if len(match) == len(labels):
            return answered
        return {"schema": schema, "operator": "contains",
                "value": match[0] if len(match) == 1 else match}
