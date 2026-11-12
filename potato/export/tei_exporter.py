"""
TEI P5 XML with the annotated spans as inline markup.

Each item becomes a ``<p xml:id="<instance id>">`` holding its text exactly as
the annotation page showed it (newlines become ``<lb/>``). Each span is
wrapped in an element:

* the span's label itself when it is a TEI name element (``persName``,
  ``placeName``, ``orgName``, ``geogName``, ``name``, ``date``, ``time``), so
  a TEI file imported with ``potato import -f tei`` comes back with the same
  elements;
* ``<rs type="LABEL">`` otherwise.

XML elements must nest. A span that crosses another one (both start inside
each other) cannot be written inline, so it goes into
``<standOff><listAnnotation>`` as an ``<annotation>`` whose ``target`` is
``#string-range(<p id>,<offset>,<length>)``, offsets counted in the ``<p>``'s
string value; the TEI importer reads these back.

Items are grouped into one TEI document per source file (the ``source_file``
field the TEI importer keeps), or one document for the whole project. With
several annotators each gets a folder of their own; ``annotator=<name>``
writes only that person's spans.

Output: ``tei/<source name>.xml``.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NAME_ELEMENTS = {"persName", "placeName", "orgName", "geogName", "name", "date", "time"}
_NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def xml_id_for(instance_id: str) -> str:
    """An xml:id for an instance id (an NCName: no leading digit, no spaces)."""
    value = str(instance_id)
    if _NCNAME.match(value):
        return value
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return cleaned if _NCNAME.match(cleaned) else f"item_{cleaned}"


def split_nesting(spans: List[dict]) -> Tuple[List[dict], List[dict]]:
    """(inline, standoff): the largest set that nests, greedily, and the rest."""
    ordered = sorted(spans, key=lambda s: (s["start"], -s["end"], s["label"]))
    inline: List[dict] = []
    standoff: List[dict] = []
    for span in ordered:
        crosses = any(o["start"] < span["start"] < o["end"] < span["end"]
                      or span["start"] < o["start"] < span["end"] < o["end"]
                      for o in inline)
        same = any(o["start"] == span["start"] and o["end"] == span["end"]
                   and o["label"] == span["label"] for o in inline)
        if same:
            continue
        (standoff if crosses else inline).append(span)
    return inline, standoff


def build_paragraph(parent, xml_id: str, text: str, spans: List[dict]) -> None:
    """Append ``<p>`` with ``text`` and the (properly nesting) ``spans`` inline."""
    p = ET.SubElement(parent, _q("p"), {XML_ID: xml_id})
    # Events: open at start (longest first), close at end (innermost first).
    stack: List[Tuple[ET.Element, int]] = [(p, len(text))]
    opens: Dict[int, List[dict]] = defaultdict(list)
    for span in sorted(spans, key=lambda s: (s["start"], -s["end"])):
        opens[span["start"]].append(span)

    def append_text(chunk: str) -> None:
        # Text goes into the innermost open element: after its last child
        # (as that child's tail) or as its own text.
        parts = chunk.split("\n")
        for i, part in enumerate(parts):
            if i:
                ET.SubElement(stack[-1][0], _q("lb"))
            if not part:
                continue
            element = stack[-1][0]
            if len(element):
                element[-1].tail = (element[-1].tail or "") + part
            else:
                element.text = (element.text or "") + part

    buf = []
    for pos, ch in enumerate(text + "\0"):
        closing = [entry for entry in stack[1:] if entry[1] == pos]
        if closing or pos in opens:
            if buf:
                append_text("".join(buf))
                buf = []
        while len(stack) > 1 and stack[-1][1] == pos:
            stack.pop()
        for span in opens.get(pos, []):
            label = str(span["label"])
            if label in NAME_ELEMENTS:
                el = ET.SubElement(stack[-1][0], _q(label))
            else:
                el = ET.SubElement(stack[-1][0], _q("rs"), {"type": label})
            if span["end"] > span["start"]:
                stack.append((el, span["end"]))
        if pos < len(text):
            buf.append(ch)
    if buf:
        append_text("".join(buf))


def string_value_offset(text: str, offset: int) -> int:
    """An item offset as an offset in the ``<p>``'s string value (``<lb/>`` adds none)."""
    return offset - text[:offset].count("\n")


class TEIExporter(BaseExporter):
    format_name = "tei"
    description = "TEI P5 XML with spans as inline name/rs elements (overlaps in standOff)"
    file_extensions = [".xml"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(ann.get("spans") for ann in context.annotations):
            return False, "No span annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        only = options.get("annotator")
        text_key = ((context.config or {}).get("item_properties") or {}).get("text_key", "text")
        # user -> group -> instance id -> spans
        per_user: Dict[str, Dict[str, Dict[str, List[dict]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list)))
        for ann in context.annotations:
            user = str(ann.get("user_id", ""))
            if only and user != only:
                continue
            iid = str(ann.get("instance_id", ""))
            item = context.items.get(iid) or {}
            group = str(item.get("source_file") or "")
            bucket = per_user[user][group][iid]
            for spans in (ann.get("spans") or {}).values():
                for span in spans or []:
                    try:
                        start, end = int(span["start"]), int(span["end"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if end <= start:
                        continue
                    bucket.append({"start": start, "end": end,
                                   "label": span.get("name") or span.get("label") or "rs",
                                   "field": span.get("target_field")})
        if not per_user:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["no span annotations" + (f" by {only}" if only else "")])

        ET.register_namespace("", TEI_NS)
        written: List[str] = []
        warnings: List[str] = []
        n_inline = n_standoff = 0
        several = len(per_user) > 1
        # Paragraphs go out in the order of the data file (which is the TEI
        # source order for an imported text), not the order they were
        # annotated in.
        position = {iid: n for n, iid in enumerate(context.items)}
        for user, groups in sorted(per_user.items()):
            folder = os.path.join(output_path, user, "tei") if several else os.path.join(output_path, "tei")
            os.makedirs(folder, exist_ok=True)
            for group, items in sorted(groups.items()):
                root = ET.Element(_q("TEI"))
                header = ET.SubElement(root, _q("teiHeader"))
                file_desc = ET.SubElement(header, _q("fileDesc"))
                title_stmt = ET.SubElement(file_desc, _q("titleStmt"))
                first = context.items.get(min(items, key=lambda i: position.get(i, len(position)))) or {}
                ET.SubElement(title_stmt, _q("title")).text = str(
                    first.get("title") or (context.config or {}).get("annotation_task_name") or "Potato export")
                pub = ET.SubElement(file_desc, _q("publicationStmt"))
                ET.SubElement(pub, _q("p")).text = f"Annotations exported from Potato (annotator {user})."
                src = ET.SubElement(file_desc, _q("sourceDesc"))
                ET.SubElement(src, _q("p")).text = group or "Potato project items"
                body = ET.SubElement(ET.SubElement(root, _q("text")), _q("body"))
                div = ET.SubElement(body, _q("div"))
                standoff_items: List[Tuple[str, str, dict]] = []
                ordered = sorted(items.items(), key=lambda kv: position.get(kv[0], len(position)))
                for iid, spans in ordered:
                    item = context.items.get(iid) or {}
                    text = self._text(context, item, text_key)
                    if text is None:
                        warnings.append(f"{iid}: no text to mark up; left out")
                        continue
                    valid = [s for s in spans if s["end"] <= len(text)]
                    if len(valid) < len(spans):
                        warnings.append(f"{iid}: {len(spans) - len(valid)} span(s) past the end of the text")
                    inline, standoff = split_nesting(valid)
                    xid = xml_id_for(iid)
                    build_paragraph(div, xid, text, inline)
                    n_inline += len(inline)
                    standoff_items.extend((xid, text, s) for s in standoff)
                if standoff_items:
                    lst = ET.SubElement(ET.SubElement(root, _q("standOff")), _q("listAnnotation"))
                    for n, (xid, text, span) in enumerate(standoff_items, start=1):
                        start = string_value_offset(text, span["start"])
                        end = string_value_offset(text, span["end"])
                        ann_el = ET.SubElement(lst, _q("annotation"), {
                            XML_ID: f"{xid}_a{n}", "target": f"#string-range({xid},{start},{end - start})",
                            "motivation": "tagging"})
                        ET.SubElement(ann_el, _q("note")).text = span["label"]
                        n_standoff += 1
                name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.splitext(group)[0]).strip("-") or "potato"
                out = os.path.join(folder, f"{name}.xml")
                ET.ElementTree(root).write(out, encoding="UTF-8", xml_declaration=True)
                written.append(out)
        if n_standoff:
            warnings.append(f"{n_standoff} overlapping span(s) could not nest and were written to "
                            "<standOff> as string-range annotations")
        return ExportResult(success=True, format_name=self.format_name, files_written=written,
                            warnings=warnings, stats={"num_inline": n_inline,
                                                      "num_standoff": n_standoff})

    @staticmethod
    def _text(context: ExportContext, item: dict, text_key: str) -> Optional[str]:
        if not item:
            return None
        try:
            text = context._span_anchor_text(item, text_key)
        except Exception:
            text = None
        if text is None and isinstance(item.get(text_key), str):
            text = item[text_key]
        return text
