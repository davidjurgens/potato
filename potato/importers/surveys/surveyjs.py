"""
SurveyJS JSON (the SurveyJS Form Library's survey model) into Potato survey pages.

Reads the JSON that SurveyJS Creator saves and that ``new Survey.Model(json)``
loads: ``{"pages": [{"name", "elements": [...], "visibleIf"}], "triggers": [...]}``
(or a single page given as top-level ``elements``).

Mapped:

* ``text`` (number inputs to ``number``), ``comment``, ``radiogroup``,
  ``checkbox``, ``dropdown``, ``tagbox``, ``boolean``, ``rating``,
  ``ranking``, ``matrix``, ``multipletext``, ``html``, ``slider``;
  ``panel`` contents are flattened into the page, the panel's ``visibleIf``
  ANDed onto each question.
* ``isRequired``, ``hasOther`` (free-text "Other"), ``hasNone``,
  ``choicesOrder: random``, page ``questionsOrder: random``.
* ``visibleIf`` on questions, panels and pages, through the shared
  expression translator; ``complete`` triggers become ``exit_when`` on the
  page that asks the last question they test.

Reported, not mapped: ``enableIf``, ``requiredIf``, ``choicesVisibleIf``,
validators, calculated values and ``expression`` questions, ``setvalue`` /
``skip`` / ``runexpression`` triggers, dynamic matrices and panels, file and
signature questions, and logic that calls functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, and_rules,
    strip_html, unique_labels)
from .expr import SURVEYJS, VarInfo, parse, to_rule, unparse


def _text(value: Any) -> str:
    """A SurveyJS localizable string: plain, or {"default": ..., "de": ...}."""
    if isinstance(value, dict):
        for key in ("default", "en"):
            if key in value:
                return str(value[key])
        return str(next(iter(value.values()), ""))
    return "" if value is None else str(value)


def _choices(raw: Any) -> List[Dict[str, str]]:
    out = []
    for c in raw or []:
        if isinstance(c, dict):
            value = c.get("value")
            text = _text(c.get("text")) or str(value)
        else:
            value, text = c, str(c)
        out.append({"value": str(value), "text": strip_html(text)})
    return out


class SurveyJSImporter:
    format_name = "surveyjs"
    description = "SurveyJS survey JSON (Form Library / Creator)"
    file_extensions = [".json"]

    def detect_path(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.lower() != ".json":
            return False
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        return self._looks_like(data)

    @staticmethod
    def _looks_like(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        pages = data.get("pages")
        if isinstance(pages, list) and pages and all(isinstance(p, dict) for p in pages):
            return any(isinstance(p.get("elements") or p.get("questions"), list) for p in pages)
        elements = data.get("elements") or data.get("questions")
        return (isinstance(elements, list) and bool(elements)
                and all(isinstance(e, dict) and "type" in e for e in elements))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        with Path(path).open(encoding="utf-8") as f:
            data = json.load(f)
        return self.parse(data, options or {})

    # ------------------------------------------------------------------

    def parse(self, data: Dict[str, Any], options: dict) -> SurveyImportResult:
        if not self._looks_like(data):
            raise ValueError("not a SurveyJS survey: expected `pages` with `elements`")
        result = SurveyImportResult(source_format="SurveyJS", title=strip_html(_text(data.get("title"))))
        raw_pages = data.get("pages") or [{"name": "page1", "elements": data.get("elements") or data.get("questions")}]
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})
        self.vars: Dict[str, VarInfo] = {}
        self.result = result
        self.question_page: Dict[str, str] = {}
        pending = []  # (page, element-or-page, kind, expression, where)

        for p_idx, raw in enumerate(raw_pages, start=1):
            page = SurveyPage(name=self.page_names.take(raw.get("name") or f"page{p_idx}", "page"),
                              title=strip_html(_text(raw.get("title"))))
            if raw.get("description") or raw.get("title"):
                intro = {
                    "name": self.names.take(f"{page.name}_intro", "intro"),
                    "annotation_type": "pure_display",
                    "description": page.title or strip_html(_text(raw.get("description"))),
                }
                # pure_display refuses an empty labels list; leave it out.
                if raw.get("description") and page.title:
                    intro["labels"] = [strip_html(_text(raw.get("description")))]
                page.questions.append(intro)
            for el in raw.get("elements") or raw.get("questions") or []:
                self._element(el, page, None, pending)
            if str(raw.get("questionsOrder", "")).lower() == "random":
                page.randomize_questions = True
            if raw.get("visibleIf"):
                pending.append((page, None, "page", raw["visibleIf"], f"page '{page.name}'"))
            for key in ("enableIf", "requiredIf"):
                if raw.get(key):
                    result.skip(f"page '{page.name}'", key, raw[key])
            result.pages.append(page)

        if str(data.get("questionsOrder", "")).lower() == "random":
            for page in result.pages:
                page.randomize_questions = True

        # Logic last: a rule may reference a question asked on a later page.
        for page, scheme, kind, expression, where in pending:
            rule = self._rule(expression, where)
            if rule is None:
                continue
            if kind == "page":
                page.show_when = and_rules(page.show_when, rule)
            else:
                current = scheme.get("display_logic")
                scheme["display_logic"] = and_rules(current, rule)

        self._triggers(data.get("triggers") or [])
        for key in ("calculatedValues", "completedHtmlOnCondition"):
            if data.get(key):
                result.skip("survey", key, json.dumps(data[key])[:200])
        return result

    # ------------------------------------------------------------------

    def _rule(self, expression: str, where: str):
        try:
            return to_rule(parse(expression, SURVEYJS), self._resolve)
        except Untranslatable as e:
            self.result.skip(where, "visibleIf", f"{expression} ({e})")
            return None

    def _resolve(self, ref: str) -> VarInfo:
        base = ref.split(".")[0]
        if ref in self.vars:
            return self.vars[ref]
        if base in self.vars and ref.endswith(".length"):
            return VarInfo(schema=self.vars[base].schema, kind="count")
        if base in self.vars and "." in ref:
            raise Untranslatable(f"a reference into {base} ({ref})")
        raise Untranslatable(f"unknown question {ref!r}")

    def _element(self, el: Dict[str, Any], page: SurveyPage, panel_rule_expr: Optional[str],
                 pending: list) -> None:
        etype = str(el.get("type", "")).lower()
        src = str(el.get("name") or etype)
        where = f"page '{page.name}' / '{src}'"
        if etype == "panel":
            inner = el.get("elements") or el.get("questions") or []
            vis = el.get("visibleIf")
            combined = (f"({panel_rule_expr}) and ({vis})" if panel_rule_expr and vis
                        else vis or panel_rule_expr)
            title = strip_html(_text(el.get("title")))
            if title:
                page.questions.append({"name": self.names.take(f"{src}_title", "panel"),
                                       "annotation_type": "pure_display", "description": title})
                if combined:
                    pending.append((page, page.questions[-1], "question", combined, where))
            for child in inner:
                self._element(child, page, combined, pending)
            return
        vis = el.get("visibleIf")
        combined = (f"({panel_rule_expr}) and ({vis})" if panel_rule_expr and vis
                    else vis or panel_rule_expr)
        if etype == "multipletext":
            # One text question per item; Potato has no grouped text box.
            title = strip_html(_text(el.get("title")))
            for it in el.get("items") or []:
                iname = self.names.take(f"{src}_{it.get('name')}")
                label = strip_html(_text(it.get("title"))) or str(it.get("name"))
                q = {"name": iname, "annotation_type": "text",
                     "description": f"{title}: {label}" if title else label}
                if el.get("isRequired") or it.get("isRequired"):
                    q["label_requirement"] = {"required": True}
                page.questions.append(q)
                self.question_page[iname] = page.name
                self.vars[f"{src}.{it.get('name')}"] = VarInfo(schema=iname, kind="text")
                self.result.name_map[f"{src}.{it.get('name')}"] = iname
                if combined:
                    pending.append((page, q, "question", combined, where))
            self.result.warnings.append(f"{where}: multipletext imported as separate text questions")
            return
        scheme = self._scheme(el, etype, where)
        if scheme is None:
            return
        scheme["description"] = scheme.get("description") or strip_html(_text(el.get("title"))) or src
        if el.get("isRequired") and scheme["annotation_type"] != "pure_display":
            scheme["label_requirement"] = {"required": True}
        page.questions.append(scheme)
        self.question_page[scheme["name"]] = page.name
        self.result.name_map[src] = scheme["name"]
        if combined:
            pending.append((page, scheme, "question", combined, where))
        for key in ("enableIf", "requiredIf", "choicesVisibleIf", "choicesEnableIf"):
            if el.get(key):
                self.result.skip(where, key, el[key])
        if el.get("validators"):
            self.result.skip(where, "validators", json.dumps(el["validators"])[:200])
        if el.get("defaultValue") is not None:
            self.result.skip(where, "defaultValue", json.dumps(el["defaultValue"]))

    def _scheme(self, el: Dict[str, Any], etype: str, where: str) -> Optional[Dict[str, Any]]:
        src = str(el.get("name") or etype)
        name = self.names.take(src)

        def choice_scheme(atype: str, extra_labels=()):
            choices = _choices(el.get("choices"))
            labels = unique_labels([c["text"] for c in choices] + list(extra_labels))
            values = {c["value"]: lab for c, lab in zip(choices, labels)}
            for extra, lab in zip(extra_labels, labels[len(choices):]):
                values[{"Other (describe)": "other", "None": "none"}.get(extra, extra)] = lab
            kind = "multi" if atype == "multiselect" else "single"
            self.vars[src] = VarInfo(schema=name, kind=kind, values=values)
            scheme = {"name": name, "annotation_type": atype, "labels": labels}
            if str(el.get("choicesOrder", "")).lower() == "random":
                scheme["randomize_order"] = True
            if el.get("choicesByUrl") or el.get("choicesFromQuestion"):
                self.result.skip(where, "dynamic choices",
                                 json.dumps(el.get("choicesByUrl") or el.get("choicesFromQuestion")))
            return scheme

        if etype in ("radiogroup", "dropdown"):
            extra = ["None"] if el.get("hasNone") or el.get("showNoneItem") else []
            scheme = choice_scheme("radio" if etype == "radiogroup" else "select", extra)
            if el.get("hasOther") or el.get("showOtherItem"):
                scheme["has_free_response"] = {"instruction": strip_html(_text(el.get("otherText"))) or "Other (please specify)"}
                self.vars[src].values["other"] = "other"
            return scheme
        if etype in ("checkbox", "tagbox"):
            extra = ["None"] if el.get("hasNone") or el.get("showNoneItem") else []
            scheme = choice_scheme("multiselect", extra)
            if el.get("hasOther") or el.get("showOtherItem"):
                scheme["has_free_response"] = {"instruction": strip_html(_text(el.get("otherText"))) or "Other (please specify)"}
            if el.get("hasSelectAll") or el.get("showSelectAllItem"):
                self.result.skip(where, "select-all option")
            return scheme
        if etype == "boolean":
            yes = strip_html(_text(el.get("labelTrue"))) or "Yes"
            no = strip_html(_text(el.get("labelFalse"))) or "No"
            labels = unique_labels([yes, no])
            values = {"true": labels[0], "false": labels[1], "True": labels[0], "False": labels[1]}
            if "valueTrue" in el:
                values[str(el["valueTrue"])] = labels[0]
            if "valueFalse" in el:
                values[str(el["valueFalse"])] = labels[1]
            self.vars[src] = VarInfo(schema=name, kind="single", values=values)
            return {"name": name, "annotation_type": "radio", "labels": labels, "horizontal": True}
        if etype == "rating":
            if el.get("rateValues"):
                choices = _choices(el["rateValues"])
                labels = unique_labels([c["text"] for c in choices])
                self.vars[src] = VarInfo(schema=name, kind="single",
                                         values={c["value"]: l for c, l in zip(choices, labels)})
                return {"name": name, "annotation_type": "radio", "labels": labels, "horizontal": True}
            lo = int(el.get("rateMin", 1))
            hi = int(el.get("rateMax", el.get("rateCount", 5) + lo - 1 if "rateCount" in el else 5))
            step = int(el.get("rateStep", 1)) or 1
            points = list(range(lo, hi + 1, step))
            labels = [str(p) for p in points]
            self.vars[src] = VarInfo(schema=name, kind="single", values={l: l for l in labels})
            min_label = strip_html(_text(el.get("minRateDescription")))
            max_label = strip_html(_text(el.get("maxRateDescription")))
            if lo == 1 and step == 1:
                return {"name": name, "annotation_type": "likert", "size": len(points),
                        "min_label": min_label or labels[0], "max_label": max_label or labels[-1]}
            return {"name": name, "annotation_type": "radio", "labels": labels, "horizontal": True}
        if etype == "text":
            itype = str(el.get("inputType", "text")).lower()
            if itype in ("number", "range"):
                self.vars[src] = VarInfo(schema=name, kind="number")
                scheme = {"name": name, "annotation_type": "number"}
                if el.get("min") is not None:
                    scheme["min"] = el["min"]
                if el.get("max") is not None:
                    scheme["max"] = el["max"]
                if el.get("step") is not None:
                    scheme["step"] = el["step"]
                return scheme
            self.vars[src] = VarInfo(schema=name, kind="text")
            scheme = {"name": name, "annotation_type": "text"}
            if el.get("placeholder") or el.get("placeHolder"):
                scheme["placeholder"] = strip_html(_text(el.get("placeholder") or el.get("placeHolder")))
            if itype not in ("text", "number", "range"):
                self.result.warnings.append(f"{where}: input type '{itype}' imported as plain text")
            return scheme
        if etype == "comment":
            self.vars[src] = VarInfo(schema=name, kind="text")
            return {"name": name, "annotation_type": "text",
                    "textarea": {"on": True, "rows": int(el.get("rows", 4))}}
        if etype == "ranking":
            choices = _choices(el.get("choices"))
            labels = unique_labels([c["text"] for c in choices])
            self.vars[src] = VarInfo(schema=name, kind="multi",
                                     values={c["value"]: l for c, l in zip(choices, labels)})
            return {"name": name, "annotation_type": "ranking", "labels": labels}
        if etype == "matrix":
            rows = _choices(el.get("rows"))
            cols = _choices(el.get("columns"))
            # A reference to one row ({m.row}) is not translated
            self.vars[src] = VarInfo(schema=name, kind="text")
            return {"name": name, "annotation_type": "multirate",
                    "options": unique_labels([r["text"] for r in rows]),
                    "labels": unique_labels([c["text"] for c in cols])}
        if etype == "html":
            # pure_display refuses an empty description, so an untitled html
            # element shows its text as the description.
            title = strip_html(_text(el.get("title")))
            body = strip_html(_text(el.get("html")))
            scheme = {"name": name, "annotation_type": "pure_display",
                      "description": title or body or src}
            if title and body:
                scheme["labels"] = [body]
            return scheme
        if etype == "slider":
            self.vars[src] = VarInfo(schema=name, kind="number")
            lo, hi = el.get("min", 0), el.get("max", 100)
            return {"name": name, "annotation_type": "slider", "min_value": lo, "max_value": hi,
                    "starting_value": el.get("defaultValue", lo), "step": el.get("step", 1)}
        self.names._used.discard(name)
        self.result.skip(where, f"question type '{etype}'", strip_html(_text(el.get("title"))))
        return None

    def _triggers(self, triggers: List[Dict[str, Any]]) -> None:
        for i, trig in enumerate(triggers):
            ttype = str(trig.get("type", "")).lower()
            where = f"trigger {i + 1}"
            expression = trig.get("expression")
            if ttype != "complete" or not expression:
                self.result.skip(where, f"'{ttype}' trigger", expression or "")
                continue
            try:
                tree = parse(expression, SURVEYJS)
                rule = to_rule(tree, self._resolve)
            except Untranslatable as e:
                self.result.skip(where, "complete trigger", f"{expression} ({e})")
                continue
            from potato.server_utils.display_logic import iter_leaf_conditions
            refs = [c["schema"] for _p, c in iter_leaf_conditions(rule["show_when"])]
            pages = [p.name for p in self.result.pages]
            last = max((pages.index(self.question_page[r]) for r in refs if r in self.question_page),
                       default=None)
            if last is None:
                self.result.skip(where, "complete trigger", expression)
                continue
            page = self.result.pages[last]
            rule["message"] = "Thank you. This is the end of the study."
            if page.exit_when:
                self.result.skip(where, "a second complete trigger on one page", unparse(tree))
                continue
            page.exit_when = rule
