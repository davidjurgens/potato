"""
TEI P5 XML importer.

Reads ``<text><body>`` of each TEI file into items and the inline named-entity
markup into span pre-annotations.

Units (``options["tei_unit"]``):

``p`` (default)
    each block: ``<p>``, ``<ab>``, ``<head>``, ``<lg>`` (a verse stanza, its
    ``<l>`` lines joined by newlines), a ``<l>`` outside any ``<lg>``;
``div``
    each innermost ``<div>``, its blocks separated by newlines;
``s``
    each ``<s>`` sentence (falls back to ``p`` when the file has none);
``l``
    each verse line.

Spans: ``<persName>``, ``<placeName>``, ``<orgName>``, ``<geogName>``,
``<name>``, ``<date>`` and ``<time>`` are labelled with their element name;
``<rs type="ship">`` is labelled with its ``type`` (``rs`` without one). Spans
written in a ``<standOff><listAnnotation>`` as ``string-range(id, offset,
length)`` targets, which is how the TEI exporter writes spans that cannot nest,
are read too.

The item text is a reading text: ``<choice>`` takes ``<reg>``, ``<corr>`` or
``<expan>`` over ``<orig>``, ``<sic>`` or ``<abbr>``; ``<del>``, ``<note>``,
``<fw>`` and ``<figDesc>`` are left out; ``<lb/>`` is a newline (none with
``break="no"``); ``<gap/>`` is ``[...]``; whitespace from the XML layout is
collapsed. Offsets are code points into that text as the annotation page
renders it.

The title in ``<teiHeader>`` and the file name are kept on each item.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import BaseTextImporter, ImportedDocument, ImportedSpan, TextImportResult

try:  # untrusted XML: refuse entity expansion when defusedxml is installed
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - expat >= 2.4.1 limits expansion itself
    from xml.etree.ElementTree import fromstring as _xml_fromstring

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ENTITY_TAGS = {"persName", "placeName", "orgName", "geogName", "name", "date", "time", "rs"}
SKIP_TAGS = {"note", "fw", "figDesc", "del", "teiHeader", "facsimile", "standOff"}
PREFERRED_IN_CHOICE = ("reg", "corr", "expan")
BLOCK_TAGS = {"p", "ab", "head", "lg", "list", "item", "sp", "speaker", "label", "trailer",
              "opener", "closer", "byline", "dateline", "salute", "signed", "table", "row"}
UNITS = ("p", "div", "s", "l")
_STRING_RANGE = re.compile(r"string-range\(\s*([^,\s)]+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


class _Builder:
    """Walks one unit and records its text, its spans and a string-value map.

    ``raw`` is the text before whitespace normalisation. ``sv`` maps each
    character of the element's XPath string value (all its text, in document
    order, including the parts the reading text leaves out) to a ``raw``
    position, so a ``string-range()`` offset can be moved onto the item.
    """

    def __init__(self):
        self.raw: List[str] = []
        self.synthetic: List[bool] = []
        self.sv: List[int] = []
        self.spans: List[Tuple[int, int, str]] = []

    def text(self, s: Optional[str]) -> None:
        for ch in s or "":
            self.sv.append(len(self.raw))
            self.raw.append(" " if ch in " \t\r\n" else ch)
            self.synthetic.append(False)

    def put(self, s: str) -> None:
        for ch in s:
            self.raw.append(ch)
            self.synthetic.append(True)

    def skip(self, element) -> None:
        for chunk in element.itertext():
            self.sv.extend([len(self.raw)] * len(chunk))

    def walk(self, el, top: bool = False) -> None:
        tag = _local(el.tag)
        if not tag:                         # a comment or processing instruction
            return
        if tag in SKIP_TAGS and not top:
            self.skip(el)
            return
        if tag in ("lb",):
            if (el.get("break") or "").lower() not in ("no", "false"):
                self.put("\n")
            return
        if tag in ("pb", "cb", "milestone", "anchor", "ptr"):
            return
        if tag == "gap":
            self.put("[...]")
            self.skip(el)
            return
        if tag == "choice":
            kids = [c for c in el if _local(c.tag)]
            chosen = next((c for want in PREFERRED_IN_CHOICE for c in kids if _local(c.tag) == want),
                          kids[0] if kids else None)
            self.text(el.text)
            for child in el:
                if child is chosen:
                    self.walk(child)
                elif _local(child.tag):
                    self.skip(child)
                self.text(child.tail)
            return
        if tag in BLOCK_TAGS and not top and self.raw:
            self.put("\n")
        if tag == "l" and not top and self.raw and self.raw[-1] != "\n":
            self.put("\n")
        start = len(self.raw)
        self.text(el.text)
        for child in el:
            self.walk(child)
            self.text(child.tail)
        if tag in ENTITY_TAGS and not top:
            label = (el.get("type") or "rs") if tag == "rs" else tag
            self.spans.append((start, len(self.raw), label))

    def finish(self) -> Tuple[str, List[int]]:
        """Normalised text, and a map from raw positions to it."""
        out: List[str] = []
        mapping: List[int] = []
        for ch, synthetic in zip(self.raw, self.synthetic):
            if ch == " " and not synthetic:
                if not out or out[-1] in " \n":
                    mapping.append(len(out))
                    continue
            if ch == "\n":
                if out and out[-1] == " ":
                    out.pop()
                if not out or (len(out) >= 2 and out[-1] == "\n" and out[-2] == "\n"):
                    mapping.append(len(out))
                    continue
            mapping.append(len(out))
            out.append(ch)
        while out and out[-1] in " \n":
            out.pop()
        mapping.append(len(out))
        mapping = [min(m, len(out)) for m in mapping]
        return "".join(out), mapping


def _title(root) -> str:
    for el in root.iter():
        if _local(el.tag) == "titleStmt":
            for t in el:
                if _local(t.tag) == "title" and "".join(t.itertext()).strip():
                    return re.sub(r"\s+", " ", "".join(t.itertext())).strip()
    return ""


def _body(root):
    text = next((el for el in root.iter() if _local(el.tag) == "text"), None)
    if text is None:
        return None
    body = next((el for el in text.iter() if _local(el.tag) == "body"), None)
    return body if body is not None else text


def _units(body, unit: str) -> List:
    if unit == "div":
        divs = [d for d in body.iter() if _local(d.tag) == "div"
                and not any(_local(c.tag) == "div" for c in d.iter() if c is not d)]
        return divs or [body]
    if unit in ("s", "l"):
        return [el for el in body.iter() if _local(el.tag) == unit]
    picked: List = []
    blocks = {"p", "ab", "head", "lg"}

    def visit(el, inside_lg=False):
        tag = _local(el.tag)
        if tag in SKIP_TAGS:
            return
        if tag in blocks or (tag == "l" and not inside_lg):
            picked.append(el)
            return
        for child in el:
            visit(child, inside_lg or tag == "lg")
    for child in body:
        visit(child)
    return picked


class TEIImporter(BaseTextImporter):
    format_name = "tei"
    description = "TEI P5 XML: paragraphs, verse or divisions as items, inline names as spans"
    file_extensions = [".xml", ".tei"]

    @staticmethod
    def _is_tei(path: Path) -> bool:
        try:
            with path.open("rb") as fh:
                head = fh.read(4096)
        except OSError:
            return False
        return TEI_NS.encode() in head or bool(re.search(rb"<TEI[\s>]", head))

    def _files(self, path: Path) -> List[Path]:
        if path.is_dir():
            return sorted(p for p in path.rglob("*") if p.suffix.lower() in self.file_extensions
                          and p.is_file() and self._is_tei(p))
        return [path] if path.is_file() else []

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if path.is_file():
            return path.suffix.lower() in self.file_extensions and self._is_tei(path)
        return path.is_dir() and bool(self._files(path))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> TextImportResult:
        from potato.importers.projects._dh import rendered_text, slug
        options = options or {}
        unit = str(options.get("tei_unit") or options.get("unit") or "p").lower()
        if unit not in UNITS:
            raise ValueError(f"tei_unit must be one of {', '.join(UNITS)}, not {unit!r}")
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no TEI files at {path}")
        result = TextImportResult()
        labels: Dict[str, None] = {}
        seen: set = set()
        for f in files:
            try:
                root = _xml_fromstring(f.read_bytes())
            except Exception as exc:  # ParseError, or defusedxml's refusals
                result.warnings.append(f"{f.name}: not well-formed XML ({exc}); skipped")
                continue
            body = _body(root)
            if body is None:
                result.warnings.append(f"{f.name}: no <text>; skipped")
                continue
            title = _title(root)
            units = _units(body, unit)
            if not units and unit == "s":
                result.warnings.append(f"{f.name}: no <s> elements; reading paragraphs instead")
                units = _units(body, "p")
            standoff = self._standoff(root)
            for n, el in enumerate(units, start=1):
                b = _Builder()
                b.walk(el, top=True)
                norm, mapping = b.finish()
                if not norm.strip():
                    continue
                dom, remap = rendered_text(norm)
                xml_id = el.get(XML_ID)
                base = xml_id or f"{slug(f.stem, 'tei')}-{n:04d}"
                iid = base
                k = 2
                while iid in seen:
                    iid = f"{base}-{k}"
                    k += 1
                seen.add(iid)
                spans = []
                for start, end, label in b.spans:
                    s, e = remap(mapping[start]), remap(mapping[end])
                    s, e = _trim(dom, s, e)
                    if e > s:
                        spans.append(ImportedSpan(start=s, end=e, label=label, text=dom[s:e]))
                        labels[label] = None
                for off, length, label in standoff.get(xml_id or "", []):
                    if off + length > len(b.sv) or length <= 0:
                        result.warnings.append(f"{iid}: standOff range {off},{length} is outside the text")
                        continue
                    raw_s = b.sv[off]
                    raw_e = b.sv[off + length - 1] + 1
                    s, e = _trim(dom, remap(mapping[raw_s]), remap(mapping[raw_e]))
                    if e > s:
                        spans.append(ImportedSpan(start=s, end=e, label=label, text=dom[s:e]))
                        labels[label] = None
                extra = {"source_file": f.name, "tei_unit": _local(el.tag)}
                if title:
                    extra["title"] = title
                if xml_id:
                    extra["xml_id"] = xml_id
                result.documents.append(ImportedDocument(instance_id=iid, text=dom, spans=spans,
                                                         extra=extra))
        if not result.documents:
            # The reason (a parse error, no <text>) is in the warnings, which
            # a raise would otherwise throw away.
            why = "; ".join(result.warnings)
            raise ValueError(f"no text found in the TEI at {path}" + (f": {why}" if why else ""))
        result.labels = [{"name": name} for name in labels]
        result.verify()
        result.summarize(unit=unit)
        return result

    @staticmethod
    def _standoff(root) -> Dict[str, List[Tuple[int, int, str]]]:
        out: Dict[str, List[Tuple[int, int, str]]] = {}
        for ann in root.iter():
            if _local(ann.tag) != "annotation":
                continue
            target = ann.get("target") or ""
            match = _STRING_RANGE.search(target)
            if not match:
                continue
            note = next((c for c in ann if _local(c.tag) == "note"), None)
            label = ("".join(note.itertext()).strip() if note is not None else "") or \
                (ann.get("ana") or "").lstrip("#") or "annotation"
            ref = match.group(1).lstrip("#")
            out.setdefault(ref, []).append((int(match.group(2)), int(match.group(3)), label))
        return out


def _trim(text: str, s: int, e: int) -> Tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e
