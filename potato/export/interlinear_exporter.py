"""
Interlinear gloss exporters, for ``interlinear_gloss`` schemes.

``flextext``
    One FieldWorks interlinear XML file per annotator (``<user>.flextext``),
    readable by FLEx's interlinear import. Items keep the text, paragraph and
    phrase numbers the FLExText importer recorded; other items go into one
    text named after the task. Morpheme types (stem, prefix, suffix, proclitic,
    enclitic) come from :func:`potato.igt.morpheme_breakdown`.
``toolbox``
    One Toolbox standard-format file per annotator (``<user>.txt``) with
    column-aligned ``\\tx \\mb \\ge \\ps \\ft`` lines per ``\\ref`` record.
    Marker names can be changed with ``options["markers"]`` (role -> marker,
    as for the importer). Markers the importer kept (``sfm_extra``) are written
    back after the free translation.
``igt``
    ``igt.txt``: each example as three aligned lines (words, segmentation,
    gloss) and the free translation in quotes. ``igt.tex``: the same examples
    for the LaTeX package gb4e (``\\gll`` segmentation and gloss, ``\\glt``
    translation), category labels in ``\\textsc``.

All three write what annotators stored. Words whose segmentation and gloss do
not line up are written as they are and counted in the warnings.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterator, List, Optional, Tuple

from potato.igt import (aligned_lines, check_answer, decode_answer, display_width,
                        is_category, marked_form, morpheme_breakdown, pad, split_cell)

from .base import BaseExporter, ExportContext, ExportResult

#: Toolbox markers written, by role.
TOOLBOX_MARKERS = {"record": "ref", "text": "tx", "morphemes": "mb", "gloss": "ge",
                   "pos": "ps", "translation": "ft"}


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]+", "_", str(text)).strip("._") or "annotator"


class _InterlinearBase(BaseExporter):
    file_extensions: List[str] = []

    def _schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if s.get("annotation_type") == "interlinear_gloss"}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No interlinear_gloss scheme in this project"
        if not any(True for _ in self._records(context)):
            return False, "No interlinear glosses to export"
        return True, ""

    def _records(self, context: ExportContext) -> Iterator[Tuple[str, str, dict, dict, dict]]:
        """(user, instance id, scheme, answer, item) in data order, then user."""
        schemes = self._schemes(context)
        order = {iid: n for n, iid in enumerate(context.items or {})}
        found = []
        for ann in context.annotations or []:
            uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
            for name, scheme in schemes.items():
                answer = decode_answer((ann.get("labels") or {}).get(name))
                if answer and answer["words"]:
                    item = (context.items or {}).get(iid)
                    found.append((uid, iid, scheme, answer, item if isinstance(item, dict) else {}))
        found.sort(key=lambda r: (order.get(r[1], len(order)), r[1], r[0], r[2]["name"]))
        return iter(found)

    @staticmethod
    def _misaligned(answer: dict) -> int:
        return sum(1 for r in check_answer(answer) if r["status"] == "misaligned")

    def _by_file(self, context: ExportContext) -> Dict[Tuple[str, str], List[tuple]]:
        multi = len(self._schemes(context)) > 1
        out: Dict[Tuple[str, str], List[tuple]] = {}
        for rec in self._records(context):
            user, _, scheme = rec[0], rec[1], rec[2]
            key = (user, scheme["name"] if multi else "")
            out.setdefault(key, []).append(rec)
        return out

    @staticmethod
    def _stem(user: str, scheme: str) -> str:
        return _safe_name(user) + (f"_{_safe_name(scheme)}" if scheme else "")

    def _result(self, files: List[str], records: int, misaligned: int) -> ExportResult:
        warnings = []
        if misaligned:
            warnings.append(f"{misaligned} word(s) have a segmentation and gloss that do not line "
                            "up; written as stored")
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings, stats={"num_examples": records,
                                                      "num_misaligned_words": misaligned})


# ---------------------------------------------------------------------------
# FLExText
# ---------------------------------------------------------------------------

def _item(parent, kind: str, lang: str, text: str):
    node = ET.SubElement(parent, "item", {"type": kind, "lang": lang})
    node.text = text
    return node


class FlexTextExporter(_InterlinearBase):
    format_name = "flextext"
    description = "FieldWorks (FLEx) interlinear XML, one .flextext per annotator"
    file_extensions = [".flextext"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        files, count, bad = [], 0, 0
        task = str((context.config or {}).get("annotation_task_name") or "Potato export")
        for (user, scheme_name), records in self._by_file(context).items():
            doc = ET.Element("document", {"version": "2"})
            texts: Dict[str, Any] = {}
            langs = {"vern": "", "analysis": ""}
            for _, iid, scheme, answer, item in records:
                count += 1
                bad += self._misaligned(answer)
                vern = scheme.get("language") or item.get("language") or "und"
                analysis = scheme.get("metalanguage") or item.get("metalanguage") or "en"
                langs["vern"] = langs["vern"] or vern
                langs["analysis"] = langs["analysis"] or analysis
                title = str(item.get("text_title") or task)
                if title not in texts:
                    itext = ET.SubElement(doc, "interlinear-text")
                    _item(itext, "title", analysis, title)
                    texts[title] = {"node": ET.SubElement(itext, "paragraphs"), "paras": {},
                                    "itext": itext}
                text = texts[title]
                para_key = str(item.get("paragraph") or 1)
                if para_key not in text["paras"]:
                    para = ET.SubElement(text["node"], "paragraph")
                    text["paras"][para_key] = {"node": ET.SubElement(para, "phrases"), "n": 0}
                para = text["paras"][para_key]
                para["n"] += 1
                phrase = ET.SubElement(para["node"], "phrase")
                _item(phrase, "segnum", analysis, str(item.get("phrase") or f"{para_key}.{para['n']}"))
                words = ET.SubElement(phrase, "words")
                tiers = list(scheme.get("tiers") or [])
                for w in answer["words"]:
                    word = ET.SubElement(words, "word")
                    _item(word, "txt", vern, w.get("word", ""))
                    morphs = ET.SubElement(word, "morphemes")
                    for m in morpheme_breakdown(w.get("morphemes", ""), w.get("gloss", "")):
                        morph = ET.SubElement(morphs, "morph", {"type": m["type"]})
                        _item(morph, "txt", vern, marked_form(m))
                        _item(morph, "gls", analysis, m["gloss"])
                    if "pos" in tiers and w.get("pos"):
                        _item(word, "pos", analysis, w["pos"])
                if answer.get("translation"):
                    _item(phrase, "gls", analysis, answer["translation"])
            for text in texts.values():
                languages = ET.SubElement(text["itext"], "languages")
                ET.SubElement(languages, "language", {"lang": langs["vern"], "vernacular": "true"})
                ET.SubElement(languages, "language", {"lang": langs["analysis"]})
            ET.indent(doc, space="  ")
            path = os.path.join(output_path, self._stem(user, scheme_name) + ".flextext")
            ET.ElementTree(doc).write(path, encoding="utf-8", xml_declaration=True)
            files.append(path)
        return self._result(files, count, bad)


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------

def _split_like(value: str, n: int) -> List[str]:
    """A tier cell split into one value per morpheme, or all of it on the first."""
    pieces, _, _ = split_cell(value)
    if len(pieces) == n:
        return pieces
    return [value] + [""] * (n - 1) if n else []


def toolbox_record(ref: str, answer: dict, tiers: List[str], markers: Dict[str, str],
                   extra: Optional[Dict[str, str]] = None) -> List[str]:
    """One ``\\ref`` record as lines, interlinear lines aligned by column."""
    rows: Dict[str, List[str]] = {"text": [], "morphemes": [], "gloss": []}
    other = [t for t in tiers if t != "pos"]
    if "pos" in tiers:
        rows["pos"] = []
    for t in other:
        rows[t] = []
    # An aligned line splits its cells on whitespace, so a tier with a
    # multi-word value cannot be aligned; it is written in full, word by word.
    loose = [t for t in other if any(re.search(r"\s", str(w.get(t) or "").strip())
                                     for w in answer["words"])]
    for w in answer["words"]:
        parts = morpheme_breakdown(w.get("morphemes", ""), w.get("gloss", ""))
        forms = [marked_form(p) for p in parts]
        glosses = [p["before"] + p["gloss"] if p["type"] in ("suffix", "enclitic")
                   else p["gloss"] + p["after"] if p["type"] in ("prefix", "proclitic")
                   else p["gloss"] for p in parts]
        pos = _split_like(w.get("pos", ""), len(parts)) if "pos" in rows else []
        widths = [max(display_width(f), display_width(g),
                      display_width(pos[i]) if pos else 0) + 1
                  for i, (f, g) in enumerate(zip(forms, glosses))]
        word = w.get("word", "")
        others = {t: "" if t in loose else str(w.get(t, "")) for t in other}
        total = max([display_width(word) + 1, sum(widths)] +
                    [display_width(v) + 1 for v in others.values()])
        if widths:
            widths[-1] += total - sum(widths)
        else:
            widths = [total]
            forms, glosses = [""], [""]
            pos = [""] if "pos" in rows else []
        rows["text"].append(pad(word, total))
        rows["morphemes"].append("".join(pad(f, wd) for f, wd in zip(forms, widths)))
        rows["gloss"].append("".join(pad(g, wd) for g, wd in zip(glosses, widths)))
        if "pos" in rows:
            rows["pos"].append("".join(pad(p, wd) for p, wd in zip(pos, widths)))
        for t in other:
            rows[t].append(pad(others[t], total))
    names = {role: markers.get(role, role) for role in rows}
    width = max(len(n) for n in names.values()) + 2
    lines = [f"\\{markers['record']} {ref}"]
    for role, cells in rows.items():
        body = "".join(cells).rstrip()
        if body or role in ("text", "morphemes", "gloss"):
            lines.append((pad("\\" + names[role], width) + body).rstrip())
    for t in loose:
        lines.extend(f"\\{names[t]} {w.get('word', '')}: {_one_line(w.get(t))}"
                     for w in answer["words"] if str(w.get(t) or "").strip())
    if answer.get("translation"):
        lines.append(f"\\{markers['translation']} {_one_line(answer['translation'])}")
    for marker, value in (extra or {}).items():
        # The importer joins a repeated marker's lines with newlines.
        lines.extend(f"\\{marker} {_one_line(v)}" for v in str(value).split("\n"))
    return lines


def _one_line(value) -> str:
    """A field value on one line: a line that starts with a backslash would be a new field."""
    return re.sub(r"\s*\n\s*", " ", str(value or "").strip())


class ToolboxExporter(_InterlinearBase):
    format_name = "toolbox"
    description = "Toolbox / Shoebox standard format interlinear text, one file per annotator"
    file_extensions = [".txt"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        markers = dict(TOOLBOX_MARKERS)
        for role, name in ((options or {}).get("markers") or {}).items():
            name = name[0] if isinstance(name, (list, tuple)) and name else name
            if role in markers and name:
                markers[role] = str(name).lstrip("\\")
        files, count, bad = [], 0, 0
        for (user, scheme_name), records in self._by_file(context).items():
            out = ["\\_sh v3.0  400  Text", ""]
            for _, iid, scheme, answer, item in records:
                count += 1
                bad += self._misaligned(answer)
                extra = item.get("sfm_extra") if isinstance(item.get("sfm_extra"), dict) else None
                ref = str(item.get("ref") or iid)
                out.extend(toolbox_record(ref, answer, list(scheme.get("tiers") or []), markers, extra))
                out.append("")
            path = os.path.join(output_path, self._stem(user, scheme_name) + ".txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            files.append(path)
        return self._result(files, count, bad)


# ---------------------------------------------------------------------------
# Plain text and gb4e
# ---------------------------------------------------------------------------

_LATEX = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
    "#": r"\#", "%": r"\%", "_": r"\_", "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}", "<": r"\textless{}", ">": r"\textgreater{}",
}
_GLOSS_ELEMENT = re.compile(r"[^.:;_\\()\[\]\s<>=\-]+")


def latex_escape(text: str) -> str:
    """Text with LaTeX's special characters written as commands."""
    return "".join(_LATEX.get(ch, ch) for ch in str(text))


def latex_gloss(gloss: str) -> str:
    """A gloss cell for gb4e: category labels in ``\\textsc``, the rest escaped."""
    out, last = [], 0
    text = str(gloss)
    for m in _GLOSS_ELEMENT.finditer(text):
        out.append(latex_escape(text[last:m.start()]))
        token = m.group()
        if is_category(token) and token != "Ø":
            out.append(r"\textsc{" + latex_escape(token.lower()) + "}")
        else:
            out.append(latex_escape(token))
        last = m.end()
    out.append(latex_escape(text[last:]))
    return "".join(out)


def _gb4e_cell(cell: str) -> str:
    # gb4e splits the lines on spaces and reads "[" as an optional argument.
    if not cell:
        return "{}"
    return "{" + cell + "}" if cell.startswith("[") or " " in cell else cell


def gb4e_example(answer: dict, comment: str = "") -> List[str]:
    seg = " ".join(_gb4e_cell(latex_escape(w.get("morphemes", ""))) for w in answer["words"])
    gls = " ".join(_gb4e_cell(latex_gloss(w.get("gloss", ""))) for w in answer["words"])
    lines = [r"\ex" + (f" % {comment}" if comment else ""),
             r"\gll " + seg + r"\\",
             "     " + gls + r"\\"]
    lines.append(r"\glt `" + latex_escape(answer.get("translation", "")) + "'")
    return lines


def plain_example(number: int, answer: dict) -> List[str]:
    rows = [[w.get("word", "") for w in answer["words"]],
            [w.get("morphemes", "") for w in answer["words"]],
            [w.get("gloss", "") for w in answer["words"]]]
    label = f"({number})"
    indent = " " * (len(label) + 2)
    body = aligned_lines(rows)
    out = [label + "  " + body[0]] + [indent + line for line in body[1:]]
    if answer.get("translation"):
        out.append(indent + "'" + answer["translation"] + "'")
    return out


class IGTExporter(_InterlinearBase):
    format_name = "igt"
    description = "Interlinear examples as aligned plain text (igt.txt) and gb4e LaTeX (igt.tex)"
    file_extensions = [".txt", ".tex"]

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        records = list(self._records(context))
        users = {r[0] for r in records}
        txt: List[str] = []
        tex = ["% Interlinear examples exported by Potato. Needs \\usepackage{gb4e}.",
               "% Category labels are set with \\textsc; for scripts other than Latin,",
               "% compile with XeLaTeX or LuaLaTeX.",
               r"\begin{exe}"]
        bad = 0
        for n, (user, iid, scheme, answer, item) in enumerate(records, start=1):
            bad += self._misaligned(answer)
            who = f"{iid}, {user}" if len(users) > 1 else iid
            txt.append(f"[{who}]")
            txt.extend(plain_example(n, answer))
            txt.append("")
            tex.extend(gb4e_example(answer, comment=who.replace("%", r"\%")))
        tex.append(r"\end{exe}")
        files = []
        for name, lines in (("igt.txt", txt), ("igt.tex", tex)):
            path = os.path.join(output_path, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines).rstrip("\n") + "\n")
            files.append(path)
        return self._result(files, len(records), bad)
