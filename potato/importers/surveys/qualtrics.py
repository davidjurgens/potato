"""
Qualtrics survey files (.qsf) into Potato survey pages.

A .qsf is the JSON that Qualtrics writes from Tools > Import/Export > Export
Survey: ``{"SurveyEntry": {...}, "SurveyElements": [...]}``. The elements
used here are ``BL`` (blocks), ``FL`` (the survey flow), ``SQ`` (one per
question) and ``QO`` (quotas, reported). ``SO``, ``RS``, ``QC``, ``STAT``,
``PROJ``, ``NT`` and ``PL`` hold settings, statistics and notes and are
ignored; ``SCO`` is reported when it defines scoring categories.

The flow is walked in order. Each block becomes one page, and a page break
inside a block starts another (``<block>_p2``, ...).

Mapped:

* Questions: multiple choice (``radio``, ``multiselect``, ``select``),
  NPS, matrix Likert single answer (``multirate``), text entry (``text``,
  ``number`` when the content validation is a number, one ``text`` per
  field for forms), sliders (one ``slider`` per statement; star ratings as
  ``radio``), rank order (``ranking``), constant sum and descriptive text.
  Forced responses, a free-text box on an "Other" choice, and choice
  randomization.
* Display logic on questions; branch logic on the pages under a branch,
  ANDed down nested branches. Within a logic set ``And`` binds tighter than
  ``Or``, and between sets ``AndIf`` binds tighter than ``ElseIf``, as in
  Qualtrics.
* End of Survey inside a branch, and skip logic to the end of the survey,
  as ``exit_when``. Skip logic to the end of the block, or to a later
  question in the same block, as ``show_when`` on what is skipped.
* A block randomizer that shows every block in random order as a
  ``phases.counterbalance`` group. A randomizer that sets one embedded data
  field to one of several values (show 1 of n) as a between-subjects factor
  in ``conditions``; logic that tests that field tests ``condition.<field>``.
* Block question randomization.

Reported, not mapped: other embedded data, web services, authenticators,
quotas, scoring, loop and merge (the block is imported once), piped text,
matrix cell logic, "displayed" conditions, choice display logic, default
choices, question JavaScript, translations, custom validation, and the
question types Potato has no equivalent for.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    NameAllocator, SurveyImportResult, SurveyPage, Untranslatable, and_rules,
    combine, rule_as_item, strip_html, unique_labels)
from .expr import VarInfo, compare

_PIPE_RE = re.compile(r"\$\{[A-Za-z]+://[^}]*\}")
_LOCATOR_RE = re.compile(r"^q://(QID\d+)/([A-Za-z]+)(?:/([^/?]+))?(?:/([^/?]+))?")
_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_CODE_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_PARAGRAPH_RE = re.compile(r"</p\s*>|<br\s*/?>|</div\s*>|\n\s*\n", re.IGNORECASE)

#: Qualtrics comparison operators -> the shared translator's spellings
_OPS = {"EqualTo": "=", "NotEqualTo": "!=", "GreaterThan": ">", "GreaterThanOrEqual": ">=",
        "LessThan": "<", "LessThanOrEqual": "<=", "Contains": "contains",
        "DoesNotContain": "notcontains"}

_SINGLE_SELECTORS = {"SAVR", "SAHR", "SACOL", "NPS"}
_MULTI_SELECTORS = {"MAVR", "MAHR", "MACOL", "MSB"}
_DROPDOWN_SELECTORS = {"DL", "SB"}

#: Question types with no Potato equivalent
_UNSUPPORTED_TYPES = {
    "Captcha": "CAPTCHA", "FileUpload": "file upload", "Draw": "signature / drawing",
    "Signature": "signature", "HeatMap": "heat map", "HotSpot": "hot spot",
    "PGR": "pick, group and rank", "HL": "highlight", "DD": "drill down",
    "GAP": "gap analysis", "SBS": "side by side", "TreeSelect": "tree select",
}

_DEFAULT_EXIT_MESSAGE = "Thank you. This is the end of the study."


@dataclass
class _Ref:
    """A question as logic sees it."""
    qid: str
    kind: str                      # single | multi | text | number | form | slider | matrix | other
    qtype: str = ""
    name: Optional[str] = None     # the Potato question, for single/multi/text/number
    values: Dict[str, str] = field(default_factory=dict)       # choice id -> label
    fields: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # choice id -> (name, kind)


@dataclass
class _Occurrence:
    """One appearance of a block in the flow."""
    block_id: str
    pages: List[SurveyPage] = field(default_factory=list)
    #: (qid, index into pages, [scheme names]) in block order
    items: List[Tuple[str, int, List[str]]] = field(default_factory=list)
    scope: Dict[str, _Ref] = field(default_factory=dict)


def _text(html: Any) -> str:
    """Plain text of Qualtrics rich text, without its <style>/<script> blocks."""
    return strip_html(_CODE_RE.sub(" ", str(html or "")))


def _stem(text: str, label: str) -> str:
    """One field or statement of a grouped question: "How many hours: On weekdays"."""
    stem = text.rstrip(" .:?")
    return f"{stem}: {label}" if stem else label


def _numbered(d: Any) -> List[Dict[str, Any]]:
    """The "0", "1", ... entries of a Qualtrics logic object, in order."""
    if not isinstance(d, dict):
        return []
    keys = sorted((k for k in d if str(k).isdigit()), key=lambda k: int(k))
    return [d[k] for k in keys if isinstance(d[k], dict)]


def _ordered_ids(choices: Any, order: Any) -> List[str]:
    """Choice ids in display order. ``ChoiceOrder`` mixes ints and strings;
    ids it leaves out are appended."""
    if isinstance(choices, list):
        choices = {str(i + 1): c for i, c in enumerate(choices)}
    if not isinstance(choices, dict):
        return []
    keys = [str(k) for k in choices]
    ids = []
    for x in order or []:
        s = str(x)
        if s in keys and s not in ids:
            ids.append(s)
    return ids + [k for k in keys if k not in ids]


def _choice_map(choices: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(choices, list):
        return {str(i + 1): c for i, c in enumerate(choices) if isinstance(c, dict)}
    if isinstance(choices, dict):
        return {str(k): v for k, v in choices.items() if isinstance(v, dict)}
    return {}


def _number(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(n) if n.is_integer() else n


def _flag_on(value: Any) -> bool:
    return str(value).strip().lower() in ("on", "true", "1", "yes")


def _describe(logic: Any) -> str:
    """Readable form of a Qualtrics logic object for the report."""
    parts = []
    for s in _numbered(logic):
        for e in _numbered(s):
            desc = strip_html(e.get("Description"))
            if not desc:
                desc = " ".join(str(e.get(k)) for k in ("LeftOperand", "Operator", "RightOperand")
                                if e.get(k) is not None) or f"{e.get('LogicType') or '?'} condition"
            parts.append(desc)
    return "; ".join(parts) if parts else json.dumps(logic)[:200]


def _group(terms: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """OR of ANDs as one show_when item."""
    ands = []
    for t in terms:
        flat: List[Dict[str, Any]] = []
        for item in t:
            flat.extend(item["all"] if set(item) == {"all"} else [item])
        ands.append(flat[0] if len(flat) == 1 else {"all": flat})
    if len(ands) == 1:
        return ands[0]
    flat_or: List[Dict[str, Any]] = []
    for item in ands:
        flat_or.extend(item["any"] if set(item) == {"any"} else [item])
    return {"any": flat_or}


def _as_rule(item: Dict[str, Any]) -> Dict[str, Any]:
    if set(item) == {"any"}:
        return {"show_when": item["any"], "logic": "any"}
    if set(item) == {"all"}:
        return {"show_when": item["all"], "logic": "all"}
    return {"show_when": [item], "logic": "all"}


def _or_rules(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    items = [rule_as_item(r) for r in (a, b) if r]
    if len(items) < 2:
        return a or b
    return combine(items, "any")


def _negate(rule: Dict[str, Any]) -> Dict[str, Any]:
    return {"show_when": [{"not": rule_as_item(rule)}], "logic": "all"}


def _leaves(items):
    from potato.server_utils.display_logic import iter_leaf_conditions
    return [c for _p, c in iter_leaf_conditions(items or [])]


class QualtricsImporter:
    format_name = "qualtrics"
    description = "Qualtrics survey file (.qsf, from Export Survey)"
    file_extensions = [".qsf"]

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in (".qsf", ".json"):
            return False
        try:
            with path.open(encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        return self._looks_like(data)

    @staticmethod
    def _looks_like(data: Any) -> bool:
        return (isinstance(data, dict) and isinstance(data.get("SurveyEntry"), dict)
                and isinstance(data.get("SurveyElements"), list))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> SurveyImportResult:
        with Path(path).open(encoding="utf-8-sig") as f:
            data = json.load(f)
        return self.parse(data, options or {})

    # ------------------------------------------------------------------

    def parse(self, data: Dict[str, Any], options: dict) -> SurveyImportResult:
        if not self._looks_like(data):
            raise ValueError("not a Qualtrics survey file: expected SurveyEntry and SurveyElements")
        entry = data["SurveyEntry"]
        result = SurveyImportResult(source_format="Qualtrics",
                                    title=strip_html(entry.get("SurveyName")))
        self.result = result
        self.names = NameAllocator()
        self.page_names = NameAllocator(reserved={"annotation", "order", "counterbalance"})
        self.factor_names = NameAllocator()
        self.blocks: Dict[str, Dict[str, Any]] = {}
        self.sq: Dict[str, Dict[str, Any]] = {}
        flow = None
        for el in data["SurveyElements"]:
            if not isinstance(el, dict):
                continue
            kind, payload = el.get("Element"), el.get("Payload")
            if kind == "BL":
                blocks = payload.values() if isinstance(payload, dict) else (payload or [])
                for b in blocks:
                    if isinstance(b, dict) and b.get("ID"):
                        self.blocks[str(b["ID"])] = b
            elif kind == "FL":
                flow = payload
            elif kind == "SQ" and isinstance(payload, dict):
                qid = str(payload.get("QuestionID") or el.get("PrimaryAttribute") or "")
                if qid:
                    self.sq[qid] = payload
            elif kind == "QO" and payload:
                quotas = payload if isinstance(payload, list) else [payload]
                for q in quotas:
                    name = q.get("Name") if isinstance(q, dict) else None
                    result.skip(f"quota {el.get('PrimaryAttribute') or ''}".strip(), "quota",
                                name or "Potato does not cap or end responses by quota")
            elif kind == "SCO" and isinstance(payload, dict) and payload.get("ScoringCategories"):
                cats = [c.get("Name") for c in payload["ScoringCategories"] if isinstance(c, dict)]
                result.skip("survey", "scoring", ", ".join(str(c) for c in cats if c))
        if not isinstance(flow, dict):
            raise ValueError("the survey file has no survey flow (FL element)")

        # walk state
        self.first: Dict[str, _Ref] = {}       # qid -> first occurrence
        self.latest: Dict[str, _Ref] = {}      # qid -> most recent occurrence so far
        self.page_path: Dict[str, Tuple[int, ...]] = {}
        self.page_parts: Dict[str, List[Tuple[Dict[str, Any], str]]] = {}
        self.branches: Dict[int, Tuple[Any, str, Dict[str, _Ref]]] = {}
        self.branch_rules: Dict[int, Optional[Dict[str, Any]]] = {}
        self.pending_q: List[Tuple[List[Dict[str, Any]], Any, Dict[str, _Ref], str]] = []
        self.pending_skip: List[Tuple[str, _Occurrence, int, Any, str]] = []
        self.exits: List[Tuple[int, Tuple[int, ...], str, str]] = []
        self.skip_hidden: set = set()
        self.block_seen: Dict[str, int] = {}
        self.factor_of: Dict[str, str] = {}     # embedded field -> factor name
        self.factors: Dict[str, List[str]] = {}
        self.assignment = None
        self.languages: set = set()
        self.stopped = False
        self._quiet = False
        self._next_branch = 0

        self._flow(flow, ())

        # Logic last: conditions and questions anywhere in the flow are known now.
        for bid, (logic, where, scope) in self.branches.items():
            self.branch_rules[bid] = self._rule(logic, scope, where, "branch logic",
                                                "the pages under it are shown to everyone "
                                                "who reaches the branch")
        for page in result.pages:
            for bid in self.page_path.get(page.name, ()):
                rule = self.branch_rules.get(bid)
                if rule:
                    self.page_parts.setdefault(page.name, []).append(
                        (rule, f"branch logic ({self.branches[bid][1]})"))
        for schemes, logic, scope, where in self.pending_q:
            rule = self._rule(logic, scope, where, "display logic", "the question is always shown")
            if rule:
                for s in schemes:
                    s["display_logic"] = and_rules(s.get("display_logic"), rule)
        for qid, occ, page_idx, entries, where in self.pending_skip:
            self._skip_logic(qid, occ, page_idx, entries, where)
        for before, path, message, where in self.exits:
            self._exit(before, path, message, where)

        self._finish_page_rules()
        for block_id, count in self.block_seen.items():
            if count > 1:
                desc = strip_html(self.blocks[block_id].get("Description")) or block_id
                result.warnings.append(
                    f"block '{desc}' appears {count} times in the flow; each appearance is "
                    "imported as its own page(s), with question names suffixed _2, _3, ...")
        if self.factors:
            result.conditions = {"factors": {f: list(v) for f, v in self.factors.items()},
                                 "assignment": self.assignment or "balanced"}
        if self.languages:
            result.skip("survey", "translations",
                        f"{', '.join(sorted(self.languages))}: only the main language is imported")
        seen = set()
        unique = []
        for u in result.untranslated:
            key = (u.where, u.what, u.detail)
            if key not in seen:
                seen.add(key)
                unique.append(u)
        result.untranslated = unique
        result.warnings = list(dict.fromkeys(result.warnings))
        return result

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------

    def _flow(self, node: Dict[str, Any], path: Tuple[int, ...]) -> None:
        ntype = str(node.get("Type") or "")
        where = f"flow {node.get('FlowID') or ntype}"
        if ntype in ("Root", "Group", "Authenticator"):
            if ntype == "Authenticator":
                self.result.skip(where, "authenticator",
                                 "Potato's own login replaces it; the elements under it are imported")
            self._children(node, path)
        elif ntype in ("Block", "Standard"):
            self._block(str(node.get("ID") or ""), path, where)
        elif ntype == "Branch":
            bid = self._next_branch
            self._next_branch += 1
            desc = strip_html(node.get("Description")) or _describe(node.get("BranchLogic"))
            self.branches[bid] = (node.get("BranchLogic"), f"{where}: {desc}"[:160],
                                  dict(self.latest))
            self._children(node, path + (bid,))
        elif ntype in ("BlockRandomizer", "Randomizer"):
            self._randomizer(node, path, where)
        elif ntype == "EmbeddedData":
            self._embedded_data(node, where)
        elif ntype == "EndSurvey":
            self._end_survey(node, path, where)
        elif ntype == "WebService":
            self.result.skip(where, "web service", str(node.get("URL") or ""))
        elif ntype == "Quota":
            self.result.skip(where, "quota element")
        else:
            self.result.skip(where, f"flow element '{ntype}'")
            self._children(node, path)

    def _children(self, node: Dict[str, Any], path: Tuple[int, ...]) -> None:
        for child in node.get("Flow") or []:
            if not isinstance(child, dict):
                continue
            if self.stopped:
                self.result.skip(f"flow {child.get('FlowID') or ''}".strip(),
                                 "elements after an unconditional End of Survey",
                                 "Qualtrics never shows them; not imported")
                return
            self._flow(child, path)

    def _end_survey(self, node: Dict[str, Any], path: Tuple[int, ...], where: str) -> None:
        options = node.get("Options") or {}
        if isinstance(options, dict) and options.get("EOSRedirectURL"):
            self.result.skip(where, "end-of-survey redirect", str(options["EOSRedirectURL"]))
        message = _DEFAULT_EXIT_MESSAGE
        if not path:
            self.stopped = True
            return
        self.exits.append((len(self.result.pages), path, message, where))

    def _last_page_on(self, before: int, path: Tuple[int, ...]) -> Optional[SurveyPage]:
        """The latest page (of the first ``before``) that every participant at
        ``path`` has passed: its own branches are all among the enclosing ones
        and no skip logic can hide it. exit_when is checked on leaving a page,
        so a skipped page would never screen anyone out."""
        for page in reversed(self.result.pages[:before]):
            own = self.page_path.get(page.name, ())
            if path[:len(own)] == own and page.name not in self.skip_hidden:
                return page
        return None

    def _embedded_data(self, node: Dict[str, Any], where: str) -> None:
        fields = node.get("EmbeddedData") or []
        described = []
        for f in fields:
            if not isinstance(f, dict):
                continue
            name = f.get("Field") or f.get("Description")
            if f.get("Value") not in (None, ""):
                described.append(f"{name} = {str(f['Value'])[:60]}")
            else:
                described.append(f"{name} ({str(f.get('Type') or 'field').lower()})")
        if described:
            self.result.skip(where, "embedded data", "; ".join(described))

    def _randomizer(self, node: Dict[str, Any], path: Tuple[int, ...], where: str) -> None:
        children = [c for c in node.get("Flow") or [] if isinstance(c, dict)]
        n = len(children)
        try:
            subset = int(str(node.get("SubSet")).strip())
        except (TypeError, ValueError):
            subset = n
        even = bool(node.get("EvenPresentation")) and str(node.get("EvenPresentation")).lower() != "false"
        types = {str(c.get("Type")) for c in children}
        if not children:
            return
        if types == {"EmbeddedData"}:
            if subset < n and self._condition_factor(children, even, where):
                return
            self.result.skip(where, "randomizer over embedded data",
                             f"presents {subset} of {n}; the assignment is not imported")
            return
        if types <= {"Block", "Standard"} and subset >= n:
            groups = []
            for child in children:
                before = len(self.result.pages)
                self._flow(child, path)
                groups.append(self.result.pages[before:])
            if n >= 2 and all(len(g) == 1 for g in groups):
                self.result.counterbalance.append(
                    {"pages": [g[0].name for g in groups], "method": "random"})
            elif n >= 2:
                self.result.skip(where, "block randomizer",
                                 "a randomized block has page breaks (or no questions), so the "
                                 "blocks are imported in their listed order")
            return
        if subset >= n:
            detail = "randomizes elements that are not single blocks; imported in listed order"
        else:
            detail = (f"presents {subset} of {n} elements; all {n} are imported in listed "
                      "order and every participant sees them")
        self.result.skip(where, "randomizer", detail)
        for child in children:
            self._flow(child, path)

    def _condition_factor(self, children: List[Dict[str, Any]], even: bool, where: str) -> bool:
        """Show-1-of-n over embedded data that sets one field: a between-subjects factor."""
        field_name = None
        levels: List[str] = []
        for child in children:
            sets = [f for f in child.get("EmbeddedData") or []
                    if isinstance(f, dict) and f.get("Value") not in (None, "")]
            if len(sets) != 1:
                return False
            fname = str(sets[0].get("Field") or sets[0].get("Description") or "")
            value = str(sets[0]["Value"])
            if not fname or (field_name and fname != field_name) or _PIPE_RE.search(value):
                return False
            field_name = fname
            levels.append(value)
        if len(levels) < 2 or len(set(levels)) != len(levels):
            return False
        if field_name in self.factor_of:
            self.result.skip(where, "second randomizer setting the same embedded field",
                             field_name)
            return True
        factor = self.factor_names.take(_IDENT_RE.sub("_", field_name).strip("_"), "factor")
        self.factor_of[field_name] = factor
        self.factors[factor] = levels
        method = "balanced" if even else "random"
        if self.assignment and self.assignment != method:
            self.result.warnings.append(
                f"{where}: randomizers disagree on even presentation; all conditions use "
                f"'{self.assignment}' assignment")
        self.assignment = self.assignment or method
        if factor != field_name:
            self.result.warnings.append(
                f"{where}: embedded field '{field_name}' became condition factor '{factor}'")
        return True

    # ------------------------------------------------------------------
    # Blocks and pages
    # ------------------------------------------------------------------

    def _block(self, block_id: str, path: Tuple[int, ...], where: str) -> None:
        block = self.blocks.get(block_id)
        if block is None:
            self.result.skip(where, "block not in the survey file", block_id)
            return
        if str(block.get("Type")) == "Trash":
            return
        desc = strip_html(block.get("Description")) or block_id
        bwhere = f"block '{desc}'"
        seen = self.block_seen.get(block_id, 0)
        self.block_seen[block_id] = seen + 1
        options = block.get("Options") or {}
        looping = options.get("Looping")
        if looping and str(looping) != "None" and not seen:
            self.result.skip(bwhere, "loop and merge",
                             f"looping by {looping}; the block is imported once")

        segments: List[List[str]] = [[]]
        for el in block.get("BlockElements") or []:
            if not isinstance(el, dict):
                continue
            if el.get("Type") == "Page Break":
                segments.append([])
            elif el.get("Type") == "Question" and el.get("QuestionID"):
                segments[-1].append(str(el["QuestionID"]))
        randomize = self._block_randomization(options, bwhere, sum(len(s) for s in segments),
                                              report=not seen)
        if randomize:
            segments = [[q for s in segments for q in s]]

        occ = _Occurrence(block_id=block_id)
        first_name = None
        for qids in segments:
            questions: List[Dict[str, Any]] = []
            placed: List[Tuple[str, List[str]]] = []
            for qid in qids:
                schemes = self._question(qid, occ, bwhere, report=not seen)
                if schemes:
                    questions.extend(schemes)
                    placed.append((qid, [s["name"] for s in schemes]))
            if not questions:
                continue
            if first_name is None:
                first_name = self.page_names.take(desc, "page")
                name = first_name
            else:
                name = self.page_names.take(f"{first_name}_p{len(occ.pages) + 1}", "page")
            page = SurveyPage(name=name, questions=questions)
            if randomize:
                page.randomize_questions = True
            self.page_path[name] = path
            occ.pages.append(page)
            for qid, names in placed:
                occ.items.append((qid, len(occ.pages) - 1, names))
            self.result.pages.append(page)
        # skip logic needs the block's pages, so it waits for the whole block
        for qid, page_idx, _names in occ.items:
            skip = (self.sq.get(qid) or {}).get("SkipLogic")
            if skip:
                self.pending_skip.append((qid, occ, page_idx, skip, self._where(qid)))

    def _block_randomization(self, options: Dict[str, Any], where: str, count: int,
                             report: bool) -> bool:
        mode = options.get("RandomizeQuestions")
        if mode in (None, False, "", "false", "False", "None"):
            return False
        adv = ((options.get("Randomization") or {}).get("Advanced") or {}) \
            if isinstance(options.get("Randomization"), dict) else {}
        if mode == "RandomWithXPerPage":
            per_page = _number(adv.get("QuestionsPerPage")) or 0
            if report and 0 < per_page < count:
                self.result.skip(where, "question randomization",
                                 f"{int(per_page)} questions per page; imported as one "
                                 "randomized page")
            return True
        if report:
            self.result.skip(where, "question randomization",
                             f"'{mode}' (subsets or fixed positions) is not supported; "
                             "questions keep their order")
        return False

    def _where(self, qid: str) -> str:
        tag = (self.sq.get(qid) or {}).get("DataExportTag")
        return f"{qid} ({tag})" if tag and tag != qid else qid

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def _question(self, qid: str, occ: _Occurrence, bwhere: str, report: bool) -> List[Dict[str, Any]]:
        p = self.sq.get(qid)
        if p is None:
            self.result.skip(bwhere, "block lists a question that is not in the file", qid)
            return []
        where = self._where(qid)
        # A block's later appearances repeat its questions under new names;
        # what did not carry over was reported on the first.
        self._quiet = not report
        try:
            schemes, ref = self._schemes(p, qid, where)
        finally:
            self._quiet = False
        if not schemes:
            return []
        occ.scope[qid] = ref
        self.first.setdefault(qid, ref)
        self.latest[qid] = ref

        text = _text(p.get("QuestionText")) or str(p.get("DataExportTag") or qid)
        settings = (p.get("Validation") or {}).get("Settings") or {}
        force = str(settings.get("ForceResponse") or "")
        for s in schemes:
            s.setdefault("description", text)
            if force == "ON" and s["annotation_type"] != "pure_display":
                s["label_requirement"] = {"required": True}
        if report:
            if force == "RequestResponse":
                self.result.skip(where, "request response",
                                 "Qualtrics asks before moving on unanswered; Potato has no soft requirement")
            if settings.get("Type") == "CustomValidation":
                self.result.skip(where, "custom validation", _describe(
                    (settings.get("CustomValidation") or {}).get("Logic")))
            pipes = _PIPE_RE.findall(str(p.get("QuestionText") or "")) + [
                pipe for c in _choice_map(p.get("Choices")).values()
                for pipe in _PIPE_RE.findall(str(c.get("Display") or ""))]
            if pipes:
                self.result.skip(where, "piped text", ", ".join(dict.fromkeys(pipes)) +
                                 " (shown as written)")
            for cid, c in _choice_map(p.get("Choices")).items():
                if c.get("DisplayLogic"):
                    self.result.skip(where, f"display logic on choice {cid}",
                                     _describe(c["DisplayLogic"]))
            if p.get("DefaultChoices"):
                self.result.skip(where, "default choices", json.dumps(p["DefaultChoices"])[:200])
            if str(p.get("QuestionJS") or "").strip() not in ("", "false", "False"):
                self.result.skip(where, "question JavaScript", "not run")
        if isinstance(p.get("Language"), dict) and p["Language"]:
            self.languages.update(str(k) for k in p["Language"])
        if p.get("DisplayLogic"):
            self.pending_q.append((schemes, p["DisplayLogic"], occ.scope, where))
        if len(schemes) == 1:
            self.result.name_map.setdefault(qid, schemes[0]["name"])
        return schemes

    def _skip(self, where: str, what: str, detail: str = "") -> None:
        if not self._quiet:
            self.result.skip(where, what, detail)

    def _schemes(self, p: Dict[str, Any], qid: str, where: str):
        qtype = str(p.get("QuestionType") or "")
        sel = str(p.get("Selector") or "")
        sub = str(p.get("SubSelector") or "")
        tag = str(p.get("DataExportTag") or qid)
        choices = _choice_map(p.get("Choices"))
        ids = _ordered_ids(p.get("Choices"), p.get("ChoiceOrder"))
        settings = (p.get("Validation") or {}).get("Settings") or {}
        config = p.get("Configuration") or {}
        text = _text(p.get("QuestionText"))

        if qtype in ("MC", "Matrix", "RO", "CS") and isinstance(p.get("DynamicChoices"), dict):
            dyn = p["DynamicChoices"]
            loc = str(dyn.get("Locator") or "")
            m = _LOCATOR_RE.match(loc)
            src = m.group(1) if m else str(dyn.get("Source") or "")
            if not ids and src in self.sq:
                choices = _choice_map(self.sq[src].get("Choices"))
                ids = _ordered_ids(self.sq[src].get("Choices"), self.sq[src].get("ChoiceOrder"))
            self._skip(where, "carried-forward choices",
                       f"{loc or src}: every choice of {src} is listed, not only the carried ones")
        if qtype in ("MC", "RO", "CS", "Matrix") and not ids and sel != "NPS":
            self._skip(where, "question without choices", text[:120])
            return [], None

        if qtype == "MC" or qtype == "NPS":
            if qtype == "NPS" or sel == "NPS":
                labels = [str(i) for i in range(11)]
                values = {lab: lab for lab in labels}
                for cid in ids:
                    disp = strip_html(choices[cid].get("Display"))
                    values[cid] = disp if disp in labels else (cid if cid in labels else values.get(cid, cid))
                name = self.names.take(tag)
                ref = _Ref(qid, "single", "NPS", name, values)
                return [{"name": name, "annotation_type": "radio", "labels": labels,
                         "horizontal": True}], ref
            if sel in _SINGLE_SELECTORS or (sel.startswith("SA") and sel not in _DROPDOWN_SELECTORS):
                atype, kind = "radio", "single"
            elif sel in _MULTI_SELECTORS or sel.startswith("MA"):
                atype, kind = "multiselect", "multi"
            elif sel in _DROPDOWN_SELECTORS:
                atype, kind = "select", "single"
            else:
                self._skip(where, f"multiple choice layout '{sel}'", text[:120])
                return [], None
            labels = unique_labels([strip_html(choices[c].get("Display")) for c in ids])
            values = dict(zip(ids, labels))
            name = self.names.take(tag)
            scheme: Dict[str, Any] = {"name": name, "annotation_type": atype, "labels": labels}
            if sel == "SAHR":
                scheme["horizontal"] = True
            free = [c for c in ids if _flag_on(choices[c].get("TextEntry"))]
            if free:
                scheme["has_free_response"] = {"instruction": values[free[0]]}
                if len(free) > 1:
                    self._skip(where, "more than one choice with a text box",
                                     f"only '{values[free[0]]}' keeps its box")
            exclusive = [values[c] for c in ids if _flag_on(choices[c].get("ExclusiveAnswer"))]
            if exclusive and atype == "multiselect":
                self._skip(where, "exclusive choice",
                                 f"{', '.join(exclusive)} can be selected with other choices")
            self._choice_randomization(p, scheme, where)
            return [scheme], _Ref(qid, kind, "MC", name, values)

        if qtype == "Matrix":
            if sel == "Likert" and sub in ("SingleAnswer", ""):
                rows = unique_labels([strip_html(choices[c].get("Display")) for c in ids])
                answers = _choice_map(p.get("Answers"))
                aids = _ordered_ids(p.get("Answers"), p.get("AnswerOrder"))
                cols = unique_labels([strip_html(answers[a].get("Display")) for a in aids])
                if not rows or not cols:
                    self._skip(where, "matrix without statements or scale points", text[:120])
                    return [], None
                name = self.names.take(tag)
                scheme = {"name": name, "annotation_type": "multirate", "options": rows,
                          "labels": cols}
                self._choice_randomization(p, scheme, where)
                return [scheme], _Ref(qid, "matrix", "Matrix", name)
            self._skip(where, f"matrix type {sel}/{sub}" if sub else f"matrix type {sel}",
                             text[:120])
            return [], None

        if qtype == "TE":
            ctype = settings.get("ContentType") if settings.get("Type") in ("ContentType", None, "") else None
            if sel == "FORM":
                schemes, fields = [], {}
                for cid in ids:
                    label = strip_html(choices[cid].get("Display")) or cid
                    fname = self.names.take(f"{tag}_{cid}")
                    schemes.append({"name": fname, "annotation_type": "text",
                                    "description": _stem(text, label)})
                    fields[cid] = (fname, "text")
                    self.result.name_map.setdefault(f"{qid}.{cid}", fname)
                if not schemes:
                    self._skip(where, "form without fields", text[:120])
                    return [], None
                return schemes, _Ref(qid, "form", "TE", None, fields=fields)
            name = self.names.take(tag)
            if ctype == "ValidNumber":
                vn = settings.get("ValidNumber") if isinstance(settings.get("ValidNumber"), dict) else {}
                scheme = {"name": name, "annotation_type": "number"}
                lo = _number(vn.get("Min", settings.get("MinNumber")))
                hi = _number(vn.get("Max", settings.get("MaxNumber")))
                if lo is not None:
                    scheme["min"] = lo
                if hi is not None:
                    scheme["max"] = hi
                dec = _number(vn.get("NumDecimals"))
                if dec is not None:
                    scheme["step"] = 1 if dec <= 0 else round(10 ** -int(dec), int(dec))
                return [scheme], _Ref(qid, "number", "TE", name)
            if ctype:
                self._skip(where, f"content validation '{ctype}'", "imported as plain text")
            scheme = {"name": name, "annotation_type": "text"}
            if sel in ("ML", "ESTB"):
                scheme["textarea"] = {"on": True, "rows": 4}
            elif sel == "PW":
                self.result.warnings.append(f"{where}: password field imported as plain text")
            return [scheme], _Ref(qid, "text", "TE", name)

        if qtype == "Slider":
            if sel in ("HSLIDER", "HBAR"):
                lo = _number(config.get("CSSliderMin"))
                hi = _number(config.get("CSSliderMax"))
                lo = 0 if lo is None else lo
                hi = 100 if hi is None else hi
                if lo >= hi:
                    self._skip(where, "slider range", f"{lo} to {hi}; 0 to 100 used")
                    lo, hi = 0, 100
                dec = _number(config.get("NumDecimals")) or 0
                step = 1 if dec <= 0 else round(10 ** -int(dec), int(dec))
                return self._per_statement(qid, tag, text, ids, choices, lambda name: {
                    "name": name, "annotation_type": "slider", "min_value": lo,
                    "max_value": hi, "starting_value": lo, "step": step}, "number")
            if sel == "STAR":
                n = int(_number(config.get("NumStars")) or _number(config.get("CSSliderMax")) or 5)
                labels = [str(i) for i in range(1, max(n, 2) + 1)]
                return self._per_statement(qid, tag, text, ids, choices, lambda name: {
                    "name": name, "annotation_type": "radio", "labels": list(labels),
                    "horizontal": True}, "single")
            self._skip(where, f"slider type {sel}", text[:120])
            return [], None

        if qtype == "RO":
            labels = unique_labels([strip_html(choices[c].get("Display")) for c in ids])
            if not labels:
                self._skip(where, "rank order without choices", text[:120])
                return [], None
            name = self.names.take(tag)
            if isinstance(p.get("Randomization"), dict) and \
                    str(p["Randomization"].get("Type")) not in ("None", ""):
                self._skip(where, "choice randomization", "Potato rankings keep the listed order")
            return [{"name": name, "annotation_type": "ranking", "labels": labels}], \
                _Ref(qid, "other", "RO", name)

        if qtype == "CS":
            labels = unique_labels([strip_html(choices[c].get("Display")) for c in ids])
            if not labels:
                self._skip(where, "constant sum without choices", text[:120])
                return [], None
            name = self.names.take(tag)
            scheme = {"name": name, "annotation_type": "constant_sum", "labels": labels}
            total = None
            for source in (config, settings):
                for key in ("TotalPoints", "Total", "ChoiceTotal", "CSTotal"):
                    if total is None and isinstance(source, dict):
                        total = _number(source.get(key))
            if total:
                scheme["total_points"] = int(total)
            else:
                self._skip(where, "constant sum total",
                                 "no total in the export; Potato's default of 100 applies")
            return [scheme], _Ref(qid, "other", "CS", name)

        if qtype == "DB":
            # the first paragraph is the header, the rest are its lines
            raw = _CODE_RE.sub(" ", str(p.get("QuestionText") or ""))
            paragraphs = [strip_html(part) for part in _PARAGRAPH_RE.split(raw)]
            paragraphs = [part for part in paragraphs if part]
            if sel == "GRB":
                self._skip(where, "graphic", "images are not imported")
            if not paragraphs:
                return [], None
            name = self.names.take(tag)
            scheme = {"name": name, "annotation_type": "pure_display",
                      "description": paragraphs[0]}
            body = paragraphs[1:]
            if len(set(body)) != len(body):
                body = [" ".join(body)]   # display lines must be distinct
            if body:
                scheme["labels"] = body
            return [scheme], _Ref(qid, "other", "DB", name)

        if qtype in ("Timing", "Meta"):
            self._skip(where, f"{qtype.lower()} question",
                             "Potato records time on page and the browser itself"
                             if qtype == "Timing" else "browser metadata is not collected")
            return [], None
        what = _UNSUPPORTED_TYPES.get(qtype)
        self._skip(where, f"question type {qtype}/{sel}" + (f" ({what})" if what else ""),
                         text[:120])
        return [], None

    def _per_statement(self, qid, tag, text, ids, choices, make, kind):
        """One question per slider statement (Qualtrics exports them as tag_<id>)."""
        if len(ids) <= 1:
            name = self.names.take(tag)
            scheme = make(name)
            label = strip_html(choices[ids[0]].get("Display")) if ids else ""
            if label and label != text:
                scheme["description"] = _stem(text, label)
            fields = {ids[0]: (name, kind)} if ids else {}
            return [scheme], _Ref(qid, "slider", "Slider", None, fields=fields)
        schemes, fields = [], {}
        for cid in ids:
            label = strip_html(choices[cid].get("Display")) or cid
            name = self.names.take(f"{tag}_{cid}")
            scheme = make(name)
            scheme["description"] = _stem(text, label)
            schemes.append(scheme)
            fields[cid] = (name, kind)
            self.result.name_map.setdefault(f"{qid}.{cid}", name)
        return schemes, _Ref(qid, "slider", "Slider", None, fields=fields)

    def _choice_randomization(self, p: Dict[str, Any], scheme: Dict[str, Any], where: str) -> None:
        r = p.get("Randomization")
        if not isinstance(r, dict):
            return
        rtype = str(r.get("Type") or "")
        subset = _number(r.get("TotalRandSubset")) or 0
        if rtype == "All" and not subset:
            scheme["randomize_order"] = True
        elif rtype == "Advanced":
            adv = r.get("Advanced") or {}
            pinned = [x for x in adv.get("FixedOrder") or [] if x != "{~Randomized~}"]
            if pinned or adv.get("RandomSubSet") or _number(adv.get("TotalRandSubset")):
                self._skip(where, "advanced choice randomization",
                                 "fixed positions or subsets; choices keep their listed order")
            else:
                scheme["randomize_order"] = True
        elif rtype not in ("None", ""):
            self._skip(where, f"choice randomization '{rtype}'",
                             "choices keep their listed order")

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _rule(self, logic: Any, scope: Dict[str, _Ref], where: str, what: str, effect: str):
        try:
            return self._logic_rule(logic, scope)
        except Untranslatable as e:
            self.result.skip(where, what, f"{_describe(logic)} ({e}); {effect}")
            return None

    def _logic_rule(self, logic: Any, scope: Dict[str, _Ref]) -> Dict[str, Any]:
        sets = _numbered(logic)
        if not sets:
            raise Untranslatable("empty logic")
        terms: List[List[Dict[str, Any]]] = []
        for i, s in enumerate(sets):
            item = self._set_item(s, scope)
            stype = s.get("Type")
            if i == 0 or stype in (None, "", "AndIf"):
                if terms:
                    terms[-1].append(item)
                else:
                    terms.append([item])
            else:
                # ElseIf (and anything else) starts a new OR term
                terms.append([item])
        return _as_rule(_group(terms))

    def _set_item(self, s: Dict[str, Any], scope: Dict[str, _Ref]) -> Dict[str, Any]:
        exprs = _numbered(s)
        if not exprs:
            raise Untranslatable("an empty condition set")
        terms: List[List[Dict[str, Any]]] = []
        for i, e in enumerate(exprs):
            item = self._expr(e, scope)
            if i > 0 and str(e.get("Conjuction") or e.get("Conjunction") or "") == "Or":
                terms.append([item])
            elif terms:
                terms[-1].append(item)
            else:
                terms.append([item])
        return _group(terms)

    def _resolve(self, qid: str, scope: Dict[str, _Ref]) -> _Ref:
        ref = scope.get(qid) or self.first.get(qid)
        if ref is None:
            if qid in self.sq:
                raise Untranslatable(f"{qid} is not imported")
            raise Untranslatable(f"unknown question {qid}")
        return ref

    def _expr(self, e: Dict[str, Any], scope: Dict[str, _Ref]) -> Dict[str, Any]:
        ltype = str(e.get("LogicType") or "Question")
        op = str(e.get("Operator") or "")
        right = e.get("RightOperand")
        if ltype == "EmbeddedField":
            fname = str(e.get("LeftOperand") or "")
            factor = self.factor_of.get(fname)
            if not factor:
                raise Untranslatable(f"embedded data field '{fname}'")
            levels = self.factors[factor]
            info = VarInfo(schema=f"condition.{factor}", kind="single",
                           values={v: v for v in levels})
            if op in ("EqualTo", "NotEqualTo"):
                return compare(info, _OPS[op], "" if right is None else str(right))
            return self._text_op(info, op, right)
        if ltype != "Question":
            raise Untranslatable(f"{ltype} condition")
        locator = str(e.get("LeftOperand") or e.get("ChoiceLocator") or "")
        m = _LOCATOR_RE.match(locator)
        if not m:
            raise Untranslatable(f"locator {locator!r}")
        qid, part, a, b = m.groups()
        if op in ("Displayed", "NotDisplayed"):
            raise Untranslatable("whether a question or choice was displayed")
        ref = self._resolve(qid, scope)
        if part == "SelectableChoice":
            if b is not None or ref.kind == "matrix":
                raise Untranslatable("a matrix cell")
            if ref.kind not in ("single", "multi") or not ref.name:
                raise Untranslatable(f"a choice of a {ref.qtype} question")
            if a not in ref.values:
                raise Untranslatable(f"choice {a} of {qid} does not exist")
            if op not in ("Selected", "NotSelected"):
                raise Untranslatable(f"'{op}' on a choice")
            info = VarInfo(schema=ref.name, kind=ref.kind, values=ref.values)
            if ref.kind == "multi":
                return compare(info, "contains" if op == "Selected" else "notcontains", a)
            return compare(info, "=" if op == "Selected" else "!=", a)
        if part in ("ChoiceTextEntryValue", "ChoiceNumericEntryValue"):
            if a is not None:
                if a not in ref.fields:
                    raise Untranslatable(f"the text entered for choice {a} of {qid}")
                name, kind = ref.fields[a]
                info = VarInfo(schema=name, kind="number" if kind == "number" else "text")
            elif ref.kind in ("text", "number"):
                info = VarInfo(schema=ref.name, kind=ref.kind)
            else:
                raise Untranslatable(f"the text of a {ref.qtype} question")
            return self._text_op(info, op, right)
        if part == "SelectedChoicesCount":
            if ref.kind not in ("single", "multi") or not ref.name:
                raise Untranslatable(f"a selection count on a {ref.qtype} question")
            if op not in _OPS or _OPS[op] in ("contains", "notcontains"):
                raise Untranslatable(f"'{op}' on a selection count")
            return compare(VarInfo(schema=ref.name, kind="count"), _OPS[op], right)
        raise Untranslatable(f"{part} reference")

    @staticmethod
    def _text_op(info: VarInfo, op: str, right: Any) -> Dict[str, Any]:
        if op == "Empty":
            return {"schema": info.schema, "operator": "empty"}
        if op == "NotEmpty":
            return {"schema": info.schema, "operator": "not_empty"}
        if op == "MatchesRegex":
            return {"schema": info.schema, "operator": "matches", "value": str(right or "")}
        if op not in _OPS:
            raise Untranslatable(f"operator '{op}'")
        sym = _OPS[op]
        value: Any = "" if right is None else right
        if info.kind == "number" and sym in ("=", "!=") and value != "":
            n = _number(value)
            if n is None:
                raise Untranslatable(f"a number compared with {value!r}")
            value = n
        if sym in ("contains", "notcontains") and info.values:
            # substring tests on a condition level: compare() would demand a level
            return {"schema": info.schema,
                    "operator": "contains" if sym == "contains" else "not_contains",
                    "value": str(value)}
        return compare(info, sym, value)

    # ------------------------------------------------------------------
    # Skip logic, End of Survey, page rules
    # ------------------------------------------------------------------

    def _skip_logic(self, qid: str, occ: _Occurrence, page_idx: int, entries: Any,
                    where: str) -> None:
        for entry in entries if isinstance(entries, list) else [entries]:
            if not isinstance(entry, dict):
                continue
            dest = str(entry.get("SkipToDestination") or "")
            expr = {"LogicType": "Question",
                    "LeftOperand": entry.get("Locator") or entry.get("ChoiceLocator"),
                    "Operator": entry.get("Condition"),
                    "RightOperand": entry.get("RightOperand")}
            desc = f"{entry.get('Condition')} {entry.get('Locator') or entry.get('ChoiceLocator')} -> {dest}"
            try:
                cond = _as_rule(self._expr(expr, occ.scope))
            except Untranslatable as e:
                self.result.skip(where, "skip logic", f"{desc} ({e})")
                continue
            page = occ.pages[page_idx]
            if dest == "ENDOFSURVEY":
                rule = dict(cond)
                old = page.exit_when
                if old:
                    merged = _or_rules({"show_when": old["show_when"], "logic": old.get("logic", "all")}, rule)
                    merged["message"] = old.get("message", _DEFAULT_EXIT_MESSAGE)
                    page.exit_when = merged
                else:
                    rule["message"] = _DEFAULT_EXIT_MESSAGE
                    page.exit_when = rule
                continue
            if dest == "ENDOFBLOCK":
                target_page, target_q = len(occ.pages), None
            else:
                target = next(((pi, i) for i, (q, pi, _n) in enumerate(occ.items) if q == dest), None)
                here = next(i for i, (q, _pi, _n) in enumerate(occ.items) if q == qid)
                if target is None or target[1] <= here:
                    self.result.skip(where, "skip logic",
                                     f"{desc}: only skips to the end of the survey, the end of "
                                     "the block or a later question in the same block are imported")
                    continue
                target_page, target_q = target
            # Qualtrics applies skip logic when the page is submitted, so the
            # rest of the page stays visible; what follows it is skipped.
            negated = _negate(cond)
            for pi in range(page_idx + 1, min(target_page, len(occ.pages))):
                self.page_parts.setdefault(occ.pages[pi].name, []).append(
                    (negated, f"skip logic on {where}"))
                self.skip_hidden.add(occ.pages[pi].name)
            if target_q is not None and target_page > page_idx:
                for q, pi, names in occ.items[:target_q]:
                    if pi != target_page:
                        continue
                    for s in occ.pages[pi].questions:
                        if s["name"] in names:
                            s["display_logic"] = and_rules(s.get("display_logic"), negated)

    def _exit(self, before: int, path: Tuple[int, ...], message: str, where: str) -> None:
        page = self._last_page_on(before, path)
        if page is None:
            self.result.skip(where, "End of Survey in a branch",
                             "no page comes before it to end the study from")
            return
        later = self.result.pages[self.result.pages.index(page) + 1:before]
        if later:
            self.result.warnings.append(
                f"{where}: End of Survey is checked after page '{page.name}', so the "
                f"participants it screens out no longer see {', '.join(p.name for p in later)} "
                "first, as they could in Qualtrics")
        rules = []
        for bid in path:
            rule = self.branch_rules.get(bid)
            if rule is None:
                self.result.skip(where, "End of Survey in a branch",
                                 "the branch logic did not translate, so nobody is screened out here")
                return
            rules.append(rule)
        rule = and_rules(*rules)
        if any(page.name in cb["pages"] for cb in self.result.counterbalance):
            self.result.warnings.append(
                f"{where}: the study can end after page '{page.name}', which is counterbalanced")
        old = page.exit_when
        if old:
            merged = _or_rules({"show_when": old["show_when"], "logic": old.get("logic", "all")}, rule)
            merged["message"] = old.get("message", message)
            page.exit_when = merged
        else:
            page.exit_when = dict(rule, message=message)

    def _finish_page_rules(self) -> None:
        """Page rules may only test answers from earlier pages (exit rules:
        this page or earlier); the server refuses anything else at boot."""
        position: Dict[str, int] = {}
        for i, page in enumerate(self.result.pages):
            for q in page.questions:
                position.setdefault(q["name"], i)

        def refs_ok(rule, limit):
            for leaf in _leaves(rule["show_when"]):
                schema = str(leaf.get("schema", ""))
                if schema.startswith("condition."):
                    continue
                if position.get(schema, len(self.result.pages)) > limit:
                    return False
            return True

        for i, page in enumerate(self.result.pages):
            parts = []
            for rule, source in self.page_parts.get(page.name, []):
                if refs_ok(rule, i - 1):
                    parts.append(rule)
                else:
                    self.result.skip(f"page '{page.name}'", source,
                                     "tests a question asked on this page or later; the page "
                                     "is shown without this condition")
            page.show_when = and_rules(*parts) if parts else None
            if page.exit_when and not refs_ok(page.exit_when, i):
                self.result.skip(f"page '{page.name}'", "End of Survey",
                                 "tests a question asked after this page; not imported")
                page.exit_when = None
