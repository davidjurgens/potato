"""
LimeSurvey survey structure files (``.lss``) into Potato survey pages.

An ``.lss`` file is an XML dump of LimeSurvey's tables: ``<document>`` with
``<LimeSurveyDocType>Survey</LimeSurveyDocType>``, then one element per table
(``surveys``, ``groups``, ``questions``, ``subquestions``, ``answers``,
``question_attributes``, ``conditions``, ...), each holding ``rows/row``.
Two layouts exist:

* DBVersion below 400 (LimeSurvey 2.x / 3.x): every text row carries a
  ``language`` column, one row per language.
* DBVersion 400 and above (LimeSurvey 4+): the text lives in
  ``group_l10ns`` / ``question_l10ns`` / ``answer_l10ns``.

The survey's base language (``surveys.language``) is used unless
``options["language"]`` names another one.

Mapped:

* Question groups, in ``group_order``, become pages; a group's
  ``grelevance`` becomes the page's ``show_when``. A group description is
  shown at the top of its page.
* ``L`` (list) and ``O`` (list with comment) to radio, ``!`` (dropdown) to
  select, ``5`` (five-point) to a horizontal radio ``1``..``5``, ``Y``
  (yes/no) and ``G`` (gender) to radio, ``M`` / ``P`` (multiple choice) to
  multiselect with the subquestions as options, the arrays ``A`` ``B`` ``C``
  ``E`` ``F`` ``H`` to multirate (rows are the subquestions), ``S`` to text,
  ``T`` / ``U`` to a textarea, ``N`` to number (``min_num_value_n`` /
  ``max_num_value_n``), ``K`` / ``Q`` to one number or text question per
  subquestion, ``R`` to ranking, ``X`` to a display block.
* "Other" options (``other = Y``, answer code ``-oth-``): an extra choice
  (``other_replace_text`` or "Other") plus a free-text box.
* ``use_dropdown`` on a list question (a dropdown).
* ``mandatory = Y``, the ``random_order`` attribute.
* Question ``relevance`` (ExpressionScript) through the shared expression
  translator: question codes with ``.NAOK`` / ``.value``, subquestion codes
  (``Q1_SQ001``), SGQA names (``123456X12X34``), ``is_empty()``, and
  ``count()`` over all the options of a multiple-choice question. When
  ``relevance`` is empty or ``1``, the legacy ``conditions`` table is used:
  conditions on one question are ORed, on different questions ANDed, and
  scenarios ORed.

Reported, not mapped: ``D`` (date, imported as a text box), ``*`` (equation),
``|`` (file upload), ``I`` (language switch), ``1`` (dual-scale array),
``:`` / ``;`` (number and text arrays), the comment fields of ``O`` and
``P``, soft mandatory, hidden questions, validation (``preg``,
``em_validation_q``), answer-count limits, ``array_filter``, timers,
question and group randomization groups, default values, quotas,
assessments, welcome and end texts, piped text, and logic that uses
``.shown`` or functions other than ``is_empty`` and ``count``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # untrusted XML: refuse entity expansion when defusedxml is installed
    from defusedxml.ElementTree import parse as _xml_parse
except ImportError:  # pragma: no cover - expat >= 2.4.1 limits expansion itself
    from xml.etree.ElementTree import parse as _xml_parse

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, and_rules,
    strip_html, unique_labels)
from .expr import LIMESURVEY, VarInfo, compare, parse, to_rule

#: The fixed scales of the array types that have no answer options.
_FIXED_SCALES = {
    "A": [str(i) for i in range(1, 6)],
    "B": [str(i) for i in range(1, 11)],
    "C": ["Yes", "Uncertain", "No"],
    "E": ["Increase", "Same", "Decrease"],
}
_FIXED_CODES = {"C": ["Y", "U", "N"], "E": ["I", "S", "D"]}

_TYPE_NAMES = {
    "1": "array dual scale", ":": "array (numbers)", ";": "array (texts)",
    "*": "equation", "|": "file upload", "I": "language switch",
    "D": "date", "X": "text display",
}

_UNSUPPORTED = {"1", ":", ";", "*", "|", "I"}

#: Question attributes Potato has no equivalent for, reported when set.
_REPORTED_ATTRIBUTES = {
    "em_validation_q": "validation equation",
    "em_validation_sq": "subquestion validation equation",
    "min_answers": "minimum number of answers",
    "max_answers": "maximum number of answers",
    "array_filter": "array filter",
    "array_filter_exclude": "array filter (exclusion)",
    "exclude_all_others": "exclusive option",
    "time_limit": "time limit",
    "equals_num_value": "required total",
    "min_num_value": "minimum total",
    "max_num_value": "maximum total",
    "random_group": "question randomization group",
}

_SGQA = re.compile(r"(?<![A-Za-z0-9_])(\d+)X(\d+)X(\d+)([A-Za-z0-9_#]*)")
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_PIPE = re.compile(r"\{(?:INSERTANS:[^{}]+|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z]+)?)\}")


def _table(root, tag: str) -> List[Dict[str, str]]:
    node = root.find(tag)
    if node is None:
        return []
    return [{c.tag: (c.text or "") for c in row} for row in node.findall("rows/row")]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _num(value: Any) -> Optional[float]:
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() else v


def _pick_language(rows: List[Dict[str, str]], key, lang: str) -> Dict[Any, Dict[str, str]]:
    """One row per key: the one in ``lang``, else the first seen."""
    out: Dict[Any, Dict[str, str]] = {}
    for row in rows:
        k = key(row)
        row_lang = row.get("language", "")
        if k not in out or (row_lang == lang and out[k].get("language", "") != lang):
            out[k] = row
    return out


def _set(value: Any) -> bool:
    return str(value or "").strip() not in ("", "0", "N", "n")


class LimeSurveyImporter:
    format_name = "limesurvey"
    description = "LimeSurvey survey structure (.lss)"
    file_extensions = [".lss"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".lss":
            return False
        try:
            with path.open("rb") as f:
                head = f.read(4096)
        except OSError:
            return False
        return b"<LimeSurveyDocType>" in head and b"<document" in head

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        root = _xml_parse(str(path)).getroot()
        return self.parse(root, options or {}, Path(path).stem)

    # ------------------------------------------------------------------

    def parse(self, root, options: dict, stem: str = "survey") -> SurveyImportResult:
        doctype = (root.findtext("LimeSurveyDocType") or "").strip()
        if root.tag != "document" or doctype.lower() != "survey":
            raise ValueError("not a LimeSurvey survey structure: expected <document> with "
                             "<LimeSurveyDocType>Survey</LimeSurveyDocType>"
                             + (f" (found {doctype!r}; export the whole survey)" if doctype else ""))
        self.version = _int(root.findtext("DBVersion"), 0)
        surveys = _table(root, "surveys")
        survey = surveys[0] if surveys else {}
        languages = [l.text.strip() for l in root.findall("languages/language") if l.text]
        lang = (options.get("language") or survey.get("language") or
                (languages[0] if languages else "en")).strip()
        self.lang = lang
        self.sid = survey.get("sid", "")

        ls: Dict[str, str] = {}
        for row in _table(root, "surveys_languagesettings"):
            if row.get("surveyls_language") == lang or not ls:
                ls = row
        result = SurveyImportResult(source_format="LimeSurvey",
                                    title=strip_html(ls.get("surveyls_title", "")))
        self.result = result
        if self.version >= 400:
            result.warnings.append(f"LimeSurvey DBVersion {self.version} (text from *_l10ns tables), "
                                   f"language '{lang}'")
        for key, what in (("surveyls_welcometext", "welcome text"), ("surveyls_endtext", "end text")):
            text = strip_html(ls.get(key, ""))
            if text:
                result.skip("survey", what, text[:200])

        self._load(root, lang)
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})
        self.vars: Dict[str, VarInfo] = {}
        self.blocked: Dict[str, str] = {}
        self.sgqa: Dict[str, Tuple[str, str]] = {}   # qid -> (title, gid)
        pending = []   # (target, kind, expression, where, qid)

        for q in self.questions.values():
            self.sgqa[q["qid"]] = (q.get("title", ""), q.get("gid", ""))

        groups = sorted(self.groups.values(), key=lambda g: _int(g.get("group_order")))
        by_group: Dict[str, List[Dict[str, str]]] = {}
        for q in self.questions.values():
            by_group.setdefault(q.get("gid", ""), []).append(q)

        for g_idx, grp in enumerate(groups, start=1):
            gid = grp.get("gid", "")
            title = strip_html(grp.get("group_name", ""))
            page = SurveyPage(name=self.page_names.take(title or f"group{g_idx}", "page"), title=title)
            where_g = f"group {gid} '{title}'"
            desc = strip_html(grp.get("description", ""))
            if desc or title:
                intro = {"name": self.names.take(f"{page.name}_intro", "intro"),
                         "annotation_type": "pure_display", "description": title or desc}
                # pure_display refuses an empty labels list; leave it out.
                if desc and title:
                    intro["labels"] = [desc]
                page.questions.append(intro)
            grel = (grp.get("grelevance") or "").strip()
            if grel and grel != "1":
                pending.append((page, "page", grel, where_g, None))
            if (grp.get("randomization_group") or "").strip():
                result.skip(where_g, "group randomization", grp["randomization_group"])
            for q in sorted(by_group.get(gid, []), key=lambda r: _int(r.get("question_order"))):
                self._question(q, page, pending)
            result.pages.append(page)

        orphan = [q for gid, qs in by_group.items() if gid not in self.groups for q in qs]
        for q in orphan:
            result.skip(f"question {q.get('title')}", "question outside any group")

        for target, kind, expression, where, qid in pending:
            if kind == "conditions":
                continue
            rule = self._relevance(expression, where, "group relevance" if kind == "page" else "relevance")
            if rule is None:
                continue
            if kind == "page":
                target.show_when = and_rules(target.show_when, rule)
            else:
                for scheme in target:
                    scheme["display_logic"] = and_rules(scheme.get("display_logic"), rule)

        self._conditions_pending(pending)
        for tag, what in (("quota", "quotas"), ("assessments", "assessments")):
            rows = _table(root, tag)
            if rows:
                result.skip("survey", what, f"{len(rows)} row(s)")
        for row in _table(root, "defaultvalues"):
            if row.get("language", lang) in ("", lang):
                title = self.sgqa.get(row.get("qid", ""), ("?",))[0]
                result.skip(f"question {title}", "default value", row.get("defaultvalue", ""))
        return result

    # ------------------------------------------------------------------
    # Tables

    def _load(self, root, lang: str) -> None:
        # Groups
        group_rows = _table(root, "groups")
        groups = _pick_language(group_rows, lambda r: r.get("gid"), lang)
        for gid, row in _pick_language(_table(root, "group_l10ns"), lambda r: r.get("gid"), lang).items():
            groups.setdefault(gid, {}).update({k: v for k, v in row.items() if k not in ("id",)})
        self.groups = groups

        # Questions and subquestions (older files keep both in `questions`)
        rows = _table(root, "questions") + _table(root, "subquestions")
        all_q = _pick_language(rows, lambda r: r.get("qid"), lang)
        for qid, row in _pick_language(_table(root, "question_l10ns"), lambda r: r.get("qid"), lang).items():
            if qid in all_q:
                all_q[qid].update({"question": row.get("question", ""), "help": row.get("help", "")})
        self.questions: Dict[str, Dict[str, str]] = {}
        self.subquestions: Dict[str, List[Dict[str, str]]] = {}
        for qid, row in all_q.items():
            parent = (row.get("parent_qid") or "0").strip()
            if parent in ("", "0"):
                self.questions[qid] = row
            else:
                self.subquestions.setdefault(parent, []).append(row)
        for subs in self.subquestions.values():
            subs.sort(key=lambda r: (_int(r.get("scale_id")), _int(r.get("question_order"))))

        # Answers
        answer_rows = _table(root, "answers")
        if any("aid" in r for r in answer_rows):
            texts = _pick_language(_table(root, "answer_l10ns"), lambda r: r.get("aid"), lang)
            for r in answer_rows:
                r.setdefault("answer", (texts.get(r.get("aid")) or {}).get("answer", ""))
        answers = _pick_language(answer_rows, lambda r: (r.get("qid"), r.get("code"), r.get("scale_id", "0")), lang)
        self.answers: Dict[str, List[Dict[str, str]]] = {}
        for r in answers.values():
            self.answers.setdefault(r.get("qid", ""), []).append(r)
        for lst in self.answers.values():
            lst.sort(key=lambda r: (_int(r.get("scale_id")), _int(r.get("sortorder"))))

        # Attributes: language-neutral rows, overridden by the chosen language
        self.attributes: Dict[str, Dict[str, str]] = {}
        for r in _table(root, "question_attributes"):
            rl = r.get("language", "") or ""
            if rl not in ("", lang):
                continue
            attrs = self.attributes.setdefault(r.get("qid", ""), {})
            if rl == lang or r.get("attribute") not in attrs:
                attrs[r.get("attribute", "")] = r.get("value", "")

        # Legacy conditions
        self.conditions: Dict[str, List[Dict[str, str]]] = {}
        for r in _table(root, "conditions"):
            self.conditions.setdefault(r.get("qid", ""), []).append(r)

    # ------------------------------------------------------------------
    # Questions

    def _question(self, q: Dict[str, str], page: SurveyPage, pending: list) -> None:
        qtype = (q.get("type") or "").strip()
        title = (q.get("title") or "").strip() or f"q{q.get('qid')}"
        qid = q.get("qid", "")
        where = f"question {title}"
        attrs = self.attributes.get(qid, {})
        text = strip_html(q.get("question", "")) or title
        help_text = strip_html(q.get("help", ""))
        description = f"{text} ({help_text})" if help_text else text
        subs = self.subquestions.get(qid, [])

        if (attrs.get("hidden") or "").strip() == "1":
            self.blocked[title] = f"{title} is a hidden question"
            self.result.skip(where, "hidden question", "always hidden in LimeSurvey; not imported")
            return
        if qtype in _UNSUPPORTED:
            self.blocked[title] = f"{title} is a {_TYPE_NAMES.get(qtype, qtype)} question"
            for s in subs:
                self.blocked[f"{title}_{s.get('title')}"] = self.blocked[title]
            self.result.skip(where, f"question type '{qtype}' ({_TYPE_NAMES.get(qtype, 'unknown')})", text[:200])
            return

        if _PIPE.search(q.get("question", "") or ""):
            self.result.skip(where, "piped text", text[:200])

        schemes = self._schemes(q, qtype, title, description, subs, attrs, where)
        if not schemes:
            return
        mandatory = (q.get("mandatory") or "").strip().upper()
        for scheme in schemes:
            if mandatory == "Y" and scheme["annotation_type"] != "pure_display":
                scheme["label_requirement"] = {"required": True}
            page.questions.append(scheme)
        if mandatory == "S":
            self.result.skip(where, "soft mandatory", "Potato asks for required answers or not at all")
        if _set(attrs.get("random_order")) and not any("randomize_order" in s for s in schemes):
            self.result.skip(where, "random order", f"type '{qtype}' has no option order to shuffle")
        for key, what in _REPORTED_ATTRIBUTES.items():
            value = (attrs.get(key) or "").strip()
            if value and value != "0":
                self.result.skip(where, what, value[:200])
        if (q.get("preg") or "").strip():
            self.result.skip(where, "validation regex", q["preg"].strip())
        if attrs.get("slider_layout") == "1":
            self.result.warnings.append(f"{where}: shown as a slider in LimeSurvey, imported as number input(s)")
        for s in subs:
            rel = (s.get("relevance") or "").strip()
            if rel and rel != "1":
                self.result.skip(f"{where} / {s.get('title')}", "subquestion relevance", rel)

        relevance = (q.get("relevance") or "").strip()
        if relevance and relevance != "1":
            pending.append((schemes, "question", relevance, where, qid))
        elif self.conditions.get(qid):
            pending.append((schemes, "conditions", None, where, qid))

    def _choice_labels(self, qid: str, scale: str = "0") -> Tuple[List[str], List[str]]:
        rows = [a for a in self.answers.get(qid, []) if (a.get("scale_id") or "0") == scale]
        labels = unique_labels([strip_html(a.get("answer", "")) or a.get("code", "") for a in rows])
        return [a.get("code", "") for a in rows], labels

    def _other(self, q, attrs, labels: List[str], values: Dict[str, str], scheme_extra: dict) -> None:
        if (q.get("other") or "").strip().upper() != "Y":
            return
        other_label = strip_html(attrs.get("other_replace_text", "")) or "Other"
        other_label = unique_labels(labels + [other_label])[-1]
        labels.append(other_label)
        values["-oth-"] = other_label
        scheme_extra["has_free_response"] = {"instruction": "Please specify"}

    def _schemes(self, q, qtype, title, description, subs, attrs, where) -> List[Dict[str, Any]]:
        qid = q.get("qid", "")
        result = self.result
        randomize = _set(attrs.get("random_order"))

        def named(src=title):
            name = self.names.take(src)
            result.name_map[src] = name
            return name

        if qtype in ("L", "!", "O"):
            codes, labels = self._choice_labels(qid)
            values = dict(zip(codes, labels))
            extra: Dict[str, Any] = {}
            self._other(q, attrs, labels, values, extra)
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="single", values=values)
            dropdown = qtype == "!" or (qtype == "L" and attrs.get("use_dropdown") == "1")
            scheme = {"name": name, "annotation_type": "select" if dropdown else "radio",
                      "description": description, "labels": labels}
            if dropdown and extra:
                result.skip(where, "free-text 'Other' on a dropdown",
                            "imported as an 'Other' option without the text box")
            else:
                scheme.update(extra)
            if randomize:
                scheme["randomize_order"] = True
            if qtype == "O":
                result.skip(where, "comment box of a list-with-comment question")
            if not labels:
                result.warnings.append(f"{where}: list question with no answer options")
            return [scheme]
        if qtype == "5":
            labels = [str(i) for i in range(1, 6)]
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="single", values={l: l for l in labels})
            return [{"name": name, "annotation_type": "radio", "description": description,
                     "labels": labels, "horizontal": True}]
        if qtype == "Y":
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="single", values={"Y": "Yes", "N": "No"})
            return [{"name": name, "annotation_type": "radio", "description": description,
                     "labels": ["Yes", "No"], "horizontal": True}]
        if qtype == "G":
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="single", values={"F": "Female", "M": "Male"})
            return [{"name": name, "annotation_type": "radio", "description": description,
                     "labels": ["Female", "Male"], "horizontal": True}]
        if qtype in ("M", "P"):
            codes = [s.get("title", "") for s in subs]
            labels = unique_labels([strip_html(s.get("question", "")) or s.get("title", "") for s in subs])
            values = dict(zip(codes, labels))
            extra = {}
            self._other(q, attrs, labels, values, extra)
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="multi", values=values)
            for code, label in values.items():
                key = "other" if code == "-oth-" else code
                self.vars[f"{title}_{key}"] = VarInfo(schema=name, kind="multi", choice=label)
                self.blocked[f"{title}_{key}comment"] = f"the comment on {title}_{key}"
            scheme = {"name": name, "annotation_type": "multiselect", "description": description,
                      "labels": labels}
            scheme.update(extra)
            if randomize:
                scheme["randomize_order"] = True
            if qtype == "P":
                result.skip(where, "per-option comment boxes of a multiple-choice-with-comments question")
            return [scheme]
        if qtype in ("A", "B", "C", "E", "F", "H"):
            rows = [s for s in subs if _int(s.get("scale_id")) == 0]
            options = unique_labels([strip_html(s.get("question", "")) or s.get("title", "") for s in rows])
            if qtype in _FIXED_SCALES:
                columns = list(_FIXED_SCALES[qtype])
            else:
                _codes, columns = self._choice_labels(qid)
            name = named()
            self.blocked[title] = f"{title} is an array; logic on a single array row is not translated"
            for s in rows:
                self.blocked[f"{title}_{s.get('title')}"] = (f"{title}_{s.get('title')} is one row of the array "
                                                            f"{title}; logic on a single row is not translated")
            if qtype == "H":
                result.warnings.append(f"{where}: array by column imported as rows (one per subquestion)")
            if not options or not columns:
                result.skip(where, "array without rows or columns")
                self.names._used.discard(name)
                return []
            scheme = {"name": name, "annotation_type": "multirate", "description": description,
                      "options": options, "labels": columns}
            if randomize:
                scheme["randomize_order"] = True
            return [scheme]
        if qtype in ("S", "T", "U", "D"):
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="text")
            scheme = {"name": name, "annotation_type": "text", "description": description}
            if qtype in ("T", "U"):
                scheme["textarea"] = {"on": True, "rows": 4 if qtype == "T" else 8}
            if qtype == "D":
                result.skip(where, "date question", "imported as a text box; Potato has no date input")
            return [scheme]
        if qtype == "N":
            name = named()
            self.vars[title] = VarInfo(schema=name, kind="number")
            return [self._number(name, description, attrs)]
        if qtype in ("K", "Q"):
            out = []
            self.blocked[title] = f"{title} has several answers; refer to one subquestion ({title}_<code>)"
            for s in subs:
                code = s.get("title", "")
                label = strip_html(s.get("question", "")) or code
                name = named(f"{title}_{code}")
                desc = f"{description}: {label}"
                if qtype == "K":
                    self.vars[f"{title}_{code}"] = VarInfo(schema=name, kind="number")
                    out.append(self._number(name, desc, attrs))
                else:
                    self.vars[f"{title}_{code}"] = VarInfo(schema=name, kind="text")
                    out.append({"name": name, "annotation_type": "text", "description": desc})
            if not out:
                result.skip(where, "multiple input question without subquestions")
            return out
        if qtype == "R":
            _codes, labels = self._choice_labels(qid)
            name = named()
            self.blocked[title] = f"{title} is a ranking; logic on ranks is not translated"
            for i in range(1, len(labels) + 1):
                self.blocked[f"{title}_{i}"] = self.blocked[title]
            return [{"name": name, "annotation_type": "ranking", "description": description,
                     "labels": labels}]
        if qtype == "X":
            name = named()
            self.blocked[title] = f"{title} is a text display, not a question"
            return [{"name": name, "annotation_type": "pure_display", "description": description}]
        self.blocked[title] = f"{title} has the unknown type '{qtype}'"
        result.skip(where, f"question type '{qtype}'", description[:200])
        return []

    def _number(self, name: str, description: str, attrs: Dict[str, str]) -> Dict[str, Any]:
        scheme: Dict[str, Any] = {"name": name, "annotation_type": "number", "description": description}
        lo, hi = _num(attrs.get("min_num_value_n")), _num(attrs.get("max_num_value_n"))
        if lo is not None:
            scheme["min"] = lo
        if hi is not None:
            scheme["max"] = hi
        if lo is not None and hi is not None and lo > hi:
            scheme.pop("min"), scheme.pop("max")
            self.result.warnings.append(f"{name}: minimum above maximum in the source; bounds dropped")
        if attrs.get("num_value_int_only") == "1":
            scheme["step"] = 1
        return scheme

    # ------------------------------------------------------------------
    # ExpressionScript

    def _rewrite_sgqa(self, expression: str) -> str:
        """SGQA names (123456X12X34SQ001) as question codes, outside strings."""
        def repl(m):
            sid, gid, qid, suffix = m.groups()
            if qid not in self.sgqa:
                return f"unknown_sgqa_{sid}X{gid}X{qid}{suffix}"
            title = self.sgqa[qid][0]
            return f"{title}_{suffix}" if suffix else title
        out, last = [], 0
        for m in _STRING.finditer(expression):
            out.append(_SGQA.sub(repl, expression[last:m.start()]))
            out.append(m.group(0))
            last = m.end()
        out.append(_SGQA.sub(repl, expression[last:]))
        return "".join(out)

    def _resolve(self, ref: str) -> VarInfo:
        ref = ref.strip()
        base, dot, suffix = ref.partition(".")
        if dot and suffix.lower() not in ("naok", "value", "code"):
            raise Untranslatable(f"{ref}: .{suffix} has no Potato equivalent")
        if base in self.vars:
            return self.vars[base]
        if base in self.blocked:
            raise Untranslatable(self.blocked[base])
        if base.startswith("unknown_sgqa_"):
            raise Untranslatable(f"SGQA {base[13:]} names no question in this survey")
        raise Untranslatable(f"unknown question {base!r}")

    def _call(self, name: str, args: list, resolve, cmp) -> Optional[Dict[str, Any]]:
        low = name.lower()
        if low == "is_empty" and cmp is None and len(args) == 1 and args[0][0] == "var":
            info = resolve(args[0][1])
            if info.choice is not None:
                return {"schema": info.schema, "operator": "not_contains", "value": info.choice}
            return {"schema": info.schema, "operator": "empty"}
        if low == "count" and cmp is not None and args and all(a[0] == "var" for a in args):
            op, right = cmp
            if right[0] != "lit":
                return None
            infos = [resolve(a[1]) for a in args]
            schemas = {i.schema for i in infos}
            if len(schemas) != 1 or any(i.choice is None for i in infos):
                raise Untranslatable("count() over something other than the options of "
                                     "one multiple-choice question")
            whole = next(v for v in self.vars.values() if v.schema in schemas and v.choice is None)
            if {i.choice for i in infos} != set(whole.values.values()):
                raise Untranslatable("count() over some, not all, options of a question")
            return compare(VarInfo(schema=whole.schema, kind="count"), op, right[1])
        return None

    def _relevance(self, expression: str, where: str, what: str):
        try:
            tree = parse(self._rewrite_sgqa(expression), LIMESURVEY)
            if tree == ("lit", True) or tree == ("lit", 1):
                return None
            return to_rule(tree, self._resolve, self._call)
        except Untranslatable as e:
            self.result.skip(where, what, f"{expression} ({e})")
            return None

    # ------------------------------------------------------------------
    # Legacy conditions

    _METHODS = {"==": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}

    def _conditions_pending(self, pending: list) -> None:
        for target, kind, _expr, where, qid in pending:
            if kind != "conditions":
                continue
            try:
                rule = self._conditions_rule(self.conditions[qid])
            except Untranslatable as e:
                summary = "; ".join(f"{c.get('cfieldname')} {c.get('method')} {c.get('value')!r}"
                                    for c in self.conditions[qid])
                self.result.skip(where, "conditions", f"{summary} ({e})")
                continue
            for scheme in target:
                scheme["display_logic"] = and_rules(scheme.get("display_logic"), rule)

    def _condition_leaf(self, c: Dict[str, str]) -> Dict[str, Any]:
        field_name = (c.get("cfieldname") or "").strip()
        method = (c.get("method") or "==").strip()
        value = c.get("value", "")
        if value.startswith("@") and value.endswith("@"):
            raise Untranslatable("a condition comparing two questions")
        if field_name.startswith("{"):
            raise Untranslatable(f"a condition on {field_name}")
        checkbox = field_name.startswith("+")
        ref = self._rewrite_sgqa(field_name.lstrip("+"))
        if checkbox:
            # A multiple-choice option: the value names the subquestion
            info = self._resolve(f"{ref}_{value}")
            return compare(info, "=" if method == "==" else "!=", "1")
        info = self._resolve(ref)
        if method == "RX":
            pattern = value.strip()
            if len(pattern) > 1 and pattern[0] == "/" and pattern.rfind("/") > 0:
                pattern = pattern[1:pattern.rfind("/")]
            return {"schema": info.schema, "operator": "matches", "value": pattern}
        if method not in self._METHODS:
            raise Untranslatable(f"condition method {method!r}")
        if info.choice is not None and value.strip().upper() == "Y":
            value = "1"
        num = _num(value) if method in ("<", "<=", ">", ">=") else None
        return compare(info, self._METHODS[method], num if num is not None else value)

    def _conditions_rule(self, conditions: List[Dict[str, str]]) -> Dict[str, Any]:
        scenarios: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for c in sorted(conditions, key=lambda r: _int(r.get("cid"))):
            fields = scenarios.setdefault(c.get("scenario", "1") or "1", {})
            fields.setdefault(c.get("cfieldname", "").lstrip("+"), []).append(self._condition_leaf(c))

        def group(kind, items):
            return items[0] if len(items) == 1 else {kind: items}

        per_scenario = [group("all", [group("any", leaves) for leaves in fields.values()])
                        for _s, fields in sorted(scenarios.items(), key=lambda kv: _int(kv[0]))]
        top = group("any", per_scenario)
        for kind, logic in (("all", "all"), ("any", "any")):
            if isinstance(top, dict) and set(top) == {kind}:
                return {"show_when": top[kind], "logic": logic}
        return {"show_when": [top], "logic": "all"}

