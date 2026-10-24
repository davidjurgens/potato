"""
A small expression parser shared by the survey importers, and the translation
of its trees into display_logic items.

Survey tools write show/hide logic in their own infix languages:

* SurveyJS: ``{age} >= 18 and ({country} = 'US' or {region} notempty)``
* XLSForm (XPath): ``${age} >= 18 and (selected(${langs}, 'en') or ${x} != '')``
* REDCap: ``[age] >= 18 and ([race(3)] = '1' or [region] <> "")``
* LimeSurvey ExpressionScript: ``age >= 18 && (country == "US" || !is_empty(region))``

They share one shape (literals, variables, comparison, and/or/not, function
calls), so one Pratt parser reads all of them; a :class:`Dialect` supplies
the token spellings. :func:`to_items` then turns a tree into display_logic
items, asking the importer (a ``Resolver``) what each variable is and how a
literal maps onto Potato's stored answer.

Trees are tuples:
``("and", [x, y])``, ``("or", [x, y])``, ``("not", x)``,
``("cmp", op, left, right)`` with op in = != > >= < <= contains notcontains
anyof allof, ``("empty", x)``, ``("notempty", x)``,
``("call", name, [args])``, ``("var", ref)``, ``("lit", value)``,
``("list", [values])``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .base import Untranslatable


@dataclass
class Dialect:
    name: str
    #: regex with one group: the variable reference
    variable: str
    #: bare identifiers are variables (LimeSurvey) rather than words/functions
    bare_identifiers_are_variables: bool = False
    #: word operators, lower-cased: word -> canonical
    words: Dict[str, str] = field(default_factory=dict)
    #: symbol operators: symbol -> canonical, longest first is handled
    symbols: Dict[str, str] = field(default_factory=dict)
    #: postfix word operators (SurveyJS ``empty`` / ``notempty``)
    postfix: Dict[str, str] = field(default_factory=dict)
    #: identifiers to read as literals: true/false/null
    constants: Dict[str, Any] = field(default_factory=dict)
    #: XPath's ``.`` (the current question) in constraints
    dot_is_self: bool = False
    #: backslash escapes inside string literals (XPath strings have none)
    string_escapes: bool = True
    #: identifiers (words, function names, bare variables)
    ident: str = r"[A-Za-z_][A-Za-z0-9_.:]*(?:\(\))?"


_SYMBOLS_COMMON = {
    "==": "=", "=": "=", "!=": "!=", "<>": "!=", ">=": ">=", "<=": "<=",
    ">": ">", "<": "<", "&&": "and", "||": "or", "!": "not",
    "(": "(", ")": ")", ",": ",", "[": "[", "]": "]",
    "+": "+", "-": "-", "*": "*", "/": "/",
}

SURVEYJS = Dialect(
    name="SurveyJS",
    variable=r"\{([^{}]+)\}",
    words={"and": "and", "or": "or", "not": "not", "contains": "contains",
           "notcontains": "notcontains", "anyof": "anyof", "allof": "allof",
           "equal": "=", "notequal": "!=", "greater": ">", "less": "<",
           "greaterorequal": ">=", "lessorequal": "<=", "noneof": "noneof"},
    symbols=dict(_SYMBOLS_COMMON),
    postfix={"empty": "empty", "notempty": "notempty"},
    constants={"true": True, "false": False, "null": None, "undefined": None},
)

XLSFORM = Dialect(
    name="XLSForm",
    variable=r"\$\{([^{}]+)\}",
    words={"and": "and", "or": "or", "div": "/", "mod": "%"},
    symbols={k: v for k, v in _SYMBOLS_COMMON.items() if k not in ("&&", "||", "!", "==")},
    constants={"true()": True, "false()": False},
    dot_is_self=True,
    string_escapes=False,
    # XPath function names have hyphens: count-selected(), string-length()
    ident=r"[A-Za-z_][A-Za-z0-9_.:\-]*(?:\(\))?",
)

REDCAP = Dialect(
    name="REDCap",
    variable=r"\[([^\[\]]+)\](?:\[([^\[\]]+)\])?",
    words={"and": "and", "or": "or", "not": "not"},
    symbols={k: v for k, v in _SYMBOLS_COMMON.items() if k not in ("[", "]")},
)

LIMESURVEY = Dialect(
    name="LimeSurvey",
    variable=r"\{([^{}]+)\}",
    bare_identifiers_are_variables=True,
    words={"and": "and", "or": "or", "not": "not", "eq": "=", "ne": "!=",
           "gt": ">", "ge": ">=", "lt": "<", "le": "<="},
    symbols=dict(_SYMBOLS_COMMON),
    constants={"true": True, "false": False, "null": None},
)


_TOKEN_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?![A-Za-z_])")
_STRING = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")


def tokenize(text: str, d: Dialect) -> List[Tuple[str, Any]]:
    tokens: List[Tuple[str, Any]] = []
    var_re = re.compile(d.variable)
    ident_re = re.compile(d.ident)
    symbols = sorted(d.symbols, key=len, reverse=True)
    i, n = 0, len(text)
    while i < n:
        m = _TOKEN_SPACE.match(text, i)
        if m:
            i = m.end()
            continue
        m = var_re.match(text, i)
        if m:
            ref = m.group(1).strip()
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                # REDCap [event][field]: keep the field, flag the event
                tokens.append(("var", f"{m.group(2).strip()}@{ref}"))
            else:
                tokens.append(("var", ref))
            i = m.end()
            continue
        m = _STRING.match(text, i)
        if m:
            raw = m.group(1) if m.group(1) is not None else m.group(2)
            tokens.append(("lit", re.sub(r"\\(.)", r"\1", raw) if d.string_escapes else raw))
            i = m.end()
            continue
        prev = tokens[-1] if tokens else None
        m = _NUMBER.match(text, i)
        if m and not (m.group(0).startswith("-") and prev and prev[0] in ("lit", "var", ")")):
            v = m.group(0)
            tokens.append(("lit", float(v) if "." in v else int(v)))
            i = m.end()
            continue
        if d.dot_is_self and text[i] == "." and not text[i + 1:i + 2].isalnum():
            tokens.append(("var", "."))
            i += 1
            continue
        sym = next((s for s in symbols if text.startswith(s, i)), None)
        m = ident_re.match(text, i)
        if m and (sym is None or len(m.group(0)) >= len(sym)):
            word = m.group(0)
            low = word.lower()
            if low in d.constants:
                tokens.append(("lit", d.constants[low]))
            elif low in d.words:
                tokens.append(("op", d.words[low]))
            elif low in d.postfix:
                tokens.append(("postfix", d.postfix[low]))
            elif not word.endswith("()") and text[m.end():].lstrip().startswith("("):
                tokens.append(("func", word))
            elif word.endswith("()"):
                tokens.append(("func", word[:-2]))
                tokens.append(("op", "("))
                tokens.append(("op", ")"))
            elif d.bare_identifiers_are_variables:
                tokens.append(("var", word))
            else:
                raise Untranslatable(f"unknown word {word!r} in {d.name} expression")
            i = m.end()
            continue
        if sym:
            tokens.append(("op", d.symbols[sym]))
            i += len(sym)
            continue
        raise Untranslatable(f"unexpected character {text[i]!r} in {d.name} expression")
    return tokens


_BINDING = {"or": 1, "and": 2, "=": 4, "!=": 4, ">": 4, ">=": 4, "<": 4, "<=": 4,
            "contains": 4, "notcontains": 4, "anyof": 4, "allof": 4, "noneof": 4,
            "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("end", None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, kind, value=None):
        tok = self.take()
        if tok[0] != kind or (value is not None and tok[1] != value):
            raise Untranslatable(f"expected {value or kind}, found {tok[1]!r}")
        return tok

    def parse(self):
        node = self.expr(0)
        if self.peek()[0] != "end":
            raise Untranslatable(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self, rbp):
        left = self.prefix()
        while True:
            kind, val = self.peek()
            if kind == "postfix":
                self.take()
                left = (val, left)
                continue
            if kind != "op" or val not in _BINDING or _BINDING[val] <= rbp:
                break
            self.take()
            right = self.expr(_BINDING[val])
            if val in ("and", "or"):
                parts = []
                for side in (left, right):
                    parts.extend(side[1] if side[0] == val else [side])
                left = (val, parts)
            elif val in ("+", "-", "*", "/", "%"):
                left = ("arith", val, left, right)
            else:
                left = ("cmp", val, left, right)
        return left

    def prefix(self):
        kind, val = self.take()
        if kind == "lit":
            return ("lit", val)
        if kind == "var":
            return ("var", val)
        if kind == "op" and val == "not":
            return ("not", self.expr(3))
        if kind == "op" and val == "-":
            inner = self.expr(7)
            if inner[0] == "lit" and isinstance(inner[1], (int, float)):
                return ("lit", -inner[1])
            return ("arith", "-", ("lit", 0), inner)
        if kind == "op" and val == "(":
            node = self.expr(0)
            self.expect("op", ")")
            return node
        if kind == "op" and val == "[":
            items = []
            if self.peek() != ("op", "]"):
                while True:
                    item = self.expr(0)
                    if item[0] != "lit":
                        raise Untranslatable("a list may only hold literal values")
                    items.append(item[1])
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            self.expect("op", "]")
            return ("list", items)
        if kind == "func":
            self.expect("op", "(")
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    args.append(self.expr(0))
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            self.expect("op", ")")
            return ("call", val, args)
        raise Untranslatable(f"unexpected {val!r}")


def parse(text: str, dialect: Dialect):
    if not isinstance(text, str) or not text.strip():
        raise Untranslatable("empty expression")
    return _Parser(tokenize(text, dialect)).parse()


# --------------------------------------------------------------------------
# Tree -> display_logic items
# --------------------------------------------------------------------------

@dataclass
class VarInfo:
    """What a variable reference is, as the importer knows it."""
    schema: str                          # Potato question name, or condition.<factor>
    kind: str = "single"                 # single | multi | number | text | count
    #: source value -> Potato stored value (label text) for choice questions
    values: Dict[str, str] = field(default_factory=dict)
    #: a fixed choice the reference itself names (REDCap [q(3)], matrix row)
    choice: Optional[str] = None


#: resolver(ref) -> VarInfo, or raise Untranslatable
Resolver = Callable[[str], VarInfo]
#: call_handler(name, args, resolver, cmp) -> item, or None to refuse.
#: ``cmp`` is ``(op, right_node)`` when the call is the left side of a
#: comparison (``count-selected(${q}) > 1``), else None.
CallHandler = Callable[[str, list, Resolver, Optional[tuple]], Optional[Dict[str, Any]]]

_FLIP = {"=": "=", "!=": "!=", ">": "<", "<": ">", ">=": "<=", "<=": ">="}
_OPS = {"=": "equals", "!=": "not_equals", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}


def _map_value(info: VarInfo, value: Any) -> Any:
    if value is None:
        return None
    if info.values:
        key = str(value)
        if key in info.values:
            return info.values[key]
        # Booleans written as true/false against Yes/No choices
        if isinstance(value, bool) and str(value).lower() in info.values:
            return info.values[str(value).lower()]
        raise Untranslatable(f"{value!r} is not one of the choices of {info.schema}")
    return value


def _leaf(info: VarInfo, op: str, value: Any) -> Dict[str, Any]:
    return {"schema": info.schema, "operator": op, "value": value}


def compare(info: VarInfo, op: str, value: Any) -> Dict[str, Any]:
    """One comparison of a variable with a literal."""
    if info.kind == "count":
        # The number of options selected ({q.length}, count-selected(${q})).
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise Untranslatable(f"a selection count compared with {value!r}")
        table = {">": ("count_gt", n), ">=": ("count_gt", n - 1), "<": ("count_lt", n),
                 "<=": ("count_lt", n + 1), "=": ("count_equals", n)}
        if op == "!=":
            return {"not": _leaf(info, "count_equals", n)}
        if op not in table:
            raise Untranslatable(f"{op} on a selection count")
        operator, n = table[op]
        return _leaf(info, operator, n)
    if info.choice is not None:
        # The reference names one choice of a multi-select ([q(3)], {q.row}):
        # a test of 1/true is "selected", of 0/false/empty "not selected".
        # LimeSurvey stores a ticked box as "Y".
        truthy = str(value).strip().lower() in ("1", "true", "yes", "y", "checked")
        if op not in ("=", "!="):
            raise Untranslatable(f"{op} on a single choice of {info.schema}")
        selected = truthy if op == "=" else not truthy
        return _leaf(info, "contains" if selected else "not_contains", info.choice)
    if value in (None, "") and op in ("=", "!="):
        return {"schema": info.schema, "operator": "empty" if op == "=" else "not_empty"}
    if op in ("contains", "notcontains"):
        mapped = _map_value(info, value) if info.kind in ("single", "multi") else value
        return _leaf(info, "contains" if op == "contains" else "not_contains", mapped)
    if op in (">", ">=", "<", "<="):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            try:
                value = float(value)
                value = int(value) if value.is_integer() else value
            except (TypeError, ValueError):
                raise Untranslatable(f"{op} with a non-number {value!r}")
        if info.values:
            # Numeric codes compared on a choice question: only safe when the
            # stored labels are themselves numbers.
            key = _num_key(info, value)
            if key in info.values and _is_number(info.values[key]):
                value = float(info.values[key])
                value = int(value) if value.is_integer() else value
            elif not all(_is_number(v) for v in info.values.values()):
                raise Untranslatable(f"numeric {op} on the text choices of {info.schema}")
        return _leaf(info, _OPS[op], value)
    mapped = _map_value(info, value)
    if info.kind == "multi" and op in ("=", "!="):
        # q = 'a' on a multi-select means "exactly a" in most tools; Potato can
        # express "a selected and nothing else" with count_equals.
        group = {"all": [_leaf(info, "contains", mapped),
                         {"schema": info.schema, "operator": "count_equals", "value": 1}]}
        return group if op == "=" else {"not": group}
    return _leaf(info, _OPS[op], mapped)


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _num_key(info: VarInfo, value) -> str:
    for k in info.values:
        if _is_number(k) and float(k) == float(value):
            return k
    return str(value)


def to_items(node, resolve: Resolver, call: Optional[CallHandler] = None) -> List[Dict[str, Any]]:
    """Top-level items for ``show_when`` and the outer ``logic``."""
    item = to_item(node, resolve, call)
    return [item]


def to_rule(node, resolve: Resolver, call: Optional[CallHandler] = None) -> Dict[str, Any]:
    """A whole display_logic rule ({show_when, logic})."""
    if node[0] in ("and", "or"):
        items = [to_item(n, resolve, call) for n in node[1]]
        return {"show_when": items, "logic": "all" if node[0] == "and" else "any"}
    return {"show_when": [to_item(node, resolve, call)], "logic": "all"}


def to_item(node, resolve: Resolver, call: Optional[CallHandler] = None) -> Dict[str, Any]:
    kind = node[0]
    if kind in ("and", "or"):
        return {"all" if kind == "and" else "any": [to_item(n, resolve, call) for n in node[1]]}
    if kind == "not":
        return {"not": to_item(node[1], resolve, call)}
    if kind in ("empty", "notempty"):
        if node[1][0] != "var":
            raise Untranslatable(f"{kind} on something other than a question")
        info = resolve(node[1][1])
        if info.choice is not None:
            return _leaf(info, "not_contains" if kind == "empty" else "contains", info.choice)
        return {"schema": info.schema, "operator": "empty" if kind == "empty" else "not_empty"}
    if kind == "cmp":
        op, left, right = node[1], node[2], node[3]
        if left[0] != "var" and right[0] == "var":
            if op not in _FLIP:
                raise Untranslatable(f"{op} with the question on the right")
            op, left, right = _FLIP[op], right, left
        if left[0] == "call" and call is not None:
            item = call(left[1], left[2], resolve, (op, right))
            if item is not None:
                return item
        if left[0] != "var":
            raise Untranslatable("a comparison that does not test a question")
        info = resolve(left[1])
        if op in ("anyof", "allof", "noneof"):
            if right[0] != "list":
                raise Untranslatable(f"{op} needs a list")
            values = [_map_value(info, v) for v in right[1]]
            if op == "anyof":
                return _leaf(info, "contains", values) if info.kind == "multi" else _leaf(info, "equals", values)
            if op == "noneof":
                return _leaf(info, "not_contains", values) if info.kind == "multi" else _leaf(info, "not_equals", values)
            return {"all": [_leaf(info, "contains", v) for v in values]}
        if right[0] == "var":
            raise Untranslatable("a comparison between two questions")
        if right[0] == "list":
            if op in ("=", "!=") and info.kind == "multi":
                values = [_map_value(info, v) for v in right[1]]
                group = {"all": [_leaf(info, "contains", v) for v in values] +
                         [{"schema": info.schema, "operator": "count_equals", "value": len(values)}]}
                return group if op == "=" else {"not": group}
            raise Untranslatable(f"{op} against a list")
        if right[0] != "lit":
            raise Untranslatable("a comparison with a computed value")
        return compare(info, op, right[1])
    if kind == "call" and call is not None:
        item = call(node[1], node[2], resolve, None)
        if item is not None:
            return item
        raise Untranslatable(f"function {node[1]}()")
    if kind == "var":
        # A bare question as a condition: "answered" (and, for yes/no, "yes")
        info = resolve(node[1])
        if info.choice is not None:
            return _leaf(info, "contains", info.choice)
        return {"schema": info.schema, "operator": "not_empty"}
    if kind == "lit":
        raise Untranslatable(f"a constant condition ({node[1]!r})")
    if kind == "call":
        raise Untranslatable(f"function {node[1]}()")
    raise Untranslatable(f"{kind} expression")


def unparse(node) -> str:
    """Readable form of a tree, for reports."""
    kind = node[0]
    if kind in ("and", "or"):
        return "(" + f" {kind} ".join(unparse(n) for n in node[1]) + ")"
    if kind == "not":
        return f"not {unparse(node[1])}"
    if kind in ("empty", "notempty"):
        return f"{unparse(node[1])} {kind}"
    if kind == "cmp" or kind == "arith":
        return f"{unparse(node[2])} {node[1]} {unparse(node[3])}"
    if kind == "call":
        return f"{node[1]}(" + ", ".join(unparse(a) for a in node[2]) + ")"
    if kind == "var":
        return "{" + str(node[1]) + "}"
    if kind == "list":
        return repr(node[1])
    return repr(node[1])
