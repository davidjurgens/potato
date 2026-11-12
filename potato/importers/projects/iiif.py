"""
IIIF Presentation API manifests as an image annotation project.

Input is a manifest file, a folder holding one, or an http(s) URL. A URL is
the only case in which the importer reads the network: the manifest itself,
and annotation pages the manifest references by URL. A local manifest's
referenced pages are read from files beside it when they are there, and
otherwise reported and left out.

Each Canvas becomes one item:

* the image is the painting annotation's body ``id``; when the body has no
  usable id, or ``options["iiif_size"]`` is given, a sized request is built
  from its IIIF Image service, ``{service}/full/{size}/0/default.jpg``
  (``!2000,2000`` by default, which fits the image in a 2000-pixel square);
* the canvas ``label``, the manifest ``label`` and the canvas and manifest
  ``metadata`` become item fields, and a one-line summary of them is the
  item text;
* annotations already on the canvas (embedded annotation pages, or pages
  referenced by URL or file) become pre-annotations on an ``image_annotation``
  scheme, through the W3C Web Annotation reader in
  :mod:`potato.importers.projects.web_annotation`. Their coordinates are
  canvas coordinates; Potato stores shapes relative to the image, so a canvas
  whose size differs from its image's still lines up.

Presentation 2.x manifests (``sequences`` / ``canvases`` / ``images`` /
``otherContent``) are read on a best-effort basis.

A copy of the manifest is kept in the project (``iiif/``), and each item
records its ``canvas_id``, so the ``iiif_annotations`` exporter can write the
corrected regions back as annotation pages on the same canvases.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from potato.importers._common import probe_image_size

from . import _dh
from .base import ProjectImportResult, ProjectItem
from .web_annotation import (Anno, _SchemeBuilder, collect_annotations, load_reference,
                             region_object, DEFAULT_REGION_LABEL)

SCHEME_NAME = "regions"
DEFAULT_SIZE = "!2000,2000"


def lang_text(value: Any) -> str:
    """A IIIF language map, a v2 ``@value`` list, or a string, as one string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "@value" in value:
            return str(value["@value"])
        for key in ("en", "none", *value.keys()):
            entries = value.get(key)
            if entries:
                return "; ".join(str(e) for e in (entries if isinstance(entries, list) else [entries]))
        return ""
    if isinstance(value, list):
        return "; ".join(t for t in (lang_text(v) for v in value) if t)
    return str(value)


def metadata_pairs(raw: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for entry in raw or []:
        if isinstance(entry, dict):
            label = _plain(lang_text(entry.get("label")))
            value = _plain(lang_text(entry.get("value")))
            if label and value:
                out.setdefault(label, value)
    return out


def _plain(text: str) -> str:
    if "<" in text:
        from potato.server_utils.span_text import markup_text
        text = markup_text(text)
    return _dh.normalize_space(text)


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _refusal_warning(result: ProjectImportResult, where: str):
    """``_dh.refusal_warning`` for IIIF, which takes no --image-dir: a local
    image is copied only from the manifest's own folder."""
    def warn(reference: str) -> None:
        result.warn(f"{where}: {reference} is outside the input folder (the manifest's "
                    "folder); not copied (move the file into the folder that holds the "
                    "manifest)")
        result.skipped["files outside the input folder"] += 1
    return warn


def _service_id(service: Any) -> Tuple[str, str]:
    """(id, type) of the first image service."""
    for entry in service if isinstance(service, list) else [service]:
        if isinstance(entry, dict):
            sid = entry.get("id") or entry.get("@id")
            if sid:
                kind = str(entry.get("type") or entry.get("@type") or entry.get("profile") or "")
                return str(sid).rstrip("/"), kind
    return "", ""


class IIIFImporter:
    format_name = "iiif"
    description = "IIIF Presentation 3 / 2.x manifest (file or URL): one item per canvas"
    file_extensions = [".json", ".jsonld"]

    # ------------------------------------------------------------------ detect
    def _manifest_file(self, path: Path) -> Optional[Path]:
        if path.is_dir():
            for candidate in sorted(path.iterdir()):
                if candidate.suffix.lower() in self.file_extensions and self._looks_like(candidate):
                    return candidate
            return None
        return path if path.is_file() and self._looks_like(path) else None

    @staticmethod
    def _looks_like(path: Path) -> bool:
        try:
            with path.open(encoding="utf-8-sig") as fh:
                head = fh.read(65536)
        except (OSError, UnicodeDecodeError):
            return False
        return bool(re.search(r'"(?:type|@type)"\s*:\s*"(?:sc:)?Manifest"', head))

    def detect_path(self, path: Path) -> bool:
        text = _dh.repair_url(str(path))
        if _dh.is_url(text):
            return True             # the only importer that reads a URL
        return self._manifest_file(Path(path)) is not None

    # ------------------------------------------------------------------ parse
    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        options = options or {}
        source = _dh.repair_url(str(options.get("source") or path))
        result = ProjectImportResult(source_format="IIIF Presentation manifest", text_key="text")
        if _dh.is_url(source):
            manifest = _dh.fetch_json(source)
            base_dir = None
            allow_fetch = True
            copy_dir = Path(tempfile.mkdtemp(prefix="potato-iiif-"))
            copy = copy_dir / (_dh.slug(Path(_dh.iri_tail(source)).stem or "manifest", "manifest") + ".json")
            copy.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            file = self._manifest_file(Path(path))
            if file is None:
                raise ValueError(f"no IIIF manifest at {path}")
            manifest = _dh.read_json(file)
            base_dir = file.parent
            allow_fetch = False
            copy = file
        if not isinstance(manifest, dict):
            raise ValueError("a IIIF manifest is a JSON object")
        manifest_rel = f"iiif/{copy.name}"
        result.media_files[manifest_rel] = str(copy)
        # A fetched manifest is saved to a temp folder; local images come only
        # from the manifest's own folder.
        result.media_roots = [str(copy.parent)] + ([str(base_dir)] if base_dir else [])

        version = 3 if isinstance(manifest.get("items"), list) else 2
        manifest_label = _plain(lang_text(manifest.get("label")))
        manifest_meta = metadata_pairs(manifest.get("metadata"))
        canvases = self._canvases(manifest, version)
        if not canvases:
            raise ValueError("the manifest has no canvases")
        result.guidelines = _plain(lang_text(manifest.get("summary") or manifest.get("description")))
        # The image scheme draws the picture itself; this shows which canvas it
        # is and the manifest's metadata above it.
        result.instance_display = {"fields": [{"key": "text", "type": "text", "label": "Canvas"}]}

        # Annotations attached to the manifest rather than to a canvas.
        loose: List[Anno] = []
        for page in manifest.get("annotations") or []:
            loose.extend(self._page_annotations(page, result, base_dir, allow_fetch))

        builder = _SchemeBuilder()
        seen: set = set()
        for index, canvas in enumerate(canvases, start=1):
            info = self._canvas(canvas, version, options, base_dir, result, allow_fetch)
            if info is None:
                continue
            label = info["label"] or f"Canvas {index}"
            iid = _dh.unique_id(f"{index:04d}-{_dh.slug(label, 'canvas')}", seen)
            meta = dict(manifest_meta)
            meta.update(info["metadata"])
            summary = " · ".join(f"{k}: {v}" for k, v in meta.items())
            text = f"{manifest_label} — {label}" if manifest_label else label
            fields: Dict[str, Any] = {
                "text": f"{text}. {summary}" if summary else text,
                "label": label,
                "image_url": info["image_url"],
                "canvas_id": info["canvas_id"],
                "canvas_width": info["canvas_width"],
                "canvas_height": info["canvas_height"],
                "manifest_id": str(manifest.get("id") or manifest.get("@id") or source),
                "manifest_label": manifest_label,
                "iiif_manifest": manifest_rel,
                "iiif_version": version,
            }
            if info["image_width"] and info["image_height"]:
                fields["image_width"] = info["image_width"]
                fields["image_height"] = info["image_height"]
            if meta:
                fields["metadata"] = meta
            item = ProjectItem(instance_id=iid, fields=fields)

            annos = list(info["annotations"])
            annos.extend(a for a in loose if a.source == info["canvas_id"])
            cw, ch = info["canvas_width"], info["canvas_height"]
            for anno in annos:
                if anno.source != info["canvas_id"]:
                    continue
                if anno.is_region:
                    obj, reason = region_object(anno, cw, ch, anno.label(DEFAULT_REGION_LABEL))
                    if obj is None:
                        result.skipped[reason] += 1
                        continue
                    builder.add_region(item, anno, obj)
                elif anno.is_text:
                    result.skipped["text-selector annotations on a canvas"] += 1
                else:
                    builder.add_whole(item, anno, result)
            result.items.append(item)

        if not result.items:
            raise ValueError("no canvas in the manifest has an image Potato can show")
        builder.finish(result)
        if not any(s["annotation_type"] == "image_annotation" for s in result.schemes):
            labels = options.get("labels") or [DEFAULT_REGION_LABEL]
            if isinstance(labels, str):
                labels = [l.strip() for l in labels.split(",") if l.strip()]
            result.schemes.insert(0, {
                "annotation_type": "image_annotation", "name": SCHEME_NAME,
                "description": "Mark the regions of interest",
                "source_field": "image_url", "tools": ["bbox", "polygon"],
                "labels": list(labels), "zoom_enabled": True, "pan_enabled": True})
        return result

    # ------------------------------------------------------------------ canvases
    @staticmethod
    def _canvases(manifest: dict, version: int) -> List[dict]:
        if version == 3:
            return [c for c in manifest.get("items") or []
                    if isinstance(c, dict) and "Canvas" in str(c.get("type", ""))]
        out: List[dict] = []
        for seq in manifest.get("sequences") or []:
            if isinstance(seq, dict):
                out.extend(c for c in seq.get("canvases") or [] if isinstance(c, dict))
        return out

    def _canvas(self, canvas: dict, version: int, options: dict, base_dir: Optional[Path],
                result: ProjectImportResult, allow_fetch: bool) -> Optional[Dict[str, Any]]:
        cid = str(canvas.get("id") or canvas.get("@id") or "")
        if not cid:
            result.skipped["canvases without an id"] += 1
            return None
        body: Optional[dict] = None
        pages: List[Any] = []
        if version == 3:
            for page in canvas.get("items") or []:
                for anno in (page or {}).get("items") or []:
                    if isinstance(anno, dict) and "painting" in str(anno.get("motivation", "")):
                        body = _first(anno.get("body"))
                        if isinstance(body, dict) and body.get("type") == "Choice":
                            body = _first(body.get("items"))
                        break
                if body:
                    break
            pages = list(canvas.get("annotations") or [])
        else:
            image = _first(canvas.get("images"))
            if isinstance(image, dict):
                body = image.get("resource")
                if isinstance(body, dict) and "Choice" in str(body.get("@type", "")):
                    body = body.get("default") or _first(body.get("item"))
            pages = list(canvas.get("otherContent") or [])
        if not isinstance(body, dict):
            result.warn(f"canvas {cid} has no painting image; left out")
            result.skipped["canvases without an image"] += 1
            return None

        body_id = str(body.get("id") or body.get("@id") or "")
        service, service_type = _service_id(body.get("service"))
        size = options.get("iiif_size")
        image_url = ""
        local = _dh.local_path(body_id, base_dir,
                               refused=_refusal_warning(result, f"canvas {cid}")) if body_id else None
        if local is not None:
            rel = f"media/{local.name}"
            result.media_files[rel] = str(local)
            image_url = f"/{rel}"
        elif service and (size or not body_id or body_id.endswith("info.json")):
            size = size or DEFAULT_SIZE
            if size == "full" and "3" in service_type:
                size = "max"
            image_url = f"{service}/full/{size}/0/default.jpg"
        elif body_id:
            image_url = body_id
        if not image_url:
            result.skipped["canvases without an image"] += 1
            return None

        cw = _num(canvas.get("width"))
        ch = _num(canvas.get("height"))
        iw = _num(body.get("width"))
        ih = _num(body.get("height"))
        if local is not None and not (iw and ih):
            measured = probe_image_size(local)
            if measured:
                iw, ih = measured
        if not (cw and ch):
            cw, ch = iw, ih
        if not (cw and ch):
            why = f" and the image could not be measured ({_dh.unmeasured_reason(local)})" \
                if local is not None else ""
            result.warn(f"canvas {cid} has no width/height{why}; its annotations cannot be placed")
        annos: List[Anno] = []
        for page in pages:
            annos.extend(self._page_annotations(page, result, base_dir, allow_fetch))
        return {
            "canvas_id": cid,
            "label": _plain(lang_text(canvas.get("label"))),
            "metadata": metadata_pairs(canvas.get("metadata")),
            "image_url": image_url,
            "image_width": int(iw) if iw else 0,
            "image_height": int(ih) if ih else 0,
            "canvas_width": int(cw) if cw else 0,
            "canvas_height": int(ch) if ch else 0,
            "annotations": annos,
        }

    def _page_annotations(self, page: Any, result: ProjectImportResult, base_dir: Optional[Path],
                          allow: bool) -> List[Anno]:
        if isinstance(page, dict) and (page.get("items") or page.get("resources")):
            return collect_annotations(page, result, base_dir, allow)
        ref = (page.get("id") or page.get("@id")) if isinstance(page, dict) else page
        loaded = load_reference(str(ref or ""), result, base_dir, allow)
        return collect_annotations(loaded, result, base_dir, allow) if loaded is not None else []


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0
