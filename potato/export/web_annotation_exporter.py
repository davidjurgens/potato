"""
W3C Web Annotation Exporter

Writes every annotation as a W3C Web Annotation (JSON-LD, Recommendation of
2017-02-23) in one ``AnnotationCollection``: the interchange format that IIIF
viewers (Mirador, Universal Viewer), Annotorious, Hypothesis and most digital
humanities tools read.

* a text span: a ``SpecificResource`` with a ``TextQuoteSelector`` (the
  marked words plus 32 characters of context each side) refined by a
  ``TextPositionSelector`` (code-point offsets);
* a region on an image: a ``FragmentSelector`` (``xywh=pixel:`` when the
  image's size is known, ``xywh=percent:`` otherwise) for a box, an
  ``SvgSelector`` for a polygon or polyline;
* an answer to a question (radio, multiselect, likert, text, number, ...):
  a ``TextualBody`` on the whole item, ``purpose: classifying`` for a chosen
  option and ``describing`` for free text.

The target of each annotation is the item: its ``url`` / media field when it
has one, else ``urn:potato:<task>:<instance id>``. Pass ``base_iri`` in the
options to mint ``<base_iri><instance id>`` instead. ``creator`` is the
annotator's Potato user id.

A region's target is its image. A local image (``/media/page1.png``) is
written relative to the project folder (``media/page1.png``), with a warning;
pass ``media_base_url`` (``https://annotate.example.org/``) to write
``<media_base_url>media/page1.png``.

Output: ``web_annotations.jsonld``.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

CONTEXT = ["http://www.w3.org/ns/anno.jsonld",
           {"potato": "https://potatoannotator.com/ns#"}]
CONTEXT_CHARS = 32

#: Labels a scheme stores free text under, not an option name.
_FREE_TEXT_LABELS = {"text_box", "textbox", "free_response", "text"}
_NUMERIC_TYPES = {"slider", "number", "vas", "range_slider"}


_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "potato")).strip("-") or "potato"


class WebAnnotationExporter(BaseExporter):
    format_name = "web_annotation"
    description = "W3C Web Annotation JSON-LD (IIIF viewers, Annotorious, Hypothesis)"
    file_extensions = [".jsonld"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    # ------------------------------------------------------------------

    def _source(self, context: ExportContext, instance_id: str, options: dict) -> str:
        base = options.get("base_iri")
        if base:
            return f"{base}{instance_id}"
        item = context.items.get(instance_id) or {}
        for key in ("url", "source_url", "iri"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        task = _slug((context.config or {}).get("annotation_task_name"))
        return f"urn:potato:{task}:{instance_id}"

    def _media_source(self, context: ExportContext, instance_id: str, schema: dict,
                      fallback: str, options: Optional[dict] = None,
                      relative: Optional[List[str]] = None) -> str:
        item = context.items.get(instance_id) or {}
        field = (schema or {}).get("source_field")
        value = item.get(field) if field else None
        if not value:
            from .cv_utils import get_image_filename
            value = get_image_filename(item, context.config)
        if not (isinstance(value, str) and value):
            return fallback
        if _ABSOLUTE_IRI.match(value):
            return value
        # A server path ("/media/page1.png") is not an IRI: a JSON-LD reader
        # resolves it against the file's own location. With media_base_url
        # it becomes absolute; without, it is written relative to the
        # project folder ("media/page1.png") and the export warns.
        path = value.lstrip("/")
        base = (options or {}).get("media_base_url")
        if base:
            return str(base).rstrip("/") + "/" + path
        if relative is not None:
            relative.append(path)
        return path

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        os.makedirs(output_path, exist_ok=True)
        schemas = {s.get("name"): s for s in context.schemas or []}
        items: List[Dict[str, Any]] = []
        skipped: Dict[str, int] = {}
        counter = 0
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        task = _slug((context.config or {}).get("annotation_task_name"))

        def created_at(ann_rec: dict, schema_name: str, span: Optional[dict] = None) -> str:
            # When the answer was last changed, from the record's change trail
            # (for a span, the annotation history); the export time only when
            # neither has anything for it.
            stamps = [c.get("timestamp") for c in ann_rec.get("_changes") or []
                      if isinstance(c, dict) and c.get("schema_name") == schema_name
                      and isinstance(c.get("timestamp"), (int, float))]
            if span is not None:
                when = (ann_rec.get("_span_times") or {}).get(
                    f"{schema_name}:{span.get('start')}:{span.get('end')}")
                if isinstance(when, (int, float)):
                    stamps = [when]
            if not stamps:
                return now
            ts = max(stamps)
            ts = ts / 1000.0 if ts > 1e11 else ts       # milliseconds, from older records
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        def add(ann_rec: dict, target: Any, body: Any, motivation: str, schema_name: str,
                span: Optional[dict] = None):
            nonlocal counter
            counter += 1
            items.append({
                "id": f"urn:potato:{task}:annotation:{counter}",
                "type": "Annotation",
                "motivation": motivation,
                "creator": {"id": f"urn:potato:{task}:user:{ann_rec.get('user_id', '')}",
                            "type": "Person", "nickname": ann_rec.get("user_id", "")},
                "created": created_at(ann_rec, schema_name, span),
                "generator": {"type": "Software", "name": "Potato"},
                "body": body,
                "target": target,
                "potato:schema": schema_name,
                "potato:instance": ann_rec.get("instance_id", ""),
            })

        relative_media: List[str] = []
        for ann in context.annotations:
            iid = str(ann.get("instance_id", ""))
            source = self._source(context, iid, options)

            for schema_name, spans in (ann.get("spans") or {}).items():
                for span in spans or []:
                    try:
                        start, end = int(span.get("start")), int(span.get("end"))
                    except (TypeError, ValueError):
                        skipped["spans without offsets"] = skipped.get("spans without offsets", 0) + 1
                        continue
                    exact = context.covered_text(iid, span)
                    full = self._anchor_text(context, iid, span)
                    quote = {"type": "TextQuoteSelector", "exact": exact}
                    if full is not None:
                        quote["prefix"] = full[max(0, start - CONTEXT_CHARS):start]
                        quote["suffix"] = full[end:end + CONTEXT_CHARS]
                    quote["refinedBy"] = {"type": "TextPositionSelector", "start": start, "end": end}
                    target = {"type": "SpecificResource", "source": source, "selector": quote}
                    if span.get("target_field"):
                        target["potato:field"] = span["target_field"]
                    label = span.get("name") or span.get("label") or ""
                    add(ann, target, {"type": "TextualBody", "purpose": "tagging", "value": label},
                        "tagging", schema_name, {"start": start, "end": end})

            for schema_name, objects in (ann.get("image_annotations") or {}).items():
                schema = schemas.get(schema_name, {})
                media = self._media_source(context, iid, schema, source, options, relative_media)
                for obj in objects or []:
                    target = self._region_target(context, iid, obj, media)
                    if target is None:
                        skipped["image regions of an unsupported shape"] = \
                            skipped.get("image regions of an unsupported shape", 0) + 1
                        continue
                    add(ann, target, {"type": "TextualBody", "purpose": "tagging",
                                      "value": obj.get("label", "")}, "tagging", schema_name)

            for schema_name, labels in (ann.get("labels") or {}).items():
                schema = schemas.get(schema_name)
                if schema is None or not isinstance(labels, dict):
                    continue
                atype = schema.get("annotation_type", "")
                if atype in ("span", "image_annotation"):
                    continue
                bodies = []
                for label, value in labels.items():
                    if value in (None, "", False):
                        continue
                    if isinstance(value, (dict, list)) or (isinstance(value, str) and value[:1] in "[{"):
                        # A structured answer (a tiered annotation, a trace
                        # rubric) has no Web Annotation shape; skipped and counted.
                        skipped[f"{atype} answers"] = skipped.get(f"{atype} answers", 0) + 1
                        bodies = None
                        break
                    if atype in _NUMERIC_TYPES or label in _FREE_TEXT_LABELS:
                        bodies.append({"type": "TextualBody", "purpose": "describing",
                                       "value": str(value)})
                    else:
                        bodies.append({"type": "TextualBody", "purpose": "classifying",
                                       "value": str(label)})
                if not bodies:
                    continue
                add(ann, source, bodies[0] if len(bodies) == 1 else bodies,
                    "classifying" if all(b["purpose"] == "classifying" for b in bodies) else "describing",
                    schema_name)

        collection = {
            "@context": CONTEXT,
            "id": f"urn:potato:{task}:collection",
            "type": "AnnotationCollection",
            "label": (context.config or {}).get("annotation_task_name") or "Potato annotations",
            "total": len(items),
            "first": {"type": "AnnotationPage", "startIndex": 0, "items": items},
        }
        out_file = os.path.join(output_path, "web_annotations.jsonld")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(collection, f, ensure_ascii=False, indent=1)
        warnings = [f"left out {n} {what} (no Web Annotation equivalent)"
                    for what, n in sorted(skipped.items())]
        if relative_media:
            warnings.append(
                f"{len(set(relative_media))} image(s) are local files, written as paths relative "
                f"to the project folder (e.g. {relative_media[0]}); pass "
                "media_base_url=<where the server is reachable> for absolute IRIs")
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=[out_file], warnings=warnings,
                            stats={"num_annotations": len(items)})

    # ------------------------------------------------------------------

    @staticmethod
    def _anchor_text(context: ExportContext, iid: str, span: dict) -> Optional[str]:
        item = context.items.get(iid)
        if not isinstance(item, dict):
            return None
        field = span.get("target_field") or ((context.config or {}).get(
            "item_properties", {}) or {}).get("text_key", "text")
        try:
            return context._span_anchor_text(item, field)
        except Exception:
            return None

    @staticmethod
    def _region_target(context: ExportContext, iid: str, obj: dict, media: str) -> Optional[dict]:
        from .cv_utils import get_image_dimensions, normalize_annotation_object
        item = context.items.get(iid) or {}
        w, h = get_image_dimensions(item, config=context.config)
        known = bool(w and h)
        norm = normalize_annotation_object(obj, w if known else 100.0, h if known else 100.0)
        if norm is None:
            return None
        unit = "pixel" if known else "percent"

        def fmt(v):
            return f"{round(v, 2):g}"

        if norm.get("points") and norm["type"] in ("polygon", "polyline", "freeform"):
            pts = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in norm["points"])
            tag = "polyline" if norm["type"] == "polyline" else "polygon"
            if known:
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
                       f'<{tag} points="{pts}"/></svg>')
            else:
                svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                       f'<{tag} points="{pts}"/></svg>')
            selector = {"type": "SvgSelector", "value": svg}
        elif norm.get("bbox"):
            x, y, bw, bh = norm["bbox"]
            selector = {"type": "FragmentSelector",
                        "conformsTo": "http://www.w3.org/TR/media-frags/",
                        "value": f"xywh={unit}:{fmt(x)},{fmt(y)},{fmt(bw)},{fmt(bh)}"}
        else:
            return None
        return {"type": "SpecificResource", "source": media, "selector": selector}
