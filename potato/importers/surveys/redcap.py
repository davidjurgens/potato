"""
REDCap data dictionaries (.csv) into Potato survey pages.

Reads the data dictionary that REDCap's Designer downloads ("Variable / Field
Name", "Form Name", "Field Type", ...) and the API's snake_case variant
(``field_name``, ``form_name``, ``field_type``, ...). Each instrument (Form
Name, in order of first appearance) becomes one survey page.

Mapped:

* ``text`` (``integer`` / ``number`` / ``number_Ndp`` validation becomes a
  ``number`` question with the dictionary's min/max), ``notes``,
  ``dropdown``, ``radio``, ``checkbox``, ``yesno``, ``truefalse``,
  ``slider``, ``descriptive``.
* Section headers, as a display-only heading before the field.
* Field embedding (``{field}`` in another field's label or choice): the
  placeholder is removed and the embedded field asked on its own.
* ``Required Field?``, ``Custom Alignment`` LH/RH (horizontal radios),
  ``Question Number``, ``Field Note`` (appended to the wording),
  ``@PLACEHOLDER`` on text fields.
* Matrix groups: a run of radio rows with one matrix name and the same
  choices becomes one ``multirate`` question, unless a row has its own
  branching logic or another field's logic tests a row. Then the rows stay
  separate horizontal radio questions so the logic can still be translated.
* Branching logic, through the shared expression translator: choice codes
  become the choice labels Potato stores, ``[cb(3)] = '1'`` becomes
  "contains", and a numeric comparison on a choice field with numeric codes
  becomes "one of the choices whose code satisfies it".

Reported, not mapped: ``calc``, ``file``, ``sql`` fields; validation types
Potato has no check for (dates, times, email, phone, ...); slider labels;
action tags other than @PLACEHOLDER; fields hidden from survey participants
(@HIDDEN, @HIDDEN-SURVEY; not imported); the Identifier? flag; matrix
ranking; piped values in labels; and logic that uses functions, smart
variables, ``[event][field]`` references or ``[form_complete]`` status.

The first field of a dictionary is the record ID, which REDCap never shows
to survey participants; it is left out.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, and_rules,
    strip_html, unique_labels)
from .expr import REDCAP, VarInfo, parse, to_rule

#: header spellings (Designer download and API) -> canonical key
_COLUMNS = {
    "variable / field name": "field_name", "field_name": "field_name",
    "form name": "form_name", "form_name": "form_name",
    "section header": "section_header", "section_header": "section_header",
    "field type": "field_type", "field_type": "field_type",
    "field label": "field_label", "field_label": "field_label",
    "choices, calculations, or slider labels": "choices",
    "select_choices_or_calculations": "choices",
    "field note": "field_note", "field_note": "field_note",
    "text validation type or show slider number": "validation",
    "text_validation_type_or_show_slider_number": "validation",
    "text validation min": "validation_min", "text_validation_min": "validation_min",
    "text validation max": "validation_max", "text_validation_max": "validation_max",
    "identifier?": "identifier", "identifier": "identifier",
    "branching logic (show field only if...)": "branching_logic",
    "branching_logic": "branching_logic",
    "required field?": "required", "required_field": "required",
    "custom alignment": "alignment", "custom_alignment": "alignment",
    "question number (surveys only)": "question_number", "question_number": "question_number",
    "matrix group name": "matrix_group", "matrix_group_name": "matrix_group",
    "matrix ranking?": "matrix_ranking", "matrix_ranking": "matrix_ranking",
    "field annotation": "field_annotation", "field_annotation": "field_annotation",
}

_NUMBER_VALIDATION = re.compile(r"^number(?:_(\d)dp)?(?:_comma_decimal)?$")
_DATE_HINTS = {
    "date_ymd": "YYYY-MM-DD", "date_mdy": "MM-DD-YYYY", "date_dmy": "DD-MM-YYYY",
    "datetime_ymd": "YYYY-MM-DD HH:MM", "datetime_mdy": "MM-DD-YYYY HH:MM",
    "datetime_dmy": "DD-MM-YYYY HH:MM",
    "datetime_seconds_ymd": "YYYY-MM-DD HH:MM:SS", "datetime_seconds_mdy": "MM-DD-YYYY HH:MM:SS",
    "datetime_seconds_dmy": "DD-MM-YYYY HH:MM:SS",
    "time": "HH:MM", "time_hh_mm_ss": "HH:MM:SS", "time_mm_ss": "MM:SS",
}
#: a reference to a field inside branching logic or a label (for piping)
_REF = re.compile(r"\[([A-Za-z][A-Za-z0-9_]*)(?:\([^)\]]*\))?(?::[A-Za-z0-9_:-]+)?\]")
_EMBED = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)(?::icons)?\}")
_CHECKBOX_REF = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\(([^()]+)\)$")
_TAG = re.compile(r"@([A-Z][A-Z0-9_-]*)")
_PLACEHOLDER_TAG = re.compile(r"@PLACEHOLDER\s*=\s*(['\"])(.*?)\1", re.S)
_HIDING_TAGS = {"HIDDEN", "HIDDEN-SURVEY"}
_ORDER_OPS = (">", ">=", "<", "<=")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Dictionaries edited in Excel on Windows are often cp1252
        return raw.decode("cp1252", errors="replace")


def _canonical_header(header: List[str]) -> List[str]:
    return [_COLUMNS.get(h.strip().lstrip("﻿").lower(), h.strip()) for h in header]


def _looks_like_header(header: List[str]) -> bool:
    keys = set(_canonical_header(header))
    return {"field_name", "field_type"} <= keys and ("form_name" in keys or "field_label" in keys)


def parse_choices(raw: str) -> List[Tuple[str, str]]:
    """``"1, Yes | 2, No"`` -> [("1", "Yes"), ("2", "No")]. The label may itself
    contain commas: only the first comma separates code from label."""
    out = []
    for part in str(raw or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            code, label = part.split(",", 1)
        else:
            code, label = part, part
        out.append((code.strip(), strip_html(label) or code.strip()))
    return out


def _number(text: Any) -> Optional[float]:
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() else v


def _humanize(name: str) -> str:
    s = re.sub(r"[_\s]+", " ", str(name)).strip()
    return s[:1].upper() + s[1:]


class REDCapImporter:
    format_name = "redcap"
    description = "REDCap data dictionary (.csv, Designer or API header)"
    file_extensions = [".csv"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != ".csv":
            return False
        with path.open("rb") as f:
            head = f.read(8192)
        text = head.decode("utf-8-sig", errors="replace")
        try:
            header = next(csv.reader(io.StringIO(text)))
        except (StopIteration, csv.Error):
            return False
        return _looks_like_header(header)

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        return self.parse_text(_read_text(Path(path)), options or {})

    # ------------------------------------------------------------------

    def parse_text(self, text: str, options: Optional[dict] = None) -> SurveyImportResult:
        reader = csv.reader(io.StringIO(text.lstrip("﻿")))
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("empty file: not a REDCap data dictionary")
        if not _looks_like_header(header):
            raise ValueError("not a REDCap data dictionary: expected 'Variable / Field Name' "
                             "and 'Field Type' columns")
        keys = _canonical_header(header)
        rows = []
        for raw in reader:
            if not any(c.strip() for c in raw):
                continue
            row = {k: (raw[i].strip() if i < len(raw) else "") for i, k in enumerate(keys)}
            if row.get("field_name"):
                rows.append(row)
        return self.parse_rows(rows)

    def parse_rows(self, rows: List[Dict[str, str]]) -> SurveyImportResult:
        result = SurveyImportResult(source_format="REDCap")
        self.result = result
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})
        self.vars: Dict[str, VarInfo] = {}
        self.types: Dict[str, str] = {}
        #: fields that exist in the dictionary but are not questions in Potato
        self.omitted: Dict[str, str] = {}
        self.forms: List[str] = []
        pending: List[Tuple[Dict[str, Any], str, str]] = []   # (scheme, logic, where)

        if not rows:
            raise ValueError("the data dictionary has no fields")
        for r in rows:
            self.types[r["field_name"]] = r.get("field_type", "").lower()
            if r.get("form_name") and r["form_name"] not in self.forms:
                self.forms.append(r["form_name"])

        # Fields some branching logic tests: a matrix of these must stay
        # separate questions, or the logic could not be translated.
        referenced = set()
        for r in rows:
            for m in _REF.finditer(r.get("branching_logic", "")):
                referenced.add(m.group(1))

        # Field embedding: "{other_text}" inside another field's label or a
        # choice places that field inline. Potato asks it as its own question.
        for r in rows:
            embedded = []
            for key in ("field_label", "choices", "section_header"):
                def drop(m, embedded=embedded):
                    if m.group(1) in self.types:
                        embedded.append(m.group(1))
                        return ""
                    return m.group(0)
                r[key] = _EMBED.sub(drop, r.get(key, ""))
            if embedded:
                result.skip(f"'{r['field_name']}'", "embedded fields (asked as separate questions)",
                            ", ".join(embedded))

        record_id = rows[0]["field_name"]
        self.omitted[record_id] = "the record ID, which REDCap assigns and never shows to participants"
        result.warnings.append(f"'{record_id}': the record ID field was left out; "
                               "Potato identifies participants itself")

        by_form: Dict[str, List[Dict[str, str]]] = {f: [] for f in self.forms}
        for r in rows[1:]:
            by_form.setdefault(r.get("form_name") or "form", []).append(r)

        identifiers = [r["field_name"] for r in rows
                       if r.get("identifier", "").lower() == "y"]
        plain_notes = []

        for form, frows in by_form.items():
            page = SurveyPage(name=self.page_names.take(form, "form"), title=_humanize(form))
            i = 0
            while i < len(frows):
                r = frows[i]
                group = r.get("matrix_group", "")
                if group:
                    j = i
                    while j < len(frows) and frows[j].get("matrix_group", "") == group:
                        j += 1
                    self._matrix(frows[i:j], page, referenced, pending)
                    i = j
                    continue
                self._field(r, page, pending)
                ann = r.get("field_annotation", "")
                if ann and not _TAG.search(ann):
                    plain_notes.append(r["field_name"])
                i += 1
            if not page.questions:
                result.warnings.append(f"form '{form}' has no fields Potato can show; no page written")
                continue
            result.pages.append(page)

        # Logic last: a field may test one asked on a later form.
        for scheme, logic, where in pending:
            rule = self._rule(logic, where)
            if rule is not None:
                scheme["display_logic"] = and_rules(scheme.get("display_logic"), rule)

        if identifiers:
            result.skip("dictionary", "Identifier? flag (identifying data, removed by "
                        "REDCap's de-identified export)", ", ".join(identifiers))
        if plain_notes:
            result.warnings.append("Field Annotation notes (not action tags) were not imported: "
                                   + ", ".join(plain_notes))
        return result

    # ------------------------------------------------------------------
    # Logic

    def _rule(self, logic: str, where: str):
        try:
            tree = self._rewrite(parse(logic, REDCAP))
            return to_rule(tree, self._resolve)
        except Untranslatable as e:
            self.result.skip(where, "branching logic", f"{logic} ({e})")
            return None

    def _resolve(self, ref: str) -> VarInfo:
        if "@" in ref:
            field, event = ref.split("@", 1)
            raise Untranslatable(f"[{event}][{field}] names a longitudinal event or a "
                                 "repeating instance")
        if ":" in ref:
            raise Untranslatable(f"[{ref}] uses a smart-variable modifier")
        m = _CHECKBOX_REF.match(ref)
        if m:
            field, code = m.group(1), m.group(2).strip()
            info = self._field_info(field)
            if self.types.get(field) != "checkbox":
                raise Untranslatable(f"[{ref}] names a choice of a field that is not a checkbox")
            if code not in info.values:
                raise Untranslatable(f"{code!r} is not a choice of {field}")
            return VarInfo(schema=info.schema, kind="multi", values=info.values,
                           choice=info.values[code])
        info = self._field_info(ref)
        if self.types.get(ref) == "checkbox":
            raise Untranslatable(f"checkbox [{ref}] tested without a choice code ([{ref}(1)])")
        return info

    def _field_info(self, field: str) -> VarInfo:
        if field in self.vars:
            return self.vars[field]
        if field in self.omitted:
            raise Untranslatable(f"[{field}] is not a Potato question ({self.omitted[field]})")
        if field.endswith("_complete") and field[:-len("_complete")] in self.forms:
            raise Untranslatable(f"[{field}] is a form's completion status")
        if field in self.types:
            raise Untranslatable(f"[{field}] was not imported")
        raise Untranslatable(f"unknown field or smart variable [{field}]")

    def _rewrite(self, node):
        """Numeric comparisons the shared translator cannot express directly.

        ``[pain] >= 3`` on a radio coded 0..5 with word labels becomes "one of
        the choices coded 3, 4 or 5"; a number field compared with '5' gets
        the number 5.
        """
        kind = node[0]
        if kind in ("and", "or"):
            return (kind, [self._rewrite(n) for n in node[1]])
        if kind == "not":
            return ("not", self._rewrite(node[1]))
        if kind == "call":
            raise Untranslatable(f"function {node[1]}()")
        if kind == "arith":
            raise Untranslatable(f"arithmetic ({node[1]})")
        if kind != "cmp":
            return node
        op, left, right = node[1], node[2], node[3]
        for side in (left, right):
            if side[0] in ("call", "arith"):
                self._rewrite(side)
        if right[0] == "var" and left[0] == "lit":
            flip = {">": "<", "<": ">", ">=": "<=", "<=": ">=", "=": "=", "!=": "!="}
            if op in flip:
                op, left, right = flip[op], right, left
        if left[0] != "var" or right[0] != "lit":
            return (kind, op, left, right)
        info = self._resolve(left[1])
        value = right[1]
        if info.kind == "number" and isinstance(value, str) and _number(value) is not None:
            return ("cmp", op, left, ("lit", _number(value)))
        if op in _ORDER_OPS and info.values and info.choice is None:
            target = _number(value)
            if target is None:
                raise Untranslatable(f"{op} with a non-number {value!r}")
            codes = [c for c in info.values if _number(c) is not None]
            if len(codes) != len(info.values):
                raise Untranslatable(f"numeric {op} on non-numeric choice codes of {info.schema}")
            test = {">": lambda c: c > target, ">=": lambda c: c >= target,
                    "<": lambda c: c < target, "<=": lambda c: c <= target}[op]
            keep = [c for c in codes if test(_number(c))]
            if not keep:
                raise Untranslatable(f"no choice of {info.schema} is {op} {value}")
            return ("cmp", "anyof", left, ("list", keep))
        return (kind, op, left, right)

    # ------------------------------------------------------------------
    # Fields

    def _wording(self, r: Dict[str, str], with_note: bool = True) -> str:
        label = strip_html(r.get("field_label", "")) or r["field_name"]
        qnum = r.get("question_number", "").strip()
        if qnum:
            label = f"{qnum} {label}"
        note = strip_html(r.get("field_note", ""))
        if with_note and note:
            label = f"{label} ({note})"
        return label

    def _where(self, page: SurveyPage, field: str) -> str:
        return f"form '{page.name}' / '{field}'"

    def _section(self, r: Dict[str, str], page: SurveyPage) -> None:
        header = strip_html(r.get("section_header", ""))
        if header:
            page.questions.append({"name": self.names.take(f"{r['field_name']}_section", "section"),
                                   "annotation_type": "pure_display", "description": header})

    def _common(self, r: Dict[str, str], scheme: Dict[str, Any], page: SurveyPage,
                pending: list) -> None:
        where = self._where(page, r["field_name"])
        if r.get("required", "").lower() in ("y", "yes", "1") and scheme["annotation_type"] != "pure_display":
            scheme["label_requirement"] = {"required": True}
        if r.get("branching_logic"):
            pending.append((scheme, r["branching_logic"], where))
        piped = _REF.search(r.get("field_label", ""))
        if scheme["annotation_type"] in ("radio", "select", "multiselect"):
            piped = piped or _REF.search(r.get("choices", ""))
        if piped:
            self.result.skip(where, "piped value in the wording", strip_html(r.get("field_label", ""))[:200])
        ann = r.get("field_annotation", "")
        tags = [t for t in _TAG.findall(ann) if t != "PLACEHOLDER" or "placeholder" not in scheme]
        if tags:
            self.result.skip(where, "action tags", ann.strip()[:200])
        self.result.name_map[r["field_name"]] = scheme["name"]

    def _field(self, r: Dict[str, str], page: SurveyPage, pending: list) -> None:
        field = r["field_name"]
        ftype = r.get("field_type", "").lower()
        where = self._where(page, field)
        tags = set(_TAG.findall(r.get("field_annotation", "")))
        if tags & _HIDING_TAGS:
            self.omitted[field] = "hidden from survey participants by " + \
                ", ".join(f"@{t}" for t in sorted(tags & _HIDING_TAGS))
            self.result.skip(where, "field hidden from participants (not imported)",
                             r.get("field_annotation", "").strip()[:200])
            return
        if ftype in ("calc", "file", "sql"):
            what = {"calc": "calculated field", "file": "file upload / signature field",
                    "sql": "SQL (dynamic query) field"}[ftype]
            self.omitted[field] = what
            self.result.skip(where, what, r.get("choices", "")[:200])
            self._section(r, page)
            return
        scheme = self._scheme(r, ftype, where)
        if scheme is None:
            self.omitted[field] = f"field type '{ftype}'"
            self.result.skip(where, f"field type '{ftype}'", strip_html(r.get("field_label", ""))[:200])
            return
        self._section(r, page)
        page.questions.append(scheme)
        self._common(r, scheme, page, pending)

    def _choice_scheme(self, r, atype: str, choices: List[Tuple[str, str]], name: str,
                       horizontal: bool = False) -> Dict[str, Any]:
        labels = unique_labels([lab for _c, lab in choices])
        self.vars[r["field_name"]] = VarInfo(
            schema=name, kind="multi" if atype == "multiselect" else "single",
            values={c: lab for (c, _l), lab in zip(choices, labels)})
        scheme = {"name": name, "annotation_type": atype, "description": self._wording(r),
                  "labels": labels}
        if atype == "radio" and (horizontal or r.get("alignment", "").upper() in ("LH", "RH")):
            scheme["horizontal"] = True
        return scheme

    def _scheme(self, r: Dict[str, str], ftype: str, where: str,
                horizontal: bool = False) -> Optional[Dict[str, Any]]:
        field = r["field_name"]
        if ftype not in ("text", "notes", "dropdown", "radio", "checkbox", "yesno",
                         "truefalse", "slider", "descriptive"):
            return None
        name = self.names.take(field)
        if ftype in ("dropdown", "radio", "checkbox"):
            choices = parse_choices(r.get("choices", ""))
            if not choices:
                self.result.skip(where, f"{ftype} without choices")
                choices = [("1", "(no choices)")]
            atype = {"dropdown": "select", "radio": "radio", "checkbox": "multiselect"}[ftype]
            return self._choice_scheme(r, atype, choices, name, horizontal)
        if ftype in ("yesno", "truefalse"):
            choices = [("1", "Yes"), ("0", "No")] if ftype == "yesno" else [("1", "True"), ("0", "False")]
            return self._choice_scheme(r, "radio", choices, name, horizontal)
        if ftype == "descriptive":
            return {"name": name, "annotation_type": "pure_display", "description": self._wording(r)}
        if ftype == "notes":
            self.vars[field] = VarInfo(schema=name, kind="text")
            scheme = {"name": name, "annotation_type": "text", "description": self._wording(r),
                      "textarea": {"on": True, "rows": 4}}
            self._placeholder(r, scheme)
            return scheme
        if ftype == "slider":
            return self._slider(r, name, where)
        return self._text(r, name, where)

    def _placeholder(self, r: Dict[str, str], scheme: Dict[str, Any]) -> None:
        m = _PLACEHOLDER_TAG.search(r.get("field_annotation", ""))
        if m:
            scheme["placeholder"] = strip_html(m.group(2))

    def _text(self, r: Dict[str, str], name: str, where: str) -> Dict[str, Any]:
        field = r["field_name"]
        vtype = r.get("validation", "").strip().lower()
        lo, hi = r.get("validation_min", ""), r.get("validation_max", "")
        number = _NUMBER_VALIDATION.match(vtype)
        if vtype == "integer" or number:
            self.vars[field] = VarInfo(schema=name, kind="number")
            scheme = {"name": name, "annotation_type": "number", "description": self._wording(r)}
            if vtype == "integer":
                scheme["step"] = 1
            elif number.group(1):
                scheme["step"] = 10 ** -int(number.group(1))
            if vtype.endswith("comma_decimal"):
                self.result.warnings.append(f"{where}: comma decimals ({vtype}) are entered with a point")
            for key, raw in (("min", lo), ("max", hi)):
                if not raw:
                    continue
                value = _number(raw)
                if value is None:
                    self.result.skip(where, f"validation {key}", raw)
                else:
                    scheme[key] = value
            return scheme
        self.vars[field] = VarInfo(schema=name, kind="text")
        scheme = {"name": name, "annotation_type": "text", "description": self._wording(r)}
        self._placeholder(r, scheme)
        if vtype:
            if vtype in _DATE_HINTS and "placeholder" not in scheme:
                scheme["placeholder"] = _DATE_HINTS[vtype]
            bounds = ", ".join(b for b in (f"min {lo}" if lo else "", f"max {hi}" if hi else "") if b)
            self.result.skip(where, f"text validation '{vtype}' (imported as free text)", bounds)
        return scheme

    def _slider(self, r: Dict[str, str], name: str, where: str) -> Dict[str, Any]:
        field = r["field_name"]
        lo = _number(r.get("validation_min", "")) if r.get("validation_min") else 0
        hi = _number(r.get("validation_max", "")) if r.get("validation_max") else 100
        if lo is None or hi is None or lo >= hi:
            self.result.skip(where, "slider range", f"{r.get('validation_min')}..{r.get('validation_max')}")
            lo, hi = 0, 100
        self.vars[field] = VarInfo(schema=name, kind="number")
        labels = [strip_html(s) for s in r.get("choices", "").split("|") if s.strip()]
        if labels:
            # `labels` on a Potato slider turns it into radio buttons
            self.result.skip(where, "slider labels", " | ".join(labels))
        self.result.warnings.append(f"{where}: the slider starts at its midpoint; REDCap's "
                                    "starts unset")
        mid = lo + (hi - lo) // 2 if isinstance(lo, int) and isinstance(hi, int) else lo + (hi - lo) / 2
        return {"name": name, "annotation_type": "slider", "description": self._wording(r),
                "min_value": lo, "max_value": hi,
                "starting_value": int(mid) if float(mid).is_integer() else mid, "step": 1}

    def _matrix(self, rows: List[Dict[str, str]], page: SurveyPage, referenced: set,
                pending: list) -> None:
        group = rows[0]["matrix_group"]
        where = f"form '{page.name}' / matrix '{group}'"
        types = {r.get("field_type", "").lower() for r in rows}
        same_choices = len({r.get("choices", "").replace(" ", "") for r in rows}) == 1
        tested = [r["field_name"] for r in rows if r["field_name"] in referenced]
        with_logic = [r["field_name"] for r in rows if r.get("branching_logic")]
        hidden = [r["field_name"] for r in rows
                  if set(_TAG.findall(r.get("field_annotation", ""))) & _HIDING_TAGS]
        if any(r.get("matrix_ranking", "").lower() == "y" for r in rows):
            self.result.skip(where, "matrix ranking (each choice usable once)")
        as_grid = (types == {"radio"} and same_choices and not tested and not with_logic
                   and not hidden and len(rows) > 1)
        if not as_grid:
            if types == {"radio"} and same_choices and len(rows) > 1:
                why = ("branching logic tests " + ", ".join(tested) if tested else
                       "rows have their own branching logic" if with_logic else
                       "some rows are hidden")
                self.result.warnings.append(f"{where}: kept as separate questions ({why})")
            for r in rows:
                if r.get("field_type", "").lower() == "radio":
                    r = dict(r, alignment=r.get("alignment") or "LH")
                self._field(r, page, pending)
            return
        first = rows[0]
        choices = parse_choices(first.get("choices", ""))
        header = strip_html(first.get("section_header", ""))
        name = self.names.take(group, "matrix")
        scheme = {"name": name, "annotation_type": "multirate",
                  "description": header or _humanize(group),
                  "options": unique_labels([self._wording(r, with_note=False) for r in rows]),
                  "labels": unique_labels([lab for _c, lab in choices])}
        required = [r.get("required", "").lower() in ("y", "yes", "1") for r in rows]
        if all(required):
            scheme["label_requirement"] = {"required": True}
        elif any(required):
            self.result.skip(where, "required on some rows only (the matrix is optional)")
        page.questions.append(scheme)
        for r in rows:
            self.omitted[r["field_name"]] = f"a row of matrix '{name}'"
            self.result.name_map[r["field_name"]] = f"{name} / {self._wording(r, with_note=False)}"
            ann = r.get("field_annotation", "")
            if _TAG.search(ann):
                self.result.skip(self._where(page, r["field_name"]), "action tags", ann.strip()[:200])
            if _REF.search(r.get("field_label", "")):
                self.result.skip(self._where(page, r["field_name"]), "piped value in the wording",
                                 strip_html(r.get("field_label", ""))[:200])
        if any(r.get("field_note") for r in rows):
            self.result.warnings.append(f"{where}: field notes on matrix rows were not imported")
