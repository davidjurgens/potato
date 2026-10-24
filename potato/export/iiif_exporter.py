"""
IIIF annotation pages for an imported IIIF manifest.

For every item that carries a ``canvas_id`` (projects made with
``potato import -f iiif`` do), the regions annotators drew are written as W3C
annotations on that canvas, one ``AnnotationPage`` per canvas:

* a box targets ``<canvas id>#xywh=x,y,w,h``;
* a polygon, polyline, ellipse or freehand shape targets the canvas through a
  ``SpecificResource`` with an ``SvgSelector`` whose ``viewBox`` is the canvas;
* a landmark uses a ``PointSelector``;
* an answer to a question on the whole canvas (radio, multiselect, text) is a
  ``TextualBody`` targeting the canvas.

Coordinates are canvas coordinates. Potato stores shapes relative to the
image, so they are scaled to the canvas ``width`` / ``height`` the manifest
gives, which need not equal the image's pixel size.

A copy of the manifest (the one the importer kept under ``iiif/``) is written
beside the pages with a reference to each page added to its canvas
(``annotations`` in Presentation 3, ``otherContent`` in 2.x), so Mirador or
Universal Viewer can open the copy and show the annotations. Options:

``base_url``
    Where the output folder will be served from, e.g.
    ``https://example.org/iiif/``. Page ids are ``<base_url>annotations/<canvas>.json``.
    Without it the ids are relative paths, which a viewer can only resolve when
    the manifest is opened from the same folder.
``embed``
    ``true`` puts the annotation pages inside the manifest copy instead of
    referencing them, which works without hosting the pages anywhere.

Output: ``annotations/*.json`` and ``manifest.json`` (one folder per manifest
when a project holds several).
"""

from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

P3_CONTEXT = "http://iiif.io/api/presentation/3/context.json"
P2_CONTEXT = "http://iiif.io/api/presentation/2/context.json"
_FREE_TEXT_LABELS = {"text_box", "textbox", "free_response", "text"}


def _slug(text: Any) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-._")[:80] or "canvas"


def _fmt(v: float) -> str:
    return f"{round(float(v), 2):g}"


def _truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


class IIIFAnnotationExporter(BaseExporter):
    format_name = "iiif_annotations"
    description = "IIIF annotation pages per canvas, plus the manifest with them attached (Mirador, UV)"
    file_extensions = [".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not any(isinstance(item, dict) and item.get("canvas_id")
                   for item in context.items.values()):
            return False, ("no item has a canvas_id; this export is for projects "
                           "imported from a IIIF manifest (potato import -f iiif)")
        return True, ""

    # ------------------------------------------------------------------

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from .cv_utils import normalize_annotation_object
        options = options or {}
        base_url = str(options.get("base_url") or "")
        if base_url and not base_url.endswith("/"):
            base_url += "/"
        embed = _truthy(options.get("embed", False))
        os.makedirs(output_path, exist_ok=True)
        schemas = {s.get("name"): s for s in context.schemas or []}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        warnings: List[str] = []
        skipped: Dict[str, int] = defaultdict(int)

        # manifest file -> canvas id -> [annotation dicts (version-neutral)]
        by_manifest: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
        canvas_items: Dict[str, dict] = {}
        for ann in context.annotations:
            iid = str(ann.get("instance_id", ""))
            item = context.items.get(iid) or {}
            cid = item.get("canvas_id")
            if not cid:
                continue
            canvas_items[cid] = item
            cw = float(item.get("canvas_width") or item.get("image_width") or 0)
            ch = float(item.get("canvas_height") or item.get("image_height") or 0)
            bucket = by_manifest[str(item.get("iiif_manifest") or "")][cid]
            user = str(ann.get("user_id", ""))
            for schema_name, objects in (ann.get("image_annotations") or {}).items():
                for obj in objects or []:
                    if not (cw and ch):
                        skipped["regions on a canvas with no size"] += 1
                        continue
                    norm = normalize_annotation_object(obj, cw, ch)
                    if norm is None or norm.get("type") == "mask":
                        skipped["masks and unreadable shapes"] += 1
                        continue
                    bucket.append({"kind": "region", "norm": norm, "label": obj.get("label", ""),
                                   "user": user, "schema": schema_name, "cw": cw, "ch": ch})
            for schema_name, labels in (ann.get("labels") or {}).items():
                schema = schemas.get(schema_name) or {}
                atype = schema.get("annotation_type", "")
                if atype in ("image_annotation", "span", "") or not isinstance(labels, dict):
                    continue
                for label, value in labels.items():
                    if value in (None, "", False) or isinstance(value, (dict, list)):
                        continue
                    if isinstance(value, str) and value[:1] in "[{":
                        continue
                    free = label in _FREE_TEXT_LABELS or atype in ("text", "number", "slider")
                    bucket.append({"kind": "whole", "purpose": "describing" if free else "classifying",
                                   "label": str(value) if free else str(label),
                                   "user": user, "schema": schema_name})
        if not canvas_items:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["no annotated item has a canvas_id"])

        written: List[str] = []
        total = 0
        multi = len(by_manifest) > 1
        task_dir = str((context.config or {}).get("task_dir") or ".")
        for manifest_rel, canvases in by_manifest.items():
            manifest = self._load_manifest(task_dir, manifest_rel)
            if manifest is None:
                manifest = self._synthesize(canvases, canvas_items)
                if manifest_rel:
                    warnings.append(f"{manifest_rel} was not found under the task directory; "
                                    "wrote a minimal Presentation 3 manifest instead")
            version = 3 if isinstance(manifest.get("items"), list) else 2
            folder = output_path
            if multi:
                folder = os.path.join(output_path, _slug(os.path.splitext(os.path.basename(manifest_rel))[0]
                                                         or "manifest"))
            os.makedirs(os.path.join(folder, "annotations"), exist_ok=True)
            prefix = base_url + (os.path.basename(folder) + "/" if multi and base_url else "")
            pages: Dict[str, dict] = {}
            for cid, entries in canvases.items():
                if not entries:
                    continue
                name = _slug(cid.rstrip("/").rsplit("/", 1)[-1] or cid)
                if name in {p["_name"] for p in pages.values()}:
                    name = f"{name}-{len(pages) + 1}"
                page_id = f"{prefix}annotations/{name}.json"
                page = (self._page_v3 if version == 3 else self._page_v2)(cid, page_id, entries, now)
                page["_name"] = name
                pages[cid] = page
                total += len(entries)
            for cid, page in pages.items():
                name = page.pop("_name")
                path = os.path.join(folder, "annotations", f"{name}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(page, fh, ensure_ascii=False, indent=1)
                written.append(path)
            out_manifest = self._attach(copy.deepcopy(manifest), pages, version, embed)
            mpath = os.path.join(folder, "manifest.json")
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump(out_manifest, fh, ensure_ascii=False, indent=1)
            written.append(mpath)
        if not base_url and not embed:
            warnings.append("annotation page ids are relative paths; pass --option "
                            "base_url=<where the folder will be served> (or embed=true) "
                            "for viewers that load the manifest from elsewhere")
        warnings.extend(f"left out {n} {what}" for what, n in sorted(skipped.items()))
        return ExportResult(success=True, format_name=self.format_name, files_written=written,
                            warnings=warnings, stats={"num_annotations": total,
                                                      "num_canvases": len(canvas_items)})

    # ------------------------------------------------------------------ manifests

    @staticmethod
    def _load_manifest(task_dir: str, rel: str) -> Optional[dict]:
        if not rel:
            return None
        path = rel if os.path.isabs(rel) else os.path.join(task_dir, rel)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _synthesize(canvases: Dict[str, List[dict]], items: Dict[str, dict]) -> dict:
        first = next(iter(items.values()))
        manifest = {"@context": P3_CONTEXT, "id": first.get("manifest_id") or "urn:potato:manifest",
                    "type": "Manifest",
                    "label": {"none": [first.get("manifest_label") or "Potato export"]},
                    "items": []}
        for cid in canvases:
            item = items[cid]
            w = int(item.get("canvas_width") or item.get("image_width") or 0)
            h = int(item.get("canvas_height") or item.get("image_height") or 0)
            manifest["items"].append({
                "id": cid, "type": "Canvas", "width": w, "height": h,
                "label": {"none": [str(item.get("label") or cid)]},
                "items": [{"id": f"{cid}/page/p1", "type": "AnnotationPage", "items": [{
                    "id": f"{cid}/annotation/painting", "type": "Annotation",
                    "motivation": "painting", "target": cid,
                    "body": {"id": item.get("image_url", ""), "type": "Image",
                             "width": int(item.get("image_width") or w),
                             "height": int(item.get("image_height") or h)}}]}],
            })
        return manifest

    @staticmethod
    def _attach(manifest: dict, pages: Dict[str, dict], version: int, embed: bool) -> dict:
        if version == 3:
            for canvas in manifest.get("items") or []:
                page = pages.get(canvas.get("id"))
                if page is None:
                    continue
                entry = page if embed else {"id": page["id"], "type": "AnnotationPage"}
                if embed:
                    entry = {k: v for k, v in page.items() if k != "@context"}
                canvas.setdefault("annotations", []).append(entry)
        else:
            for seq in manifest.get("sequences") or []:
                for canvas in seq.get("canvases") or []:
                    page = pages.get(canvas.get("@id"))
                    if page is None:
                        continue
                    entry = ({k: v for k, v in page.items() if k != "@context"} if embed
                             else {"@id": page["@id"], "@type": "sc:AnnotationList"})
                    canvas.setdefault("otherContent", []).append(entry)
        return manifest

    # ------------------------------------------------------------------ pages

    @staticmethod
    def _svg(norm: dict, cw: float, ch: float) -> Optional[str]:
        points = norm.get("points")
        if not points:
            return None
        pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)
        tag = "polyline" if norm.get("type") == "polyline" else "polygon"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(cw)} {_fmt(ch)}">'
                f'<{tag} points="{pts}"/></svg>')

    def _page_v3(self, cid: str, page_id: str, entries: List[dict], now: str) -> dict:
        items = []
        stem = page_id[:-5] if page_id.endswith(".json") else page_id
        for n, e in enumerate(entries, start=1):
            if e["kind"] == "region":
                norm = e["norm"]
                if norm.get("type") == "landmark":
                    target: Any = {"type": "SpecificResource", "source": {"id": cid, "type": "Canvas"},
                                   "selector": {"type": "PointSelector",
                                                "x": float(_fmt(norm["points"][0][0])),
                                                "y": float(_fmt(norm["points"][0][1]))}}
                elif norm.get("type") == "bbox" or not norm.get("points"):
                    x, y, w, h = norm["bbox"]
                    target = f"{cid}#xywh={_fmt(x)},{_fmt(y)},{_fmt(w)},{_fmt(h)}"
                else:
                    target = {"type": "SpecificResource", "source": {"id": cid, "type": "Canvas"},
                              "selector": {"type": "SvgSelector",
                                           "value": self._svg(norm, e["cw"], e["ch"])}}
                body = {"type": "TextualBody", "purpose": "tagging", "value": e["label"],
                        "format": "text/plain"}
                motivation = "tagging"
            else:
                target = cid
                body = {"type": "TextualBody", "purpose": e["purpose"], "value": e["label"],
                        "format": "text/plain"}
                motivation = "classifying" if e["purpose"] == "classifying" else "commenting"
            items.append({"id": f"{stem}/a{n}", "type": "Annotation", "motivation": motivation,
                          "created": now,
                          "creator": {"id": f"urn:potato:user:{e['user']}", "type": "Person",
                                      "nickname": e["user"]},
                          "body": body, "target": target})
        return {"@context": P3_CONTEXT, "id": page_id, "type": "AnnotationPage", "items": items}

    def _page_v2(self, cid: str, page_id: str, entries: List[dict], now: str) -> dict:
        resources = []
        stem = page_id[:-5] if page_id.endswith(".json") else page_id
        for n, e in enumerate(entries, start=1):
            if e["kind"] == "region":
                norm = e["norm"]
                if norm.get("type") == "bbox" or not norm.get("points") or norm.get("type") == "landmark":
                    x, y, w, h = norm["bbox"]
                    if norm.get("type") == "landmark":
                        x, y, w, h = norm["points"][0][0], norm["points"][0][1], 1, 1
                    on: Any = f"{cid}#xywh={int(round(x))},{int(round(y))},{int(round(w))},{int(round(h))}"
                else:
                    on = {"@type": "oa:SpecificResource", "full": cid,
                          "selector": {"@type": "oa:SvgSelector",
                                       "value": self._svg(norm, e["cw"], e["ch"])}}
                motivation = ["oa:tagging"]
                resource = {"@type": "oa:Tag", "chars": e["label"]}
            else:
                on = cid
                motivation = ["oa:classifying"] if e["purpose"] == "classifying" else ["oa:commenting"]
                resource = {"@type": "dctypes:Text", "format": "text/plain", "chars": e["label"]}
            resources.append({"@id": f"{stem}/a{n}", "@type": "oa:Annotation",
                              "motivation": motivation, "resource": resource, "on": on,
                              "annotatedBy": {"@id": f"urn:potato:user:{e['user']}",
                                              "name": e["user"]}})
        return {"@context": P2_CONTEXT, "@id": page_id, "@type": "sc:AnnotationList",
                "resources": resources}
