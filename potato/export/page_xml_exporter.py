"""
PAGE XML, with the annotators' corrections written into the original files.

For projects made with ``potato import -f page_xml``. The importer keeps a copy
of every source file under ``page_xml/`` in the project; this exporter opens
that copy, changes only what was corrected, and writes it out with the rest of
the file (metadata, reading order, words, styles, custom attributes, the
schema version and its namespace) as it was.

Line mode (a ``text_edit`` scheme over one item per ``TextLine``):
    the line's ``TextEquiv/Unicode`` (and ``PlainText``, when present) is set
    to the corrected text and its recogniser ``conf`` is removed. When the text
    changed, the line's ``Word`` elements no longer match it and are removed
    (``keep_words=true`` keeps them). A region that had its own ``TextEquiv``
    gets its lines' texts joined by newlines.

Layout mode (an ``image_annotation`` scheme over one item per page):
    a shape that came from the file (it carries ``attributes.page_xml_id``)
    updates that element's ``Coords``; a region's ``type`` follows a changed
    label. A shape the annotator drew becomes a new ``TextLine`` (label
    ``line``, placed in the region that contains its centre) or a new
    ``TextRegion``. An element the annotator deleted is removed, with its
    reading-order reference.

Items nobody annotated leave their lines and pages unchanged. With several
annotators each gets a folder of their own (``annotator=<name>`` picks one).

Output: ``page_xml/<the source's relative path>``.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

XSI = "http://www.w3.org/2001/XMLSchema-instance"
TEXT_REGION_TYPES = {"paragraph", "heading", "caption", "header", "footer", "page-number",
                     "drop-capital", "credit", "floating", "signature-mark", "catch-word",
                     "marginalia", "footnote", "footnote-continued", "endnote", "TOC-entry",
                     "list-label", "other"}
#: PAGE's sequence of TextLine children; a new TextEquiv goes after these.
_BEFORE_TEXTEQUIV = {"AlternativeImage", "Coords", "Baseline", "Word"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def _edited_text(labels: Any) -> Optional[str]:
    """The corrected text from a text_edit record (a JSON blob, or a plain string)."""
    if not isinstance(labels, dict):
        return None
    for value in labels.values():
        if not isinstance(value, str):
            continue
        try:
            data = json.loads(value)
        except ValueError:
            return value
        if isinstance(data, dict) and isinstance(data.get("edited_text"), str):
            return data["edited_text"]
        if isinstance(data, str):
            return data
    return None


def _parse(path: str):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    tree = ET.parse(path, parser=parser)
    root = tree.getroot()
    ns = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    return tree, root, ns


def _points_str(points: List[List[float]]) -> str:
    return " ".join(f"{int(round(x))},{int(round(y))}" for x, y in points)


def _set_coords(element, points: List[List[float]], ns: str) -> None:
    coords = next((c for c in element if _local(c.tag) == "Coords"), None)
    if coords is None:
        coords = ET.Element(f"{{{ns}}}Coords" if ns else "Coords")
        element.insert(0, coords)
    for child in list(coords):
        coords.remove(child)        # the 2010 <Point> form
    coords.attrib.pop("conf", None)
    coords.set("points", _points_str(points))


def _set_text(element, text: str, ns: str) -> None:
    q = (lambda name: f"{{{ns}}}{name}") if ns else (lambda name: name)
    equivs = [c for c in element if _local(c.tag) == "TextEquiv"]
    if equivs:
        equivs.sort(key=lambda e: (e.get("index") not in (None, "", "1", "0"), e.get("index") or ""))
        equiv = equivs[0]
    else:
        equiv = ET.Element(q("TextEquiv"))
        position = 0
        for i, child in enumerate(list(element)):
            if _local(child.tag) in _BEFORE_TEXTEQUIV:
                position = i + 1
        element.insert(position, equiv)
    equiv.attrib.pop("conf", None)
    plain = next((c for c in equiv if _local(c.tag) == "PlainText"), None)
    if plain is not None:
        plain.text = text
    uni = next((c for c in equiv if _local(c.tag) == "Unicode"), None)
    if uni is None:
        uni = ET.SubElement(equiv, q("Unicode"))
    uni.text = text


def _centre(points: List[List[float]]) -> Tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _inside(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


class PageXMLExporter(BaseExporter):
    format_name = "page_xml"
    description = "PAGE XML with corrected line texts or layout written into the source files"
    file_extensions = [".xml"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(isinstance(item, dict) and item.get("page_xml") for item in context.items.values()):
            return False, ("no item has a page_xml field; this export is for projects "
                           "imported from PAGE XML (potato import -f page_xml)")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        task_dir = str((context.config or {}).get("task_dir") or ".")
        keep_words = _truthy(options.get("keep_words", False))
        only = options.get("annotator")
        schemas = {s.get("name"): s for s in context.schemas or []}
        text_schemes = [n for n, s in schemas.items() if s.get("annotation_type") in ("text_edit", "text")]
        image_schemes = [n for n, s in schemas.items() if s.get("annotation_type") == "image_annotation"]

        # user -> page_xml rel -> list of (item, annotation record)
        work: Dict[str, Dict[str, List[Tuple[dict, dict]]]] = defaultdict(lambda: defaultdict(list))
        for ann in context.annotations:
            user = str(ann.get("user_id", ""))
            if only and user != only:
                continue
            item = context.items.get(str(ann.get("instance_id", ""))) or {}
            rel = item.get("page_xml")
            if rel:
                work[user][rel].append((item, ann))
        if not work:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["no annotations on PAGE XML items"
                                        + (f" by {only}" if only else "")])

        written: List[str] = []
        warnings: List[str] = []
        stats = defaultdict(int)
        per_user = len(work) > 1
        for user, pages in sorted(work.items()):
            base = os.path.join(output_path, user) if per_user else output_path
            for rel, entries in sorted(pages.items()):
                source = rel if os.path.isabs(rel) else os.path.join(task_dir, rel)
                if not os.path.isfile(source):
                    warnings.append(f"{rel} is missing from the task directory; its "
                                    "corrections were not written")
                    stats["pages_missing"] += 1
                    continue
                tree, root, ns = _parse(source)
                if ns:
                    ET.register_namespace("", ns)
                ET.register_namespace("xsi", XSI)
                by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
                changed = False
                for item, ann in entries:
                    if item.get("line_id"):
                        changed |= self._line(item, ann, by_id, text_schemes, ns, keep_words,
                                              stats, warnings)
                    else:
                        changed |= self._layout(item, ann, root, by_id, image_schemes, ns, stats)
                if changed:
                    self._touch(root, ns)
                rel_out = rel[len("page_xml/"):] if rel.startswith("page_xml/") else os.path.basename(rel)
                out = os.path.join(base, "page_xml", rel_out)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                tree.write(out, encoding="UTF-8", xml_declaration=True)
                written.append(out)
                stats["pages_written"] += 1
        return ExportResult(success=True, format_name=self.format_name, files_written=written,
                            warnings=warnings, stats=dict(stats))

    # ------------------------------------------------------------------ lines

    def _line(self, item, ann, by_id, text_schemes, ns, keep_words, stats, warnings) -> bool:
        line = by_id.get(item.get("line_id"))
        if line is None or _local(line.tag) != "TextLine":
            warnings.append(f"line {item.get('line_id')} is not in {item.get('page_xml')}")
            return False
        labels = ann.get("labels") or {}
        text = None
        for name in text_schemes:
            text = _edited_text(labels.get(name))
            if text is not None:
                break
        if text is None:
            return False
        text = text.replace("\r\n", "\n").replace("\n", " ").strip()
        before = item.get("htr_text", "")
        _set_text(line, text, ns)
        stats["lines_written"] += 1
        if text != before:
            stats["lines_changed"] += 1
            if not keep_words:
                for word in [c for c in line if _local(c.tag) == "Word"]:
                    line.remove(word)
        region = by_id.get(item.get("region_id"))
        if region is not None and any(_local(c.tag) == "TextEquiv" for c in region):
            texts = []
            for child in region:
                if _local(child.tag) == "TextLine":
                    equiv = next((c for c in child if _local(c.tag) == "TextEquiv"), None)
                    uni = next((c for c in equiv if _local(c.tag) == "Unicode"), None) if equiv is not None else None
                    texts.append((uni.text or "") if uni is not None else "")
            _set_text(region, "\n".join(texts), ns)
        return True

    # ------------------------------------------------------------------ layout

    def _layout(self, item, ann, root, by_id, image_schemes, ns, stats) -> bool:
        from .cv_utils import normalize_annotation_object
        records = ann.get("image_annotations") or {}
        names = [n for n in image_schemes if n in records]
        if not names:
            return False
        w = float(item.get("image_width") or 0)
        h = float(item.get("image_height") or 0)
        if not (w and h):
            return False
        q = (lambda name: f"{{{ns}}}{name}") if ns else (lambda name: name)
        page = next((c for c in root if _local(c.tag) == "Page"), None)
        if page is None:
            return False
        kept = set()
        new_lines: List[Tuple[List[List[float]], str]] = []
        new_regions: List[Tuple[List[List[float]], str]] = []
        for name in names:
            for obj in records[name] or []:
                norm = normalize_annotation_object(obj, w, h)
                if norm is None:
                    continue
                points = norm.get("points")
                if not points and norm.get("bbox"):
                    x, y, bw, bh = norm["bbox"]
                    points = [[x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]]
                if not points or len(points) < 3:
                    continue
                attrs = obj.get("attributes") or {}
                element = by_id.get(attrs.get("page_xml_id")) if attrs.get("page_xml_id") else None
                label = str(obj.get("label") or "")
                if element is not None:
                    kept.add(element.get("id"))
                    _set_coords(element, points, ns)
                    if (_local(element.tag) == "TextRegion" and label in TEXT_REGION_TYPES
                            and element.get("type") != label):
                        element.set("type", label)
                    stats["shapes_updated"] += 1
                elif label == "line":
                    new_lines.append((points, label))
                else:
                    new_regions.append((points, label))

        # Deleted: every region and line the file had that the annotator removed.
        parents = {child: parent for parent in root.iter() for child in parent}
        removed = set()
        for element in list(page.iter()):
            tag = _local(element.tag)
            if element.get("id") and (tag == "TextLine" or (tag.endswith("Region") and element is not page)) \
                    and any(_local(c.tag) == "Coords" for c in element):
                if element.get("id") not in kept and parents.get(element) is not None:
                    # Lines inside a deleted region go with it.
                    if any(id(a) in removed for a in self._ancestors(element, parents)):
                        continue
                    parents[element].remove(element)
                    removed.add(id(element))
                    stats["shapes_removed"] += 1
                    self._drop_ref(page, element.get("id"))

        counter = 0
        regions = [el for el in page.iter() if _local(el.tag) == "TextRegion"]
        for points, label in new_regions:
            counter += 1
            region = ET.SubElement(page, q("TextRegion"),
                                   {"id": f"r_potato_{counter}"})
            if label in TEXT_REGION_TYPES:
                region.set("type", label)
            else:
                region.set("custom", f"potato-label {{value:{label};}}")
            _set_coords(region, points, ns)
            regions.append(region)
            stats["shapes_added"] += 1
        for points, _label in new_lines:
            counter += 1
            centre = _centre(points)
            host = next((r for r in regions if _inside(centre, self._coords(r))), None)
            if host is None:
                host = ET.SubElement(page, q("TextRegion"), {"id": f"r_potato_{counter}"})
                _set_coords(host, points, ns)
                regions.append(host)
            line = ET.Element(q("TextLine"), {"id": f"l_potato_{counter}"})
            _set_coords(line, points, ns)
            # After the region's own Coords and existing lines, before its TextEquiv.
            position = len(host)
            for i, child in enumerate(list(host)):
                if _local(child.tag) in ("TextEquiv", "TextStyle", "UserDefined", "Labels"):
                    position = i
                    break
            host.insert(position, line)
            stats["shapes_added"] += 1
        return True

    @staticmethod
    def _ancestors(element, parents):
        node = parents.get(element)
        while node is not None:
            yield node
            node = parents.get(node)

    @staticmethod
    def _coords(element) -> List[List[float]]:
        from potato.importers.projects.page_xml import coords_points
        return coords_points(element)

    @staticmethod
    def _drop_ref(page, region_id: str) -> None:
        for order in page.iter():
            for ref in list(order):
                if _local(ref.tag).startswith("RegionRef") and ref.get("regionRef") == region_id:
                    order.remove(ref)

    @staticmethod
    def _touch(root, ns: str) -> None:
        meta = next((c for c in root if _local(c.tag) == "Metadata"), None)
        if meta is None:
            return
        last = next((c for c in meta if _local(c.tag) == "LastChange"), None)
        if last is not None:
            last.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
