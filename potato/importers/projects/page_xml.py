"""
PAGE XML (PRImA) files, as Transkribus, eScriptorium, OCR-D and Kraken write
them, as a handwritten-text-recognition correction project.

Input is one ``.xml`` file or a folder of them (searched recursively, so a
Transkribus export with its ``page/`` folder works). Each file is a
``PcGts > Page`` with ``imageFilename``, ``imageWidth`` and ``imageHeight``;
the image is looked for beside the XML, one folder up (the Transkribus
layout), and in ``options["image_dir"]``, and copied into the project's
``media/``. Both the 2013 and 2019 schema versions are read, and the older
``<Coords><Point x= y=/></Coords>`` form as well as ``points="x,y x,y"``.

Two modes (``options["page_xml_mode"]``):

``lines`` (default)
    One item per ``TextLine``, in reading order. The annotator sees the line
    cropped out of the page (the ``image_region`` display) and corrects its
    recognised text in a ``text_edit`` scheme pre-filled with the line's
    ``TextEquiv/Unicode``.
``regions``
    One item per page. Every region and every text line comes in as a polygon
    on an ``image_annotation`` scheme, labelled with the region's type
    (``paragraph``, ``heading``, ``marginalia``, ...; ``image``, ``table``,
    ... for non-text regions; ``line`` for text lines), for correcting the
    layout analysis.

A copy of each XML file is kept under ``page_xml/`` in the project, and the
``page_xml`` exporter writes the corrections into that copy, leaving the rest
of the file as it was.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from potato.importers._common import probe_image_size

from . import _dh
from .base import ProjectImportResult, ProjectItem

try:  # untrusted XML: refuse entity expansion when defusedxml is installed
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - expat >= 2.4.1 limits expansion itself
    from xml.etree.ElementTree import fromstring as _xml_fromstring

LINE_SCHEME = "transcription"
LAYOUT_SCHEME = "layout"
LINE_LABEL = "line"
MODES = ("lines", "regions")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def coords_points(element) -> List[List[float]]:
    """The polygon of a region or line: ``points="x,y ..."`` or ``<Point>`` children."""
    coords = next((c for c in element if local(c.tag) == "Coords"), None)
    if coords is None:
        return []
    if coords.get("points"):
        return _dh.parse_points(coords.get("points"))
    out = []
    for point in coords:
        if local(point.tag) == "Point":
            try:
                out.append([float(point.get("x")), float(point.get("y"))])
            except (TypeError, ValueError):
                continue
    return out


def baseline_points(element) -> List[List[float]]:
    base = next((c for c in element if local(c.tag) == "Baseline"), None)
    if base is None:
        return []
    if base.get("points"):
        return _dh.parse_points(base.get("points"))
    return [[float(p.get("x", 0)), float(p.get("y", 0))] for p in base if local(p.tag) == "Point"]


def text_equiv(element) -> str:
    """The element's own ``TextEquiv/Unicode`` (index 1, or the first)."""
    equivs = [c for c in element if local(c.tag) == "TextEquiv"]
    if not equivs:
        return ""
    equivs.sort(key=lambda e: (e.get("index") not in (None, "", "1", "0"), e.get("index") or ""))
    unicode_el = next((c for c in equivs[0] if local(c.tag) == "Unicode"), None)
    if unicode_el is not None and unicode_el.text:
        return unicode_el.text
    plain = next((c for c in equivs[0] if local(c.tag) == "PlainText"), None)
    return (plain.text or "") if plain is not None else ""


def region_label(element) -> str:
    tag = local(element.tag)
    if tag == "TextRegion":
        return element.get("type") or "text"
    base = tag[:-len("Region")] if tag.endswith("Region") else tag
    return re.sub(r"(?<!^)(?=[A-Z])", "-", base).lower() or "region"


def reading_order(page) -> List[str]:
    """Region ids in the page's ReadingOrder, if it has one."""
    order = next((c for c in page if local(c.tag) == "ReadingOrder"), None)
    if order is None:
        return []
    ids: List[Tuple[int, str]] = []
    for n, ref in enumerate(order.iter()):
        if local(ref.tag).startswith("RegionRef") and ref.get("regionRef"):
            try:
                key = int(ref.get("index"))
            except (TypeError, ValueError):
                key = 10_000 + n
            ids.append((key, ref.get("regionRef")))
    # Nested groups: keep document order within an index tie.
    return [rid for _, rid in sorted(ids, key=lambda t: t[0])]


def iter_regions(page) -> List[Any]:
    """Every region on the page (nested ones too), in reading order where given."""
    regions = [el for el in page.iter() if local(el.tag).endswith("Region")
               and el is not page and any(local(c.tag) == "Coords" for c in el)]
    order = reading_order(page)
    if order:
        rank = {rid: i for i, rid in enumerate(order)}
        regions.sort(key=lambda r: rank.get(r.get("id"), len(rank)))
    return regions


def parse_page_file(path: Path):
    """``(root, page)`` of a PAGE XML file, or raise ValueError."""
    try:
        root = _xml_fromstring(path.read_bytes())
    except Exception as exc:  # ParseError, or defusedxml's refusals
        raise ValueError(f"{path.name}: not well-formed XML ({exc})") from exc
    if local(root.tag) != "PcGts":
        raise ValueError(f"{path.name}: not a PAGE XML file (root is <{local(root.tag)}>)")
    page = next((c for c in root if local(c.tag) == "Page"), None)
    if page is None:
        raise ValueError(f"{path.name}: has no <Page>")
    return root, page


def outside_image(points: List[List[float]], width: int, height: int) -> bool:
    """Whether any point lies off a ``width`` x ``height`` image (unknown size: no)."""
    if not (width and height):
        return False
    return any(x < 0 or y < 0 or x > width or y > height for x, y in points)


def warn_outside(xml: Path, ids: List[str], width: int, height: int,
                 result: ProjectImportResult) -> None:
    if not ids:
        return
    shown = ", ".join(ids[:5]) + (f" and {len(ids) - 5} more" if len(ids) > 5 else "")
    result.warn(f"{xml.name}: {len(ids)} region(s) or line(s) have coordinates outside the "
                f"{width}x{height} image ({shown}); kept as they are, so check imageWidth/"
                "imageHeight or the coordinates")
    result.skipped["regions or lines outside the image (kept)"] += len(ids)


class PageXMLImporter:
    format_name = "page_xml"
    description = "PAGE XML (Transkribus, eScriptorium, OCR-D): line transcription or layout correction"
    file_extensions = [".xml"]

    @staticmethod
    def _is_page(path: Path) -> bool:
        try:
            with path.open("rb") as fh:
                head = fh.read(4096)
        except OSError:
            return False
        return b"PcGts" in head and b"primaresearch.org/PAGE" in head

    def _files(self, path: Path) -> List[Path]:
        if path.is_dir():
            return sorted(p for p in path.rglob("*.xml") if self._is_page(p))
        return [path] if path.is_file() and path.suffix.lower() == ".xml" else []

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if path.is_file():
            return path.suffix.lower() == ".xml" and self._is_page(path)
        return path.is_dir() and bool(self._files(path))

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = options or {}
        path = Path(path)
        mode = str(options.get("page_xml_mode") or "lines").lower()
        if mode not in MODES:
            raise ValueError(f"page_xml_mode must be one of {', '.join(MODES)}, not {mode!r}")
        files = self._files(path)
        if not files:
            raise ValueError(f"no PAGE XML files at {path}")
        root_dir = path if path.is_dir() else path.parent
        result = ProjectImportResult(source_format="PAGE XML", text_key="text")
        self._unmeasured: Dict[Path, str] = {}
        seen_ids: set = set()
        media_names: Dict[str, str] = {}
        labels: Dict[str, None] = {}

        for f in files:
            if not _dh.within(f, [root_dir]):
                result.warn(f"{f} is a link out of {root_dir}; left out")
                result.skipped["files outside the input folder"] += 1
                continue
            try:
                _root, page = parse_page_file(f)
            except ValueError as exc:
                result.warn(f"{exc}; left out")
                result.skipped["unreadable files"] += 1
                continue
            rel_xml = "page_xml/" + f.relative_to(root_dir).as_posix()
            result.media_files[rel_xml] = str(f)
            image_url, width, height = self._image(f, page, options, result, media_names, root_dir)
            stem = _dh.slug(f.stem, "page")
            if mode == "lines":
                self._lines(f, page, stem, rel_xml, image_url, width, height, result, seen_ids)
            else:
                self._layout(f, page, stem, rel_xml, image_url, width, height, result,
                             seen_ids, labels)

        if not result.items:
            raise ValueError(f"no {'text lines' if mode == 'lines' else 'pages'} found in {path}")
        if mode == "lines":
            result.text_key = "htr_text"
            result.schemes = [{
                "annotation_type": "text_edit", "name": LINE_SCHEME,
                "description": "Correct the transcription of this line",
                "source_field": "htr_text", "show_diff": True,
                "show_edit_distance": True, "allow_reset": True,
            }]
            result.instance_display = {"fields": [
                {"key": "line_image", "type": "image_region", "label": "Line"},
            ]}
        else:
            result.schemes = [{
                "annotation_type": "image_annotation", "name": LAYOUT_SCHEME,
                "description": "Correct the regions and text lines",
                "source_field": "image_url", "tools": ["polygon", "bbox"],
                "labels": list(labels) or ["text", LINE_LABEL],
                "zoom_enabled": True, "pan_enabled": True,
            }]
        return result

    # ------------------------------------------------------------------ helpers

    def _image(self, xml: Path, page, options: dict, result: ProjectImportResult,
               media_names: Dict[str, str], root_dir: Path) -> Tuple[str, int, int]:
        name = page.get("imageFilename") or ""
        width = int(float(page.get("imageWidth") or 0))
        height = int(float(page.get("imageHeight") or 0))
        found: Optional[Path] = None
        if name and not _dh.is_url(name):
            if name.startswith("file://"):
                name = unquote(urlparse(name).path)
            ref = Path(name)
            candidates = [xml.parent / ref, xml.parent.parent / ref,
                          xml.parent / ref.name, xml.parent.parent / ref.name]
            if options.get("image_dir"):
                candidates[:0] = [Path(options["image_dir"]) / ref, Path(options["image_dir"]) / ref.name]
            # Only inside the input folder (or the folder above a page/
            # folder, where Transkribus puts the images) and --image-dir: an
            # absolute or ../ name would copy any local file into media/.
            roots = [root_dir, Path(options["image_dir"]) if options.get("image_dir") else None]
            if xml.parent.name.lower() == "page":
                roots.append(xml.parent.parent)
            for r in roots:
                if r is not None and str(r) not in result.media_roots:
                    result.media_roots.append(str(r))
            existing = [c for c in candidates if c.is_file()]
            found = next((c for c in existing if _dh.within(c, roots)), None)
            if found is None and existing:
                _dh.refusal_warning(result, xml.name)(page.get("imageFilename") or name)
                return "", width, height
        if found is None:
            if _dh.is_url(name):
                return name, width, height
            result.warn(f"{xml.name}: image {name or '(none named)'} not found beside the XML "
                        "or in --image-dir; the item will show no image")
            result.skipped["pages whose image was not found"] += 1
            return "", width, height
        if not (width and height):
            size = probe_image_size(found)
            if size:
                width, height = size
            else:
                self._unmeasured[xml] = _dh.unmeasured_reason(found)
        media = found.name
        if media in media_names and media_names[media] != str(found):
            media = f"{_dh.slug(xml.parent.name)}-{found.name}"
        media_names[media] = str(found)
        rel = f"media/{media}"
        result.media_files[rel] = str(found)
        return f"/{rel}", width, height

    def _lines(self, xml: Path, page, stem: str, rel_xml: str, image_url: str,
               width: int, height: int, result: ProjectImportResult, seen: set) -> None:
        index = 0
        outside: List[str] = []
        for region in iter_regions(page):
            for line in region:
                if local(line.tag) != "TextLine":
                    continue
                points = coords_points(line)
                if len(points) < 2:
                    result.skipped["text lines without coordinates"] += 1
                    continue
                index += 1
                line_id = line.get("id") or f"l{index}"
                if outside_image(points, width, height):
                    outside.append(line_id)
                bbox = _dh.polygon_bbox(points)
                text = text_equiv(line)
                iid = _dh.unique_id(f"{stem}-{_dh.slug(line_id, 'line')}", seen)
                fields: Dict[str, Any] = {
                    "htr_text": text,
                    "line_image": {
                        "image": image_url, "width": width, "height": height,
                        "region": [round(v, 2) for v in bbox],
                        "polygon": [[round(x, 2), round(y, 2)] for x, y in points],
                    },
                    "page": xml.name,
                    "page_xml": rel_xml,
                    "region_id": region.get("id") or "",
                    "line_id": line_id,
                    "line_number": index,
                }
                baseline = baseline_points(line)
                if baseline:
                    fields["line_image"]["baseline"] = [[round(x, 2), round(y, 2)] for x, y in baseline]
                conf = next((e.get("conf") for e in line if local(e.tag) == "TextEquiv"), None)
                if conf:
                    fields["htr_confidence"] = conf
                result.items.append(ProjectItem(instance_id=iid, fields=fields))
        warn_outside(xml, outside, width, height, result)
        if index == 0:
            result.warn(f"{xml.name}: no text lines")

    def _layout(self, xml: Path, page, stem: str, rel_xml: str, image_url: str,
                width: int, height: int, result: ProjectImportResult, seen: set,
                labels: Dict[str, None]) -> None:
        from potato.export.cv_utils import to_client_object
        objects: List[dict] = []
        n_lines = 0
        outside: List[str] = []
        regions = iter_regions(page)
        if not (width and height):
            result.warn(f"{xml.name}: the page has no imageWidth/imageHeight and the image could "
                        f"not be measured ({self._unmeasured.get(xml, 'no image')}); its regions "
                        "were left out")
            result.skipped["pages of unknown size"] += 1
        else:
            for element in regions + [l for r in regions for l in r if local(l.tag) == "TextLine"]:
                points = coords_points(element)
                if len(points) < 3:
                    result.skipped["regions or lines with fewer than three points"] += 1
                    continue
                is_line = local(element.tag) == "TextLine"
                if outside_image(points, width, height):
                    outside.append(element.get("id") or local(element.tag))
                label = LINE_LABEL if is_line else region_label(element)
                labels[label] = None
                obj = to_client_object("polygon", label, img_w=width, img_h=height, points=points,
                                       provenance={"source": "import", "import_format": "page_xml"})
                if obj is None:
                    continue
                obj["attributes"] = {"page_xml_id": element.get("id") or "",
                                     "page_xml_element": local(element.tag)}
                objects.append(obj)
                n_lines += is_line
            warn_outside(xml, outside, width, height, result)
        iid = _dh.unique_id(stem, seen)
        fields = {"text": f"{xml.name}: {len(regions)} regions, {n_lines} text lines",
                  "image_url": image_url, "image_width": width, "image_height": height,
                  "page": xml.name, "page_xml": rel_xml}
        item = ProjectItem(instance_id=iid, fields=fields)
        if objects:
            item.predictions[LAYOUT_SCHEME] = objects
            item.prediction_sources[LAYOUT_SCHEME] = {"model": "imported page_xml"}
        result.items.append(item)
