"""
Survey and questionnaire importers: Qualtrics, SurveyJS, LimeSurvey,
XLSForm, REDCap, and the other formats in this package.

An importer reads a survey exported from another tool and returns a
:class:`SurveyImportResult`: survey pages, each a list of Potato question
schemes in the phase-page JSON format, with the source's show/hide logic
translated into the display_logic grammar (``show_when`` with nested
``all`` / ``any`` / ``not`` groups). The writer turns it into survey files
and phase entries.

Nothing is dropped silently. Every construct an importer cannot express in
Potato (a calculated field, piped text, a quota, a validation regex Potato
has no equivalent for, a logic expression with a function call) goes into
``untranslated`` with where it was and why, and the writer puts that list
in IMPORT_REPORT.md next to the generated files.

Each importer provides ``format_name``, ``description``, ``file_extensions``,
``detect_path(path) -> bool`` and ``parse_path(path, options) ->
SurveyImportResult``, the same protocol as ``importers/projects``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Untranslated:
    where: str           # e.g. "QID12", "page 3 / question 'age'"
    what: str            # e.g. "display logic", "question type Matrix/TE"
    detail: str = ""     # the source text, or why it could not be mapped

    def line(self) -> str:
        tail = f": {self.detail}" if self.detail else ""
        return f"{self.where}: {self.what}{tail}"


@dataclass
class SurveyPage:
    name: str
    title: str = ""
    questions: List[Dict[str, Any]] = field(default_factory=list)
    #: display_logic-style rule for the whole page: {"show_when": [...], "logic": ...}
    show_when: Optional[Dict[str, Any]] = None
    #: {"show_when": [...], "logic": ..., "message": ...}: end the study here
    exit_when: Optional[Dict[str, Any]] = None
    randomize_questions: Any = None     # True or {"pin_first": n, "pin_last": n}


@dataclass
class SurveyImportResult:
    source_format: str
    title: str = ""
    pages: List[SurveyPage] = field(default_factory=list)
    #: phases.counterbalance entries: [{"pages": [...], "method": "random"}]
    counterbalance: List[Dict[str, Any]] = field(default_factory=list)
    #: top-level `conditions` block (between-subjects factors), if any
    conditions: Optional[Dict[str, Any]] = None
    untranslated: List[Untranslated] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: source question id -> Potato question name, for the report
    name_map: Dict[str, str] = field(default_factory=dict)

    def skip(self, where: str, what: str, detail: str = "") -> None:
        self.untranslated.append(Untranslated(where, what, detail))

    def num_questions(self) -> int:
        return sum(len(p.questions) for p in self.pages)

    def all_questions(self):
        for page in self.pages:
            yield from page.questions


class Untranslatable(ValueError):
    """A logic expression or construct with no Potato equivalent."""


_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


class NameAllocator:
    """Question names unique across the whole study.

    Phase answers from every page are read together by page rules and by
    the export, so two pages cannot both have a question called ``age``.
    """

    def __init__(self, reserved=()):
        self._used = set(reserved)

    def take(self, raw: Any, fallback: str = "q") -> str:
        base = _NAME_RE.sub("_", str(raw or "")).strip("_") or fallback
        if base[0].isdigit():
            base = f"{fallback}_{base}"
        name, n = base, 2
        while name in self._used:
            name = f"{base}_{n}"
            n += 1
        self._used.add(name)
        return name


def unique_labels(texts: List[str]) -> List[str]:
    """Option labels unique within one question (Potato stores the label as
    the answer, so two options with the same text would be indistinguishable)."""
    out: List[str] = []
    seen = set()
    for t in texts:
        label = (str(t).strip() or "(blank)")
        candidate, n = label, 2
        while candidate in seen:
            candidate = f"{label} ({n})"
            n += 1
        seen.add(candidate)
        out.append(candidate)
    return out


_TAG_RE = re.compile(r"<[^>]+>")
#: Style and script blocks whose contents are not wording (survey tools put
#: CSS inside question text).
_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.I | re.S)


def strip_html(text: Any) -> str:
    """Plain text from a source's rich-text question wording. Kept short and
    conservative: Potato question descriptions are escaped, not rendered."""
    s = _TAG_RE.sub(" ", _BLOCK_RE.sub(" ", str(text or "")))
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", s).strip()


def combine(items: List[Dict[str, Any]], logic: str = "all") -> Optional[Dict[str, Any]]:
    """A display_logic rule from a list of items (None when empty)."""
    items = [i for i in items if i]
    if not items:
        return None
    return {"show_when": items, "logic": logic}


def rule_as_item(rule: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A whole rule as one show_when item, so it can be ANDed with another."""
    if not rule:
        return None
    items = rule["show_when"]
    if len(items) == 1:
        return items[0]
    return {rule.get("logic", "all"): items}


def and_rules(*rules: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    items = [rule_as_item(r) for r in rules if r]
    return combine([i for i in items if i], "all")
