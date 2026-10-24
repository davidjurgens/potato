"""
FLExText and Toolbox files as an interlinear glossing project.

Both formats hold texts already analysed into words, morphemes and glosses.
The importers turn every sentence (a FLEx *phrase*, a Toolbox *record*) into
one item and write its existing analysis into the item's own fields, which an
``interlinear_gloss`` scheme reads as its starting point. Annotators open each
sentence with the analysis filled in and correct it; nothing is stored as a
person's answer until they save. The ``flextext`` and ``toolbox`` exporters
write the corrected glosses back out.

Item fields written::

    text          the sentence as one string (shown as the item text)
    words         list of words
    morphemes     list, one segmentation per word ("ev-ler-de")
    glosses       list, one gloss per word ("house-PL-LOC")
    translation   free translation
    pos           list, one part of speech per word (when the source has one)
    source_file, text_title, paragraph, phrase, language, metalanguage

FLExText
    The XML written by FieldWorks' interlinear export (FlexInterlinear.xsd):
    ``document > interlinear-text > paragraphs > paragraph > phrases > phrase
    > words > word > morphemes > morph``, each level carrying
    ``<item type=... lang=...>`` children. Read: word ``txt`` / ``punct``,
    morph ``txt`` / ``cf`` / ``gls`` / ``msa`` and the ``type`` attribute,
    word ``gls`` / ``pos``, phrase ``gls`` (free translation) and ``segnum``.

Toolbox / Shoebox
    Standard format: backslash markers at the start of a line, records
    starting at ``\\ref``. Interlinear lines are aligned by column: a morpheme
    belongs to the word it sits under, a gloss to the morpheme it sits under.
    Projects name their markers differently, so every marker can be set in
    ``options["markers"]`` (see ``DEFAULT_MARKERS``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.igt import join_marked

from .base import ProjectImportResult, ProjectItem
from .textgrid import _read_text

try:  # untrusted XML: refuse entity expansion when defusedxml is installed
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - expat >= 2.4.1 limits expansion itself
    from xml.etree.ElementTree import fromstring as _xml_fromstring

SCHEME_NAME = "igt"


def _not_text(path: Path) -> str:
    """Why a file is not an XML text file, or "" if it may be one."""
    head = path.read_bytes()[:4096]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ""                                   # UTF-16 with a BOM
    if b"\x00" in head:
        return "is binary, not text"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(head) - 4:               # not just a character cut at 4096
            return f"is not UTF-8 text (byte 0x{head[exc.start]:02x} at offset {exc.start})"
    return ""


def _xml_problem(exc: Exception) -> str:
    """A readable reason an XML file was refused."""
    name = type(exc).__name__
    if name in ("EntitiesForbidden", "DTDForbidden", "ExternalReferenceForbidden"):
        return "defines XML entities or a DTD, which are refused in uploaded files"
    if "amplification" in str(exc):
        return f"its XML entities expand too far, which is refused ({exc})"
    return f"not well-formed XML ({exc})"

#: Toolbox markers, by role. A role may list several spellings; the first one a
#: record uses wins. ``options["markers"]`` replaces any of them (a string or a
#: list), e.g. ``{"text": "t", "gloss": ["g", "gle"]}``.
DEFAULT_MARKERS: Dict[str, List[str]] = {
    "record": ["ref"],
    "text": ["tx", "t"],
    "morphemes": ["mb", "m"],
    "gloss": ["ge", "g"],
    "pos": ["ps", "p"],
    "translation": ["ft", "f"],
}


def _scheme(source: str, has_pos: bool, language: str = "", metalanguage: str = "") -> dict:
    scheme = {
        "annotation_type": "interlinear_gloss",
        "name": SCHEME_NAME,
        "description": f"Check and correct the glosses imported from {source}.",
        "source_field": "words",
        "morphemes_field": "morphemes",
        "gloss_field": "glosses",
        "translation_field": "translation",
        "abbreviations": "leipzig",
    }
    if has_pos:
        scheme["tiers"] = ["pos"]
    if language:
        scheme["language"] = language
    if metalanguage:
        scheme["metalanguage"] = metalanguage
    return scheme


def _safe_id(raw: str, fallback: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(raw or "").strip()).strip("_.")
    return ident or fallback


def _unique(ident: str, seen: set) -> str:
    out, n = ident, 2
    while out in seen:
        out = f"{ident}_{n}"
        n += 1
    seen.add(out)
    return out


def _no_spaces(gloss: str) -> str:
    """Join the words of one gloss with "." (Leipzig rule 4)."""
    return re.sub(r"\s+", ".", str(gloss or "").strip())


# ---------------------------------------------------------------------------
# FLExText
# ---------------------------------------------------------------------------

def _items(node, kind: str) -> List[Tuple[str, str]]:
    """(lang, text) of the direct ``<item type=kind>`` children."""
    return [(i.get("lang", ""), (i.text or "").strip())
            for i in node.findall("item") if i.get("type") == kind]


def _first(node, kind: str, lang: Optional[str] = None) -> str:
    values = _items(node, kind)
    for item_lang, text in values:
        if lang is None or item_lang == lang:
            return text
    return values[0][1] if values else ""


class FlexTextImporter:
    format_name = "flextext"
    description = "FieldWorks (FLEx) interlinear texts, .flextext"
    file_extensions = [".flextext"]

    def _files(self, path: Path) -> List[Path]:
        if path.is_dir():
            return sorted(p for p in path.iterdir() if p.suffix.lower() == ".flextext")
        return [path] if path.suffix.lower() in (".flextext", ".xml") else []

    def _looks_like(self, text: str) -> bool:
        head = text.lstrip()[:4000]
        return head.startswith("<") and "<interlinear-text" in head

    def detect_path(self, path: Path) -> bool:
        files = self._files(Path(path))
        if not files:
            return False
        try:
            return self._looks_like(_read_text(files[0]))
        except OSError:
            return False

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no .flextext files at {path}")
        result = ProjectImportResult(source_format=self.description, text_key="text")
        seen: set = set()
        langs = {"vern": "", "analysis": ""}
        has_pos = False
        for f in files:
            problem = _not_text(f)
            if problem:
                result.warn(f"{f.name} {problem}; left out")
                result.skipped["unreadable files"] += 1
                continue
            text = _read_text(f).lstrip()
            if not self._looks_like(text):
                result.warn(f"{f.name} is not a FLExText file (no <interlinear-text> near the "
                            "start); left out")
                result.skipped["unreadable files"] += 1
                continue
            try:
                root = _xml_fromstring(text.encode("utf-8"))
            except Exception as exc:  # ParseError, or defusedxml's refusals
                result.warn(f"{f.name}: {_xml_problem(exc)}; left out")
                result.skipped["unreadable files"] += 1
                continue
            texts = [root] if root.tag == "interlinear-text" else root.findall("interlinear-text")
            for t_index, itext in enumerate(texts, start=1):
                title = _first(itext, "title") or (f.stem if len(texts) == 1 else f"{f.stem} {t_index}")
                for lang in itext.findall("languages/language"):
                    if lang.get("vernacular") == "true" and not langs["vern"]:
                        langs["vern"] = lang.get("lang", "")
                    elif lang.get("vernacular") != "true" and not langs["analysis"]:
                        langs["analysis"] = lang.get("lang", "")
                p_index = 0
                for para in itext.findall("paragraphs/paragraph"):
                    p_index += 1
                    for ph_index, phrase in enumerate(para.findall("phrases/phrase"), start=1):
                        item, pos_seen = self._phrase(phrase, f, title, p_index, ph_index, seen, result)
                        if item is not None:
                            has_pos = has_pos or pos_seen
                            result.items.append(item)
        if not result.items:
            why = f": {'; '.join(result.warnings)}" if result.warnings else ""
            raise ValueError(f"no phrases with words in the FLExText at {path}{why}")
        for item in result.items:
            item.fields.setdefault("language", langs["vern"])
            item.fields.setdefault("metalanguage", langs["analysis"])
            if not has_pos:
                item.fields.pop("pos", None)
        result.schemes = [_scheme("FLEx", has_pos, langs["vern"], langs["analysis"])]
        return result

    def _phrase(self, phrase, f: Path, title: str, p_index: int, ph_index: int,
                seen: set, result: ProjectImportResult):
        words, morphs, glosses, pos, surface = [], [], [], [], []
        pos_seen = False
        for word in phrase.findall("words/word"):
            punct = _first(word, "punct")
            form = _first(word, "txt")
            if not form:
                if punct:
                    if surface:
                        surface[-1] += punct
                    else:
                        surface.append(punct)
                continue
            surface.append(form)
            forms, types, gls = [], [], []
            for morph in word.findall("morphemes/morph"):
                m_form = _first(morph, "txt") or _first(morph, "cf")
                forms.append(m_form)
                types.append(morph.get("type", ""))
                gls.append(_no_spaces(_first(morph, "gls")))
            if forms:
                segmentation = join_marked(forms, types)
                # The glosses take the boundaries the morphemes have.
                seps = re.findall(r"[-=]", segmentation)
                gloss = gls[0] + "".join(s + g for s, g in zip(seps, gls[1:]))
            else:
                segmentation = form
                gloss = _no_spaces(_first(word, "gls"))
            word_pos = _first(word, "pos")
            if not word_pos:
                msas = [_first(m, "msa") for m in word.findall("morphemes/morph")]
                word_pos = next((m for m, t in zip(msas, types) if m and t in ("stem", "root", "")), "")
            pos_seen = pos_seen or bool(word_pos)
            words.append(form)
            morphs.append(segmentation)
            glosses.append(gloss)
            pos.append(word_pos)
        if not words:
            result.skipped["phrases without words"] += 1
            return None, False
        segnum = _first(phrase, "segnum") or f"{p_index}.{ph_index}"
        ident = _unique(_safe_id(f"{f.stem}_{segnum}", f"{f.stem}_{p_index}_{ph_index}"), seen)
        fields: Dict[str, Any] = {
            "text": " ".join(surface),
            "words": words,
            "morphemes": morphs,
            "glosses": glosses,
            "translation": _first(phrase, "gls"),
            "pos": pos,
            "source_file": f.name,
            "text_title": title,
            "paragraph": p_index,
            "phrase": segnum,
        }
        item = ProjectItem(instance_id=ident, fields=fields)
        return item, pos_seen


# ---------------------------------------------------------------------------
# Toolbox / Shoebox standard format
# ---------------------------------------------------------------------------

_MARKER = re.compile(r"^\\([^\s\\]+)(?:[ \t]|$)")


def _markers(options: Optional[dict]) -> Dict[str, List[str]]:
    out = {role: list(names) for role, names in DEFAULT_MARKERS.items()}
    for role, names in ((options or {}).get("markers") or {}).items():
        if role not in out:
            raise ValueError(f"unknown Toolbox marker role {role!r}; "
                             f"roles are {', '.join(DEFAULT_MARKERS)}")
        names = [names] if isinstance(names, str) else list(names)
        out[role] = [str(n).lstrip("\\") for n in names if str(n).strip()]
    return out


def _tokens(line: str) -> List[Tuple[int, str]]:
    """(column, token) for each whitespace-separated token of an aligned line."""
    return [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]


def _owner(starts: Sequence[int], col: int) -> int:
    """Index of the column a token at ``col`` sits under."""
    owner = 0
    for i, s in enumerate(starts):
        if s <= col:
            owner = i
        else:
            break
    return owner


def parse_toolbox(text: str, options: Optional[dict] = None) -> List[Dict[str, Any]]:
    """Records of a Toolbox file, each ``{"ref", "words": [...], "translation", "extra"}``.

    Each word is ``{"word", "morphemes": [...marked forms], "glosses": [...],
    "pos": [...]}``, morphemes and glosses as they stand in the file.
    """
    markers = _markers(options)
    role_of = {}
    for role, names in markers.items():
        for name in names:
            role_of.setdefault(name, role)
    records: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    lines: List[Tuple[str, str]] = []   # (marker, full line) in order

    def flush():
        if current is not None:
            current["lines"] = list(lines)
            records.append(current)

    last_marker = None
    for raw in text.splitlines():
        line = raw.rstrip("\r\n").expandtabs(8)
        m = _MARKER.match(line)
        if m:
            marker = m.group(1)
            if role_of.get(marker) == "record":
                flush()
                current = {"ref": line[m.end():].strip()}
                lines = []
                last_marker = marker
                continue
            if current is None:
                last_marker = None
                continue   # header (\_sh, \id) before the first record
            lines.append((marker, line))
            last_marker = marker
        elif current is not None and line.strip() and last_marker and lines:
            # A continuation of the previous field (free translation, notes).
            marker, prev = lines[-1]
            if role_of.get(marker) in ("translation",) or marker not in role_of:
                lines[-1] = (marker, prev + " " + line.strip())
    flush()

    out = []
    for rec in records:
        out.append(_toolbox_record(rec, role_of))
    return out


def _toolbox_record(rec: Dict[str, Any], role_of: Dict[str, str]) -> Dict[str, Any]:
    words: List[Dict[str, Any]] = []
    translation_parts: List[str] = []
    extra: Dict[str, str] = {}
    bundle: Dict[str, str] = {}
    used: Dict[str, str] = {}

    def close_bundle():
        if "text" not in bundle:
            return
        words.extend(_toolbox_bundle(bundle))

    for marker, line in rec["lines"]:
        role = role_of.get(marker)
        if role in ("text", "morphemes", "gloss", "pos"):
            # Only the first spelling a record uses counts for a role, so a
            # file that happens to use both \g and \ge does not mix them.
            if used.setdefault(role, marker) != marker:
                extra[marker] = (extra.get(marker, "") + " " + line[len(marker) + 1:].strip()).strip()
                continue
            if role == "text":
                close_bundle()
                bundle = {}
            # Keep the line's own columns: blank out the marker, not strip it.
            bundle[role] = " " * (len(marker) + 1) + line[len(marker) + 1:]
        elif role == "translation":
            translation_parts.append(line[len(marker) + 1:].strip())
        else:
            value = line[len(marker) + 1:].strip()
            extra[marker] = (extra.get(marker, "") + "\n" + value).strip() if marker in extra else value
    close_bundle()
    return {"ref": rec["ref"], "words": words, "translation": " ".join(p for p in translation_parts if p),
            "extra": extra}


def _group_by_marks(tokens: Sequence[str]) -> List[List[int]]:
    """Morpheme tokens grouped into words by their own boundary marks.

    ``-ler`` and ``=de`` attach to the token before, ``un-`` to the token
    after; any other token starts a new word.
    """
    groups: List[List[int]] = []
    for i, tok in enumerate(tokens):
        joins_prev = tok[:1] in ("-", "=")
        prev_open = i > 0 and len(tokens[i - 1]) > 1 and tokens[i - 1][-1:] in ("-", "=")
        if groups and (joins_prev or prev_open):
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _toolbox_bundle(bundle: Dict[str, str]) -> List[Dict[str, Any]]:
    """The words of one interlinear bundle (a \\tx line and the lines under it).

    Toolbox aligns the lines by column, so a morpheme belongs to the word it
    sits under and a gloss to the morpheme it sits under. Files edited by hand
    are often not aligned, so two order-based readings come first when they
    fit: morphemes grouped into words by their - and = marks, when that gives
    one group per word, and glosses paired with morphemes in order, when there
    is one gloss per morpheme.
    """
    word_toks = _tokens(bundle["text"])
    word_starts = [c for c, _ in word_toks]
    words = [{"word": tok, "morphemes": [], "glosses": [], "pos": []} for _, tok in word_toks]
    if not words:
        return []
    morph_toks = _tokens(bundle.get("morphemes", ""))
    groups = _group_by_marks([tok for _, tok in morph_toks])
    if len(groups) == len(words):
        owners = [wi for wi, group in enumerate(groups) for _ in group]
    else:
        owners = [_owner(word_starts, col) for col, _ in morph_toks]
    slots: List[Tuple[int, int]] = []   # (word index, morpheme index) per token
    for (col, tok), wi in zip(morph_toks, owners):
        slots.append((wi, len(words[wi]["morphemes"])))
        words[wi]["morphemes"].append(tok)
    morph_cols = [col for col, _ in morph_toks]
    for role, key in (("gloss", "glosses"), ("pos", "pos")):
        toks = _tokens(bundle.get(role, ""))
        if not toks:
            continue
        if not morph_toks:
            # No morpheme line: the glosses sit under the words.
            for col, tok in toks:
                words[_owner(word_starts, col)][key].append(tok)
            continue
        for w in words:
            w[key] = [""] * len(w["morphemes"])
        if len(toks) == len(morph_toks):
            targets = slots
        else:
            targets = [slots[_owner(morph_cols, col)] for col, _ in toks]
        for (col, tok), (wi, mi) in zip(toks, targets):
            cell = words[wi][key]
            cell[mi] = f"{cell[mi]}.{tok}" if cell[mi] else tok
    return words


def _strip_marks(token: str) -> str:
    return str(token or "").strip("-=")


def toolbox_word_cells(word: Dict[str, Any]) -> Tuple[str, str, str]:
    """(segmentation, gloss, pos) cells for one parsed Toolbox word."""
    forms = word["morphemes"]
    if not forms:
        gloss = ".".join(_strip_marks(g) for g in word["glosses"] if g)
        pos = ".".join(_strip_marks(p) for p in word["pos"] if p)
        return word["word"], gloss, pos
    segmentation = join_marked(forms)
    seps = re.findall(r"[-=]", segmentation)

    def joined(values: List[str]) -> str:
        values = [_strip_marks(v) for v in values] + [""] * (len(forms) - len(values))
        if not any(values):
            return ""
        return values[0] + "".join(s + v for s, v in zip(seps, values[1:]))

    return segmentation, joined(word["glosses"]), joined(word["pos"])


class ToolboxImporter:
    format_name = "toolbox"
    description = "Toolbox / Shoebox interlinear text (standard format markers)"
    file_extensions = [".txt", ".sfm", ".db", ".tbx", ".toolbox"]

    def _files(self, path: Path) -> List[Path]:
        exts = tuple(self.file_extensions)
        if path.is_dir():
            return sorted(p for p in path.iterdir() if p.suffix.lower() in exts)
        return [path] if path.suffix.lower() in exts else []

    def _looks_like(self, text: str, options: Optional[dict] = None) -> bool:
        markers = _markers(options)
        found = set()
        for line in text.splitlines()[:400]:
            m = _MARKER.match(line)
            if m:
                found.add(m.group(1))
        has = lambda role: bool(found & set(markers[role]))  # noqa: E731
        return has("record") and has("text") and (has("morphemes") or has("gloss"))

    def detect_path(self, path: Path) -> bool:
        files = self._files(Path(path))
        if not files:
            return False
        try:
            return self._looks_like(_read_text(files[0]))
        except OSError:
            return False

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no Toolbox files ({', '.join(self.file_extensions)}) at {path}")
        result = ProjectImportResult(source_format=self.description, text_key="text")
        seen: set = set()
        has_pos = False
        for f in files:
            text = _read_text(f)
            if not self._looks_like(text, options):
                result.warn(f"{f.name} has no \\ref records with text and gloss lines; left out")
                result.skipped["unreadable files"] += 1
                continue
            for n, rec in enumerate(parse_toolbox(text, options), start=1):
                if not rec["words"]:
                    result.skipped["records without a text line"] += 1
                    continue
                morphs, glosses, pos = [], [], []
                for w in rec["words"]:
                    m, g, p = toolbox_word_cells(w)
                    morphs.append(m)
                    glosses.append(g)
                    pos.append(p)
                has_pos = has_pos or any(pos)
                ident = _unique(_safe_id(rec["ref"], f"{f.stem}_{n}"), seen)
                fields: Dict[str, Any] = {
                    "text": " ".join(w["word"] for w in rec["words"]),
                    "words": [w["word"] for w in rec["words"]],
                    "morphemes": morphs,
                    "glosses": glosses,
                    "translation": rec["translation"],
                    "pos": pos,
                    "source_file": f.name,
                    "ref": rec["ref"],
                }
                if rec["extra"]:
                    # Kept so the Toolbox export can write them back.
                    fields["sfm_extra"] = rec["extra"]
                result.items.append(ProjectItem(instance_id=ident, fields=fields))
        if not result.items:
            raise ValueError(f"no Toolbox records with a text line at {path}")
        if not has_pos:
            for item in result.items:
                item.fields.pop("pos", None)
        result.schemes = [_scheme("Toolbox", has_pos)]
        return result
