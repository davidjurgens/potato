"""
W3C Web Annotation (JSON-LD) files as a Potato project.

Reads the shapes annotation tools publish (Recommendation of 2017-02-23):

* an ``AnnotationCollection`` with embedded ``AnnotationPage`` s (``first`` /
  ``next``, or ``items``), an ``AnnotationPage``, a JSON list of annotations
  or of pages, or one ``Annotation``;
* the Hypothesis API search response (``{"rows": [...]}``) and a list of
  Hypothesis annotations;
* IIIF Presentation 2 ``sc:AnnotationList`` / ``oa:Annotation`` (``resource``
  and ``on`` instead of ``body`` and ``target``).

What each annotation becomes:

=============================================  =================================
target                                         Potato
=============================================  =================================
``TextQuoteSelector`` / ``TextPositionSelector``  a span on the item's text
``FragmentSelector`` ``xywh=pixel:`` / ``percent:``  an ``image_annotation`` box
``SvgSelector`` polygon / polyline / rect / ...    a polygon, polyline, box, ellipse
the whole resource                             a radio / multiselect answer
                                               (``classifying`` / ``tagging``
                                               bodies) or a text answer
                                               (``describing`` / ``commenting``)
=============================================  =================================

A span needs the text it was drawn on. The importer looks for it in, in order:
``options["texts"]`` (a folder of text files named after the target's last
path segment, or a JSONL/JSON file of ``{"source" | "id" | "url": ..., "text":
...}`` rows), then the target's ``source`` when that is a local file. When the
position and the quote disagree, or the position is missing, the span is found
again by its quote, using ``prefix`` and ``suffix`` to pick between repeats.

Each annotation's ``creator`` is kept as that person's answer (written as
their saved work with ``--keep-annotators``), and every annotation also comes
in as a pre-annotation so a new annotator starts from them.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from potato.importers._common import IMAGE_EXTENSIONS, probe_image_size

from . import _dh
from .base import ProjectImportResult, ProjectItem
from .writer import safe_username

logger = logging.getLogger(__name__)

FORMAT = "web_annotation"
TAG_PURPOSES = {"tagging", "classifying", "identifying"}
TEXT_PURPOSES = {"describing", "commenting", "replying", "editing", "transcribing",
                 "supplementing", "highlighting", "assessing", "questioning"}
DEFAULT_SPAN_LABEL = "annotation"
DEFAULT_REGION_LABEL = "region"
#: A comment this short is taken as the label of an untagged region or span
#: (Mirador and Hypothesis users often type the label into the comment box).
MAX_LABEL_CHARS = 40
TEXT_SUFFIXES = {".txt", ".md", ".text", ".html", ".htm", ".xml", ""}


# ---------------------------------------------------------------------------
# Normalized annotation
# ---------------------------------------------------------------------------

@dataclass
class Anno:
    id: str
    source: str
    fragment: Optional[str] = None
    selectors: List[dict] = field(default_factory=list)
    #: (purpose, value) pairs; purpose "" when the body did not say.
    bodies: List[Tuple[str, str]] = field(default_factory=list)
    motivation: str = ""
    creator: Optional[str] = None
    creator_is_software: bool = False
    schema: Optional[str] = None
    instance: Optional[str] = None
    target_field: Optional[str] = None

    # -- what kind of target --------------------------------------------
    def selector(self, kind: str) -> Optional[dict]:
        return next((s for s in self.selectors if s["type"] == kind), None)

    @property
    def is_text(self) -> bool:
        return bool(self.selector("TextQuoteSelector") or self.selector("TextPositionSelector"))

    @property
    def is_region(self) -> bool:
        if self.is_text:
            return False
        frag = self.selector("FragmentSelector")
        return bool(self.selector("SvgSelector") or self.selector("PointSelector")
                    or (frag and _dh.parse_xywh(frag.get("value", "")))
                    or (self.fragment and _dh.parse_xywh(self.fragment)))

    # -- what it says ---------------------------------------------------
    @property
    def tags(self) -> List[str]:
        return [v for p, v in self.bodies if v and p in TAG_PURPOSES]

    @property
    def comments(self) -> List[str]:
        return [v for p, v in self.bodies if v and p not in TAG_PURPOSES]

    def label(self, default: str) -> str:
        if self.tags:
            return self.tags[0]
        short = [c for c in self.comments if len(c) <= MAX_LABEL_CHARS and "\n" not in c]
        return short[0] if short else default


def _types(node: dict) -> List[str]:
    raw = node.get("type", node.get("@type"))
    values = raw if isinstance(raw, list) else [raw]
    return [str(v).split(":", 1)[-1] for v in values if v]


def _id(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return str(node.get("id") or node.get("@id") or "")
    return ""


def _strip_html(text: str) -> str:
    if "<" not in text:
        return text.strip()
    from potato.server_utils.span_text import markup_text
    return _dh.normalize_space(markup_text(text))


def _flatten_selectors(selector: Any, out: List[dict]) -> None:
    if isinstance(selector, list):
        for s in selector:
            _flatten_selectors(s, out)
        return
    if not isinstance(selector, dict):
        return
    kinds = _types(selector)
    kind = kinds[0] if kinds else ""
    if kind == "Choice":          # IIIF 2: oa:Choice of default/item selectors
        _flatten_selectors(selector.get("default"), out)
        _flatten_selectors(selector.get("item"), out)
        return
    entry = dict(selector)
    entry["type"] = kind
    if kind == "SvgSelector" and not entry.get("value") and entry.get("chars"):
        entry["value"] = entry["chars"]
    out.append(entry)
    _flatten_selectors(selector.get("refinedBy"), out)


def _bodies(raw: Any, motivation: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    default = motivation if motivation else ""
    for body in raw if isinstance(raw, list) else [raw]:
        if body is None:
            continue
        if isinstance(body, str):
            out.append((default or "tagging", _dh.iri_tail(body) if _dh.is_url(body) else body))
            continue
        if not isinstance(body, dict):
            continue
        kinds = _types(body)
        purpose = body.get("purpose", "")
        if isinstance(purpose, list):
            purpose = purpose[0] if purpose else ""
        purpose = str(purpose).split(":", 1)[-1] if purpose else default
        if "Choice" in kinds:
            out.extend(_bodies(body.get("items"), motivation))
            continue
        if "SpecificResource" in kinds and body.get("source"):
            out.append((purpose or "tagging", _dh.iri_tail(_id(body["source"]))))
            continue
        value = body.get("value", body.get("chars"))
        if value is None:
            continue
        value = _strip_html(str(value))
        if value:
            out.append((purpose, value))
    return out


def _creator(raw: Any) -> Tuple[Optional[str], bool]:
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None, False
    if isinstance(raw, str):
        name = raw
        software = False
    elif isinstance(raw, dict):
        software = bool({"Software", "SoftwareAgent", "Application"} & set(_types(raw)))
        name = (raw.get("nickname") or raw.get("name") or raw.get("foaf:nick")
                or _dh.iri_tail(_id(raw)) or "")
        if isinstance(name, list):
            name = name[0] if name else ""
    else:
        return None, False
    name = str(name)
    if name.startswith("acct:"):            # Hypothesis: acct:alice@hypothes.is
        name = name[len("acct:"):].split("@", 1)[0]
    elif "/" in name or name.startswith("urn:"):
        name = _dh.iri_tail(name)
    return (name or None), software


def _from_w3c(node: dict, result: ProjectImportResult) -> List[Anno]:
    motivation = node.get("motivation", "")
    if isinstance(motivation, list):
        motivation = motivation[0] if motivation else ""
    motivation = str(motivation).split(":", 1)[-1]
    body_raw = node.get("body", node.get("resource"))
    if body_raw is None and node.get("bodyValue") is not None:
        body_raw = {"type": "TextualBody", "value": node["bodyValue"]}
    bodies = _bodies(body_raw, motivation)
    creator, software = _creator(node.get("creator", node.get("annotatedBy")))
    targets = node.get("target", node.get("on"))
    if targets is None:
        result.skipped["annotations without a target"] += 1
        return []
    out = []
    for target in targets if isinstance(targets, list) else [targets]:
        anno = Anno(id=_id(node), source="", bodies=list(bodies), motivation=motivation,
                    creator=creator, creator_is_software=software,
                    schema=node.get("potato:schema"), instance=node.get("potato:instance"))
        if isinstance(target, str):
            anno.source = target
        elif isinstance(target, dict):
            src = target.get("source", target.get("full"))
            if src is None and not target.get("selector"):
                src = target            # a Canvas or other resource given whole
            anno.source = _id(src)
            _flatten_selectors(target.get("selector"), anno.selectors)
            anno.target_field = target.get("potato:field")
        else:
            continue
        if "#" in anno.source:
            anno.source, anno.fragment = anno.source.split("#", 1)
        if not anno.source:
            result.skipped["annotations without a target"] += 1
            continue
        out.append(anno)
    return out


def _from_hypothesis(row: dict) -> List[Anno]:
    bodies = [("tagging", str(t)) for t in row.get("tags") or [] if t]
    if row.get("text"):
        bodies.append(("commenting", _strip_html(str(row["text"]))))
    creator, _ = _creator(row.get("user"))
    out = []
    for target in row.get("target") or [{"source": row.get("uri", "")}]:
        if not isinstance(target, dict):
            continue
        anno = Anno(id=str(row.get("id", "")), source=str(target.get("source") or row.get("uri") or ""),
                    bodies=list(bodies), motivation="commenting", creator=creator)
        _flatten_selectors(target.get("selector"), anno.selectors)
        if anno.source:
            out.append(anno)
    return out


def _is_hypothesis_row(node: dict) -> bool:
    return ("uri" in node and "target" in node and not _types(node)
            and any(k in node for k in ("user", "tags", "text", "permissions")))


def collect_annotations(doc: Any, result: ProjectImportResult,
                        base_dir: Optional[Path] = None,
                        allow_fetch: bool = False, _depth: int = 0) -> List[Anno]:
    """Every annotation in a collection, page, list or single annotation."""
    if _depth > 50:
        return []
    out: List[Anno] = []
    if isinstance(doc, list):
        for node in doc:
            out.extend(collect_annotations(node, result, base_dir, allow_fetch, _depth + 1))
        return out
    if not isinstance(doc, dict):
        return out
    if isinstance(doc.get("rows"), list):                       # Hypothesis search API
        for row in doc["rows"]:
            if isinstance(row, dict):
                out.extend(_from_hypothesis(row))
        return out
    if _is_hypothesis_row(doc):
        return _from_hypothesis(doc)
    kinds = set(_types(doc))
    if kinds & {"AnnotationCollection", "AnnotationPage", "AnnotationList", "Layer"}:
        for key in ("items", "resources"):
            out.extend(collect_annotations(doc.get(key) or [], result, base_dir, allow_fetch, _depth + 1))
        for key in ("first", "next"):
            ref = doc.get(key)
            if isinstance(ref, dict) and (ref.get("items") or ref.get("resources")):
                out.extend(collect_annotations(ref, result, base_dir, allow_fetch, _depth + 1))
            elif ref:
                loaded = load_reference(_id(ref), result, base_dir, allow_fetch)
                if loaded is not None:
                    out.extend(collect_annotations(loaded, result, base_dir, allow_fetch, _depth + 1))
        return out
    if kinds & {"Annotation"} or ("target" in doc and "body" in doc) or ("on" in doc and "resource" in doc):
        return _from_w3c(doc, result)
    return out


def load_reference(ref: str, result: ProjectImportResult, base_dir: Optional[Path],
                   allow_fetch: bool) -> Optional[Any]:
    """A referenced (not embedded) page: a local file, or a URL when fetching is allowed."""
    if not ref:
        return None
    path = _dh.local_path(ref, base_dir,
                          refused=_dh.refusal_warning(result, "annotation page reference"))
    if path is None and base_dir is not None and _dh.is_url(ref):
        # A page published beside the document: try its file name locally.
        candidate = Path(base_dir) / _dh.iri_tail(ref)
        path = candidate if candidate.is_file() and _dh.within(candidate, [base_dir]) else None
    if path is not None:
        try:
            return _dh.read_json(path)
        except ValueError as exc:
            result.warn(str(exc))
            return None
    if allow_fetch and _dh.is_url(ref):
        try:
            return _dh.fetch_json(ref)
        except ValueError as exc:
            result.warn(str(exc))
            return None
    result.warn(f"annotation page {ref} is referenced, not embedded, and was not "
                "fetched; save it beside the file to include it")
    result.skipped["referenced annotation pages not read"] += 1
    return None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def region_object(anno: Anno, width: float, height: float,
                  label: str) -> Tuple[Optional[dict], str]:
    """The client-shaped object for a region annotation, or (None, reason)."""
    from potato.export.cv_utils import to_client_object
    known = bool(width and height and width > 0 and height > 0)
    provenance = {"source": "import", "import_format": FORMAT}

    svg = anno.selector("SvgSelector")
    if svg is not None:
        shape = _dh.parse_svg(svg.get("value", ""))
        if shape is None:
            return None, "SVG selectors with no polygon, polyline, rect, circle, ellipse or path"
        w, h = (width, height) if known else (shape["viewbox"] or (0, 0))
        if not (w and h):
            return None, "SVG selectors on an image of unknown size"
        kind = shape["kind"]
        if kind == "bbox":
            return to_client_object("bbox", label, img_w=w, img_h=h, bbox=shape["bbox"],
                                    provenance=provenance), ""
        if kind == "ellipse":
            return to_client_object("ellipse", label, img_w=w, img_h=h, ellipse=shape["ellipse"],
                                    provenance=provenance), ""
        return to_client_object(kind, label, img_w=w, img_h=h, points=shape["points"],
                                provenance=provenance), ""

    frag = anno.selector("FragmentSelector")
    parsed = _dh.parse_xywh(frag.get("value", "")) if frag else None
    if parsed is None and anno.fragment:
        parsed = _dh.parse_xywh(anno.fragment)
    if parsed is not None:
        unit, x, y, w, h = parsed
        if unit == "percent":
            return to_client_object("bbox", label, img_w=100.0, img_h=100.0, bbox=[x, y, w, h],
                                    provenance=provenance), ""
        if not known:
            return None, "pixel regions on an image of unknown size"
        return to_client_object("bbox", label, img_w=width, img_h=height, bbox=[x, y, w, h],
                                provenance=provenance), ""

    point = anno.selector("PointSelector")
    if point is not None and known:
        try:
            pts = [[float(point["x"]), float(point["y"])]]
        except (KeyError, TypeError, ValueError):
            return None, "point selectors without x and y"
        return to_client_object("landmark", label, img_w=width, img_h=height, points=pts,
                                provenance=provenance), ""
    return None, "regions of an unsupported shape"


def svg_viewbox(annos: Iterable[Anno]) -> Optional[Tuple[float, float]]:
    """The image size an SVG selector in this group states, if any does."""
    for anno in annos:
        svg = anno.selector("SvgSelector")
        if svg is not None:
            shape = _dh.parse_svg(svg.get("value", ""))
            if shape and shape.get("viewbox"):
                return shape["viewbox"]
    return None


# ---------------------------------------------------------------------------
# Text and image lookup
# ---------------------------------------------------------------------------

class SourceIndex:
    """What ``options["texts"]`` says about each target: its text, image, size."""

    KEYS = ("source", "iri", "uri", "url", "id", "instance_id")

    def __init__(self, spec: Optional[str], base_dir: Optional[Path]):
        self.rows: Dict[str, dict] = {}
        self.base_dir = base_dir
        #: Files in a texts folder that link out of it; not read.
        self.outside: List[str] = []
        if not spec:
            return
        path = Path(spec)
        if not path.exists() and base_dir is not None and (Path(base_dir) / spec).exists():
            path = Path(base_dir) / spec
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES:
                    if not _dh.within(f, [path]):
                        self.outside.append(str(f.relative_to(path)))
                        continue
                    row = {"text": f.read_text(encoding="utf-8-sig", errors="replace")}
                    self.rows.setdefault(f.name, row)
                    self.rows.setdefault(f.stem, row)
        elif path.is_file():
            raw = path.read_text(encoding="utf-8-sig")
            if path.suffix.lower() == ".jsonl":
                rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            else:
                data = json.loads(raw)
                rows = data if isinstance(data, list) else [data]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for key in self.KEYS:
                    if row.get(key) not in (None, ""):
                        self.rows.setdefault(str(row[key]), row)
        else:
            raise ValueError(f"texts: {spec} is not a file or a folder")

    def lookup(self, source: str, instance: Optional[str] = None) -> Optional[dict]:
        tail = _dh.iri_tail(source)
        for key in (source, instance, tail, Path(tail).stem if tail else None):
            if key and key in self.rows:
                return self.rows[key]
        return None


def _image_like(reference: str) -> bool:
    return Path(_dh.iri_tail(reference)).suffix.lower() in IMAGE_EXTENSIONS + (".gif", ".svg")


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------

class WebAnnotationImporter:
    format_name = FORMAT
    description = "W3C Web Annotation JSON-LD (Annotorious, Mirador, Hypothesis exports)"
    file_extensions = [".json", ".jsonld"]

    def _files(self, path: Path) -> List[Path]:
        exts = tuple(self.file_extensions)
        if path.is_dir():
            return sorted(p for p in path.iterdir() if p.suffix.lower() in exts)
        return [path] if path.is_file() and path.suffix.lower() in exts else []

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in self.file_extensions:
            return False
        try:
            with path.open(encoding="utf-8-sig") as fh:
                head = fh.read(65536)
        except (OSError, UnicodeDecodeError):
            return False
        if re.search(r'"(?:type|@type)"\s*:\s*"(?:sc:)?Manifest"', head):
            return False            # a IIIF manifest: the iiif importer
        if "w3.org/ns/anno.jsonld" in head or "www.w3.org/ns/oa" in head:
            return True
        if re.search(r'"(?:type|@type)"\s*:\s*"(?:oa:)?(?:Annotation|AnnotationCollection|AnnotationPage)"', head):
            return True
        return '"rows"' in head and "hypothes.is" in head

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = options or {}
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no .json / .jsonld files at {path}")
        result = ProjectImportResult(source_format="W3C Web Annotation", text_key="text")
        base_dir = path if path.is_dir() else path.parent
        annos: List[Anno] = []
        for f in files:
            annos.extend(collect_annotations(_dh.read_json(f), result, f.parent,
                                             allow_fetch=bool(options.get("allow_fetch"))))
        if not annos:
            raise ValueError(f"{path} holds no Web Annotations")
        build_project(annos, result, base_dir, options)
        return result


def _roots(base_dir: Optional[Path], options: dict) -> List[Optional[Path]]:
    """Where local files may come from: the input folder, --image-dir, texts."""
    roots: List[Optional[Path]] = [base_dir]
    if options.get("image_dir"):
        roots.append(Path(options["image_dir"]))
    texts = options.get("texts")
    if texts:
        spec = Path(texts)
        if not spec.exists() and base_dir is not None:
            spec = Path(base_dir) / texts
        roots.append(spec if spec.is_dir() else spec.parent)
    return roots


def build_project(annos: List[Anno], result: ProjectImportResult, base_dir: Optional[Path],
                  options: dict) -> None:
    """Group annotations by what they target and turn each group into an item."""
    index = SourceIndex(options.get("texts"), base_dir)
    for name in index.outside:
        result.warn(f"texts: {name} links to a file outside the texts folder; not read")
        result.skipped["files outside the input folder"] += 1
    result.media_roots = [str(r) for r in _roots(base_dir, options) if r is not None]
    groups: Dict[str, List[Anno]] = defaultdict(list)
    order: List[str] = []
    for anno in annos:
        key = anno.instance or anno.source
        if key not in groups:
            order.append(key)
        groups[key].append(anno)

    builder = _SchemeBuilder()
    seen_ids: set = set()
    for key in order:
        group = groups[key]
        source = group[0].source
        instance_id = _dh.unique_id(_dh.slug(group[0].instance or _dh.iri_tail(source), "item"),
                                    seen_ids)
        item = ProjectItem(instance_id=instance_id, fields={"text": "", "source": source})
        row = index.lookup(source, group[0].instance) or {}
        if row:
            for k, v in row.items():
                if k not in ("text", "id") and k not in item.fields and not isinstance(v, (dict, list)):
                    item.fields[k] = v

        text_annos = [a for a in group if a.is_text]
        region_annos = [a for a in group if a.is_region]
        whole = [a for a in group if not a.is_text and not a.is_region]

        if text_annos:
            raw = row.get("text") if isinstance(row.get("text"), str) else None
            if raw is None:
                local = _dh.local_path(source, base_dir, roots=_roots(base_dir, options),
                                       refused=_dh.refusal_warning(result, f"text of {instance_id}"))
                if local is not None and local.suffix.lower() in TEXT_SUFFIXES:
                    raw = local.read_text(encoding="utf-8-sig", errors="replace")
            if raw is None:
                result.warn(f"no text for {source}: pass texts (a folder or JSONL of the "
                            "annotated documents); its text annotations were left out")
                result.skipped["text annotations whose document was not found"] += len(text_annos)
            else:
                dom = _add_spans(item, text_annos, raw, builder, result)
                item.fields["text"] = dom

        if region_annos:
            _add_regions(item, region_annos, source, row, base_dir, builder, result, options)
            if not item.fields["text"]:
                item.fields["text"] = str(row.get("label") or _dh.iri_tail(source))

        for anno in whole:
            _warn_unplaced_fragment(anno, source, result)
            builder.add_whole(item, anno, result)

        if not item.predictions and not item.fields.get("image_url"):
            continue
        if not item.fields["text"]:
            item.fields["text"] = _dh.iri_tail(source)
        result.items.append(item)

    builder.finish(result)


_TIME_FRAGMENT = re.compile(r"(?:^|[&#])t=(?:npt:)?([^&]*)")


def _warn_unplaced_fragment(anno: Anno, source: str, result: ProjectImportResult) -> None:
    """A whole-item annotation whose target named a part Potato can't place.

    Its tags and comments are still imported onto the item, but the part
    they were about is gone, so say which.
    """
    frag = anno.selector("FragmentSelector")
    values = [v for v in ((frag or {}).get("value"), anno.fragment) if v]
    for value in values:
        value = str(value)
        time = _TIME_FRAGMENT.search(value)
        if time:
            result.warn(f"{source}: annotation {anno.id or '(no id)'} targets the time range "
                        f"t={time.group(1)}; Potato imports it as a note on the whole item, "
                        "without the range")
            result.skipped["time ranges imported as whole-item notes"] += 1
            return
        if "xywh=" in value:
            result.warn(f"{source}: annotation {anno.id or '(no id)'} has an unreadable region "
                        f"{value!r} (xywh= needs four numbers, with a width and height above 0); "
                        "imported as a note on the whole item, without the region")
            result.skipped["regions with an unreadable xywh"] += 1
            return


def _span_basis(raw: str):
    dom, remap = _dh.rendered_text(raw)
    return dom, remap


def _add_spans(item: ProjectItem, annos: List[Anno], raw: str, builder: "_SchemeBuilder",
               result: ProjectImportResult) -> str:
    dom, remap = _span_basis(raw)
    for anno in annos:
        quote = anno.selector("TextQuoteSelector")
        position = anno.selector("TextPositionSelector")
        found = _resolve_span(raw, dom, remap, quote, position)
        if found is None:
            what = (quote or {}).get("exact") or position
            result.warn(f"{item.instance_id}: could not find the span {what!r} in its text; left out")
            result.skipped["text annotations not found in their text"] += 1
            continue
        start, end = found
        label = anno.label(DEFAULT_SPAN_LABEL)
        builder.add_span(item, anno, {"start": start, "end": end, "label": label})
    return dom


def _resolve_span(raw: str, dom: str, remap, quote: Optional[dict],
                  position: Optional[dict]) -> Optional[Tuple[int, int]]:
    """Offsets into the RENDERED text, from a quote and/or a position.

    A position may count the source text (most tools) or the rendered text
    (Potato's own export); the quote says which, so both are tried.
    """
    pos = None
    if position is not None:
        try:
            pos = (int(position["start"]), int(position["end"]))
        except (KeyError, TypeError, ValueError):
            pos = None
    exact = (quote or {}).get("exact") or ""
    prefix = (quote or {}).get("prefix") or ""
    suffix = (quote or {}).get("suffix") or ""
    bases = [(raw, remap), (dom, lambda o: o)] if raw != dom else [(dom, lambda o: o)]

    if pos is not None and 0 <= pos[0] < pos[1]:
        for text, to_dom in bases:
            if pos[1] <= len(text) and (not exact or text[pos[0]:pos[1]] == exact):
                return to_dom(pos[0]), to_dom(pos[1])
    if exact:
        for text, to_dom in bases:
            hit = _dh.locate_quote(text, exact, prefix, suffix, hint=pos[0] if pos else None)
            if hit is not None:
                return to_dom(hit[0]), to_dom(hit[1])
        # The quote's own whitespace may differ from the text's.
        loose = _dh.normalize_space(exact)
        if loose and loose != exact:
            hit = _dh.locate_quote(dom, loose, _dh.normalize_space(prefix)[-32:],
                                   _dh.normalize_space(suffix)[:32])
            if hit is not None:
                return hit
        return None
    if pos is not None and pos[1] <= len(raw) and pos[0] < pos[1]:
        return remap(pos[0]), remap(pos[1])
    return None


def _add_regions(item: ProjectItem, annos: List[Anno], source: str, row: dict,
                 base_dir: Optional[Path], builder: "_SchemeBuilder",
                 result: ProjectImportResult, options: dict) -> None:
    image = row.get("image") or row.get("image_url") or source
    width = _number(row.get("width") or row.get("image_width"))
    height = _number(row.get("height") or row.get("image_height"))
    roots = _roots(base_dir, options)
    local = _dh.local_path(str(image), base_dir, roots=roots,
                           refused=_dh.refusal_warning(result, f"image of {item.instance_id}"))
    if local is None and options.get("image_dir"):
        candidate = Path(options["image_dir"]) / _dh.iri_tail(str(image))
        local = candidate if candidate.is_file() and _dh.within(candidate, roots) else None
    if local is not None:
        rel = f"media/{local.name}"
        result.media_files[rel] = str(local)
        url = f"/{rel}"
        if not (width and height):
            size = probe_image_size(local)
            if size:
                width, height = size
    else:
        url = str(image)
    if not (width and height):
        vb = svg_viewbox(annos)
        if vb:
            width, height = vb
    unmeasured = "" if (width and height) else _dh.unmeasured_reason(local)
    item.fields["image_url"] = url
    if width and height:
        item.fields["image_width"] = int(round(width))
        item.fields["image_height"] = int(round(height))
    for anno in annos:
        obj, reason = region_object(anno, width or 0, height or 0, anno.label(DEFAULT_REGION_LABEL))
        if obj is None:
            result.skipped[reason] += 1
            if "unknown size" in reason:
                result.warn(f"{source}: the image size is unknown ({unmeasured}), so pixel "
                            "regions could not be placed; give width/height in texts rows, "
                            "install Pillow, or pass --image-dir")
            continue
        builder.add_region(item, anno, obj)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ---------------------------------------------------------------------------
# Schemes
# ---------------------------------------------------------------------------

_TOOL_BY_TYPE = {"bbox": "bbox", "polygon": "polygon", "polyline": "polyline",
                 "ellipse": "ellipse", "landmark": "landmark", "freeform": "freeform"}


class _SchemeBuilder:
    """Collects scheme names, kinds and labels while items are built."""

    def __init__(self):
        self.kinds: Dict[str, str] = {}
        self.labels: Dict[str, Dict[str, None]] = defaultdict(dict)
        self.tools: Dict[str, Dict[str, None]] = defaultdict(dict)
        self.multi: set = set()
        self.order: List[str] = []

    def _name(self, wanted: Optional[str], kind: str, default: str) -> str:
        name = wanted or default
        while name in self.kinds and self.kinds[name] != kind:
            name = f"{name}_{kind}"
        if name not in self.kinds:
            self.kinds[name] = kind
            self.order.append(name)
        return name

    @staticmethod
    def _who(item: ProjectItem, anno: Anno) -> Optional[str]:
        if anno.creator and not anno.creator_is_software:
            return safe_username(anno.creator)
        return None

    def _record(self, item: ProjectItem, anno: Anno, name: str, value: Any, as_list: bool):
        targets = [item.predictions]
        who = self._who(item, anno)
        if who:
            targets.append(item.responses.setdefault(who, {}))
            item.fields.setdefault("_annotators", set()).add((who, anno.creator))
        for store in targets:
            if as_list:
                bucket = store.setdefault(name, [])
                if value not in bucket:
                    bucket.append(value)
            else:
                store[name] = value
        if anno.creator_is_software and anno.creator:
            item.prediction_sources[name] = {"model": anno.creator}
        else:
            item.prediction_sources.setdefault(name, {"model": f"imported {FORMAT}"})

    def add_span(self, item, anno, span):
        name = self._name(anno.schema, "span", "spans")
        self.labels[name][span["label"]] = None
        self._record(item, anno, name, span, as_list=True)

    def add_region(self, item, anno, obj):
        name = self._name(anno.schema, "image_annotation", "regions")
        self.labels[name][obj["label"]] = None
        self.tools[name][_TOOL_BY_TYPE.get(obj["type"], "polygon")] = None
        self._record(item, anno, name, obj, as_list=True)

    def add_whole(self, item, anno, result):
        tags = anno.tags
        if tags:
            name = self._name(anno.schema, "choice", "classification")
            for tag in tags:
                self.labels[name][tag] = None
                self._record(item, anno, name, tag, as_list=True)
            return
        comments = anno.comments
        if comments:
            name = self._name(anno.schema, "text", "comment")
            self._record(item, anno, name, "\n\n".join(comments), as_list=False)
            return
        result.skipped["annotations with no body Potato can read"] += 1

    def finish(self, result: ProjectImportResult) -> None:
        # A choice is a multiselect when one person (or, for an item nobody
        # signed, the file itself) gave several answers; two people giving one
        # answer each disagree, which is what a radio records.
        for item in result.items:
            stores = list(item.responses.values()) or [item.predictions]
            for store in stores:
                for name, value in store.items():
                    if self.kinds.get(name) == "choice" and len(value) > 1:
                        self.multi.add(name)
        for name in self.order:
            kind = self.kinds[name]
            labels = list(self.labels[name])
            if kind == "span":
                result.schemes.append({"annotation_type": "span", "name": name,
                                       "description": "Check and correct the imported spans",
                                       "labels": labels or [DEFAULT_SPAN_LABEL]})
            elif kind == "image_annotation":
                result.schemes.append({"annotation_type": "image_annotation", "name": name,
                                       "description": "Check and correct the imported regions",
                                       "source_field": "image_url",
                                       "tools": list(self.tools[name]) or ["bbox", "polygon"],
                                       "labels": labels or [DEFAULT_REGION_LABEL],
                                       "zoom_enabled": True, "pan_enabled": True})
            elif kind == "choice":
                multi = name in self.multi
                result.schemes.append({"annotation_type": "multiselect" if multi else "radio",
                                       "name": name, "description": _humanize(name),
                                       "labels": labels})
            elif kind == "text":
                result.schemes.append({"annotation_type": "text", "name": name,
                                       "description": _humanize(name), "multiline": True})
        # Choice answers were collected as lists; a radio answer is one name.
        radios = {s["name"] for s in result.schemes if s["annotation_type"] == "radio"}
        for item in result.items:
            for store in [item.predictions, *item.responses.values()]:
                for name in radios & set(store):
                    if isinstance(store[name], list):
                        store[name] = store[name][0] if store[name] else ""
            people = item.fields.pop("_annotators", set())
            for who, raw in people:
                result.annotator_ids.setdefault(who, raw)
        most = max((len(item.responses) for item in result.items), default=0)
        result.annotations_per_item = most or None


def _humanize(name: str) -> str:
    from .base import humanize
    return humanize(name)
