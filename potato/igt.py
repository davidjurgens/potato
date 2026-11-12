"""
Interlinear glossed text (IGT): the alignment rules the ``interlinear_gloss``
scheme, its importers and its exporters share.

An analysed word has two editable lines. The segmentation line splits the word
into morphemes with ``-`` (affix boundary) and ``=`` (clitic boundary); the
gloss line has one gloss per morpheme, separated the same way. The Leipzig
Glossing Rules (Comrie, Haspelmath & Bickel) require the two lines to have the
same boundaries in the same order (their rule 2). Inside one gloss, ``.`` joins
several meta-language elements that belong to one morpheme (rule 4), and
grammatical category labels are written in capitals and printed in small caps.

``static/interlinear-gloss.js`` implements the same checks for the page;
``tests/unit/test_interlinear_gloss.py`` runs both on the same cases.

A stored answer is one JSON object::

    {"words": [{"word": "evlerde", "morphemes": "ev-ler-de",
                "gloss": "house-PL-LOC", "pos": "n"}, ...],
     "translation": "in the houses"}

Extra tiers configured on the scheme (``tiers: [pos, notes]``) are extra keys
on each word.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: The standard abbreviations listed in the appendix of the Leipzig Glossing
#: Rules, with a short meaning for each (our wording). ``N`` doubles as the
#: "non-" prefix (NSG, NPST), which ``unknown_labels`` handles.
LEIPZIG_ABBREVIATIONS: Dict[str, str] = {
    "1": "first person",
    "2": "second person",
    "3": "third person",
    "A": "agent-like argument of a transitive verb",
    "ABL": "ablative",
    "ABS": "absolutive",
    "ACC": "accusative",
    "ADJ": "adjective",
    "ADV": "adverb(ial)",
    "AGR": "agreement",
    "ALL": "allative",
    "ANTIP": "antipassive",
    "APPL": "applicative",
    "ART": "article",
    "AUX": "auxiliary",
    "BEN": "benefactive",
    "CAUS": "causative",
    "CLF": "classifier",
    "COM": "comitative",
    "COMP": "complementizer",
    "COMPL": "completive",
    "COND": "conditional",
    "COP": "copula",
    "CVB": "converb",
    "DAT": "dative",
    "DECL": "declarative",
    "DEF": "definite",
    "DEM": "demonstrative",
    "DET": "determiner",
    "DIST": "distal",
    "DISTR": "distributive",
    "DU": "dual",
    "DUR": "durative",
    "ERG": "ergative",
    "EXCL": "exclusive",
    "F": "feminine",
    "FOC": "focus",
    "FUT": "future",
    "GEN": "genitive",
    "IMP": "imperative",
    "INCL": "inclusive",
    "IND": "indicative",
    "INDF": "indefinite",
    "INF": "infinitive",
    "INS": "instrumental",
    "INTR": "intransitive",
    "IPFV": "imperfective",
    "IRR": "irrealis",
    "LOC": "locative",
    "M": "masculine",
    "N": "neuter; also the prefix non- (NSG, NPST)",
    "NEG": "negation, negative",
    "NMLZ": "nominalizer, nominalization",
    "NOM": "nominative",
    "OBJ": "object",
    "OBL": "oblique",
    "P": "patient-like argument of a transitive verb",
    "PASS": "passive",
    "PFV": "perfective",
    "PL": "plural",
    "POSS": "possessive",
    "PRED": "predicative",
    "PRF": "perfect",
    "PRS": "present",
    "PROG": "progressive",
    "PROH": "prohibitive",
    "PROX": "proximal, proximate",
    "PST": "past",
    "PTCP": "participle",
    "PURP": "purposive",
    "Q": "question particle or marker",
    "QUOT": "quotative",
    "RECP": "reciprocal",
    "REFL": "reflexive",
    "REL": "relative",
    "RES": "resultative",
    "S": "single argument of an intransitive verb",
    "SBJ": "subject",
    "SBJV": "subjunctive",
    "SG": "singular",
    "TOP": "topic",
    "TR": "transitive",
    "VOC": "vocative",
}

#: Morpheme boundaries that must match between the two lines.
BOUNDARIES = ("-", "=")
_SPLIT = re.compile(r"([-=])")
_INFIX = re.compile(r"<([^<>]*)>")
#: What separates meta-language elements inside one gloss: "." (rule 4), ":"
#: and ";" (rule 4 variants), "_" (multi-word glosses), "\" (morphophonological
#: change), the brackets of rules 6 and 7, and the morpheme boundaries.
_ELEMENT = re.compile(r"[^.:;_\\()\[\]\s<>=\-]+")
_CATEGORY = re.compile(r"[0-9A-ZØ]+")
_PERSON = re.compile(r"([123]+)([0-9A-Z]*)")
#: Characters stripped from the edges of a word when a sentence is split.
_EDGE_PUNCT = ".,;:!?\"'“”‘’«»()[]{}¿¡…–—"

#: Keys a word record always has; configured tiers are added to these.
WORD_KEYS = ("word", "morphemes", "gloss")


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def tokenize_sentence(text: str) -> List[str]:
    """A sentence split into words on whitespace, edge punctuation removed.

    Hyphens and ``=`` inside a word are kept, so an already segmented sentence
    survives. A token that is only punctuation or dashes is dropped.
    """
    out = []
    for token in str(text or "").split():
        word = token.strip(_EDGE_PUNCT)
        if word.strip("-=–—"):
            out.append(word)
    return out


def split_cell(text: str) -> Tuple[List[str], List[str], int]:
    """One cell as (pieces, boundaries, infixes).

    ``ev-ler=de`` -> (["ev", "ler", "de"], ["-", "="], 0). Infixes in angle
    brackets (rule 9: ``s<um>ulat``) are counted separately and left out of the
    pieces: the infix's gloss sits beside the stem's gloss rather than inside
    it, so their positions do not line up.
    """
    text = str(text or "").strip()
    infixes = len(_INFIX.findall(text))
    flat = _INFIX.sub("", text)
    parts = _SPLIT.split(flat)
    pieces = parts[0::2]
    boundaries = parts[1::2]
    return pieces, boundaries, infixes


def _describe(boundaries: Sequence[str], infixes: int) -> str:
    n = len(boundaries) + 2 * infixes
    if not n:
        return "no boundaries"
    kinds = " ".join(boundaries) + (" " if boundaries and infixes else "") + \
        " ".join(["<>"] * infixes)
    return f"{n} boundar{'y' if n == 1 else 'ies'} ({kinds})"


def check_word(morphemes: str, gloss: str) -> Dict[str, Any]:
    """Check one word's segmentation against its gloss.

    Returns ``{"status", "messages"}``. Status is one of:

    * ``ok``          both lines filled and aligned
    * ``empty``       neither line filled
    * ``incomplete``  one line filled and the other not
    * ``misaligned``  the boundaries differ, a morpheme or gloss is empty, or a
                      cell holds a space
    """
    m = str(morphemes or "").strip()
    g = str(gloss or "").strip()
    if not m and not g:
        return {"status": "empty", "messages": []}
    if not g:
        return {"status": "incomplete", "messages": ["no gloss yet"]}
    if not m:
        return {"status": "incomplete", "messages": ["no segmentation yet"]}
    messages = []
    if re.search(r"\s", m):
        messages.append("the segmentation holds a space: join morphemes with - or =")
    if re.search(r"\s", g):
        messages.append("the gloss holds a space: join the words of one gloss with . (rule 4)")
    m_pieces, m_bounds, m_infix = split_cell(m)
    g_pieces, g_bounds, g_infix = split_cell(g)
    if m_bounds != g_bounds or m_infix != g_infix:
        messages.append(f"segmentation has {_describe(m_bounds, m_infix)}, "
                        f"gloss has {_describe(g_bounds, g_infix)}")
    else:
        empty_m = [i + 1 for i, p in enumerate(m_pieces) if not p.strip()]
        empty_g = [i + 1 for i, p in enumerate(g_pieces) if not p.strip()]
        if empty_m:
            messages.append("empty morpheme at position " + ", ".join(map(str, empty_m)))
        if empty_g:
            messages.append("no gloss for morpheme " + ", ".join(map(str, empty_g)))
    return {"status": "misaligned" if messages else "ok", "messages": messages}


# ---------------------------------------------------------------------------
# Category labels and abbreviations
# ---------------------------------------------------------------------------

def gloss_elements(gloss: str) -> List[str]:
    """The meta-language elements of a gloss line, in order."""
    return _ELEMENT.findall(str(gloss or ""))


def is_category(element: str) -> bool:
    """A grammatical category label: capitals and person digits, no lowercase."""
    if element in ("1", "2", "3"):
        return True
    if element.isdigit():
        return False
    return bool(_CATEGORY.fullmatch(element))


def resolve_abbreviations(spec: Any) -> Optional[Dict[str, str]]:
    """The known category labels for a scheme's ``abbreviations`` setting.

    * absent / None / false  no checking (returns None)
    * ``leipzig`` or true    the standard Leipzig list
    * a list                 those labels; the entry ``leipzig`` adds the
                             standard list
    * a mapping              label -> meaning; a ``leipzig`` key adds the list
    """
    if spec is None or spec is False:
        return None
    if spec is True or (isinstance(spec, str) and spec.strip().lower() == "leipzig"):
        return dict(LEIPZIG_ABBREVIATIONS)
    out: Dict[str, str] = {}
    if isinstance(spec, dict):
        items: Iterable[Tuple[Any, Any]] = spec.items()
    elif isinstance(spec, (list, tuple)):
        items = [(entry, "") for entry in spec]
    else:
        raise ValueError("abbreviations must be 'leipzig', a list of labels or a mapping")
    for label, meaning in items:
        label = str(label).strip()
        if label.lower() == "leipzig":
            for k, v in LEIPZIG_ABBREVIATIONS.items():
                out.setdefault(k, v)
            continue
        if label:
            out[label] = str(meaning or "")
    return out


def _known(element: str, known: Dict[str, str]) -> bool:
    if element in known or element == "Ø":
        return True
    person = _PERSON.fullmatch(element)
    if person:
        digits, rest = person.groups()
        if all(d in known for d in digits) and (not rest or _known(rest, known)):
            return True
    # Leipzig's "N-" (non-): NSG, NPST.
    if len(element) > 1 and element.startswith("N") and "N" in known:
        return _known(element[1:], known)
    # Person + number written together with a known number (3SG, 1PL) is
    # covered above; a label run together with another (PLLOC) is not.
    return False


def unknown_labels(gloss: str, known: Optional[Dict[str, str]]) -> List[str]:
    """Category labels in a gloss that are not in ``known``, in order, once each."""
    if known is None:
        return []
    out: List[str] = []
    for element in gloss_elements(gloss):
        if is_category(element) and not _known(element, known) and element not in out:
            out.append(element)
    return out


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ["" if v is None else str(v) for v in value]
    if isinstance(value, str):
        return value.split()
    return None


def source_words(item: Dict[str, Any], scheme: Dict[str, Any]) -> List[str]:
    """The words of one item: a list as given, or a sentence split on spaces."""
    value = (item or {}).get(scheme.get("source_field") or "text")
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return tokenize_sentence(value if isinstance(value, str) else "")


def initial_answer(item: Dict[str, Any], scheme: Dict[str, Any]) -> Dict[str, Any]:
    """The answer the page starts from: the item's words plus any pre-filled analysis.

    A segmentation with no pre-fill starts as the word itself, so the annotator
    only has to type the boundaries. ``interlinear-gloss.js`` builds the same
    record (``initialAnswer``).
    """
    item = item or {}
    words = source_words(item, scheme)
    morphs = _as_list(item.get(scheme["morphemes_field"])) if scheme.get("morphemes_field") else None
    glosses = _as_list(item.get(scheme["gloss_field"])) if scheme.get("gloss_field") else None
    tiers = list(scheme.get("tiers") or [])
    tier_values = {t: _as_list(item.get(t)) if isinstance(item.get(t), list) else None for t in tiers}
    records = []
    for i, word in enumerate(words):
        rec = {"word": word,
               "morphemes": morphs[i] if morphs and i < len(morphs) else word,
               "gloss": glosses[i] if glosses and i < len(glosses) else ""}
        for t in tiers:
            vals = tier_values.get(t)
            rec[t] = vals[i] if vals and i < len(vals) else ""
        records.append(rec)
    translation = ""
    if scheme.get("translation_field"):
        translation = str(item.get(scheme["translation_field"]) or "")
    return {"words": records, "translation": translation}


def decode_answer(raw: Any) -> Optional[Dict[str, Any]]:
    """A stored answer from whatever the export pipeline holds, or None."""
    if isinstance(raw, dict) and "words" not in raw and len(raw) == 1:
        raw = next(iter(raw.values()))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or not isinstance(raw.get("words"), list):
        return None
    words = []
    for w in raw["words"]:
        if isinstance(w, dict):
            words.append({k: "" if v is None else str(v) for k, v in w.items()})
    return {"words": words, "translation": str(raw.get("translation") or "")}


def check_answer(answer: Dict[str, Any], known: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """``check_word`` for every word, plus the unknown labels of each."""
    out = []
    for w in (answer or {}).get("words") or []:
        result = check_word(w.get("morphemes", ""), w.get("gloss", ""))
        result["unknown"] = unknown_labels(w.get("gloss", ""), known)
        out.append(result)
    return out


# ---------------------------------------------------------------------------
# Morpheme types, for the formats that record them
# ---------------------------------------------------------------------------

def morpheme_breakdown(morphemes: str, gloss: str) -> List[Dict[str, str]]:
    """One word as a list of ``{"form", "gloss", "type", "before", "after"}``.

    ``before`` / ``after`` are the boundary symbols on each side. The stem is
    the first morpheme whose gloss has a lowercase letter (a lexical gloss);
    morphemes before it are prefixes or proclitics and those after it suffixes
    or enclitics, by their boundary. Without a lexical gloss the first morpheme
    is taken as the stem.
    """
    pieces, bounds, _ = split_cell(morphemes)
    g_pieces, g_bounds, _ = split_cell(gloss)
    if g_bounds != bounds:
        # Misaligned: the whole gloss goes on the first morpheme, so nothing
        # the annotator wrote is lost in a format that pairs them one to one.
        g_pieces = [str(gloss or "").strip()] + [""] * (len(pieces) - 1)
    stem = next((i for i, g in enumerate(g_pieces[:len(pieces)]) if re.search(r"[a-z]", g)), 0)
    out = []
    for i, form in enumerate(pieces):
        before = bounds[i - 1] if i > 0 else ""
        after = bounds[i] if i < len(bounds) else ""
        if i == stem:
            kind = "stem"
        elif i < stem:
            kind = "proclitic" if after == "=" else "prefix"
        else:
            kind = "enclitic" if before == "=" else "suffix"
        out.append({"form": form, "gloss": g_pieces[i] if i < len(g_pieces) else "",
                    "type": kind, "before": before, "after": after})
    return out


def marked_form(morph: Dict[str, str]) -> str:
    """A morpheme with its boundary written on the side away from the stem.

    ``-ler`` for a suffix, ``un-`` for a prefix, ``=de`` for an enclitic, as
    FLEx and Toolbox write affix forms.
    """
    kind = morph["type"]
    if kind in ("suffix", "enclitic"):
        return morph["before"] + morph["form"]
    if kind in ("prefix", "proclitic"):
        return morph["form"] + morph["after"]
    return morph["form"]


def join_marked(forms: Sequence[str], types: Optional[Sequence[str]] = None) -> str:
    """Morphemes written with their own boundary markers, joined into one cell.

    ``["ev", "-ler", "=de"]`` -> ``ev-ler=de``. The boundary between two
    morphemes is the one either side marks, ``=`` winning; with no mark it is
    ``-``, or ``=`` when ``types`` says one side is a clitic.
    """
    out = ""
    prev_after = ""
    for i, form in enumerate(forms):
        form = str(form or "").strip()
        lead = form[0] if form[:1] in BOUNDARIES else ""
        trail = form[-1] if len(form) > 1 and form[-1:] in BOUNDARIES else ""
        core = form.strip("-=")
        if i > 0:
            marks = {prev_after, lead} - {""}
            if "=" in marks:
                sep = "="
            elif marks:
                sep = "-"
            elif types and ("clitic" in (types[i] or "") or "clitic" in (types[i - 1] or "")):
                sep = "="
            else:
                sep = "-"
            out += sep
        out += core
        prev_after = trail
    return out


# ---------------------------------------------------------------------------
# Plain-text rendering
# ---------------------------------------------------------------------------

def display_width(text: str) -> int:
    """Columns a string takes in a monospaced font: combining marks take none,
    wide East Asian characters two."""
    width = 0
    for ch in str(text):
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def aligned_lines(rows: Sequence[Sequence[str]], gap: int = 2) -> List[str]:
    """Rows of cells padded so every column starts at the same position."""
    if not rows:
        return []
    n = max(len(r) for r in rows)
    widths = [max(display_width(r[i]) if i < len(r) else 0 for r in rows) for i in range(n)]
    out = []
    for r in rows:
        cells = [pad(r[i] if i < len(r) else "", widths[i] + gap) for i in range(n)]
        out.append("".join(cells).rstrip())
    return out
