"""
WebDataset shard importer (``.tar`` archives of paired files).

WebDataset is a **container, not an annotation format**. A shard is a plain tar
whose members share a basename::

    000000.jpg  000000.json
    000001.jpg  000001.json

The image is the image; the sidecar holds whatever the dataset author chose to
put there. So this importer does not invent a fifteenth annotation dialect —
it extracts the sidecars and hands each one to the registry, which detects
LabelMe, Darwin, or a plain object list exactly as it would for a loose file.
A dataset shipped as WebDataset-wrapped LabelMe therefore imports as LabelMe,
with LabelMe's conventions and LabelMe's warnings, rather than through a
second, subtly different code path.

Read with the standard library's ``tarfile``: no ``webdataset`` dependency, and
shards stream rather than being unpacked to disk.

The images stay inside the shard, which no web server can serve. The import
either extracts them next to the project (``--extract-media``) or reports that
the canvas will be blank until they are — the failure that is otherwise
discovered one item at a time in the browser.
"""

from __future__ import annotations

import json
import logging
import os
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix, safe_instance_id
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)

#: Sidecar extensions that may carry annotations.
ANNOTATION_EXTENSIONS = (".json", ".cls", ".txt")

#: Image members we know how to point the canvas at.
MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

#: A shard with no size information still needs dimensions to normalize
#: absolute coordinates; sidecars usually carry them, and this is the fallback.
DEFAULT_SIZE = (1000, 1000)


class WebDatasetImporter(BaseAnnotationImporter):
    format_name = "webdataset"
    description = "WebDataset .tar shards (image + sidecar pairs)"
    file_extensions = [".tar"]

    def detect(self, data: Any) -> bool:
        return isinstance(data, dict) and "webdataset_shards" in data

    # ------------------------------------------------------------------

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        shards = ([base] if base.is_file() and tarfile.is_tarfile(base)
                  else sorted(p for p in base.glob("*.tar")
                              if tarfile.is_tarfile(p)))
        if not shards:
            raise ValueError(
                f"No readable .tar shards under {base}. A WebDataset is one or "
                f"more tar files holding image/sidecar pairs that share a "
                f"basename.")
        return self.parse({"webdataset_shards": shards, "root": base}, options)

    # ------------------------------------------------------------------

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        if not self.detect(data):
            raise ValueError(
                "Not a WebDataset. Point --input at a .tar shard or the "
                "directory holding them.")

        extract_to = options.get("extract_media")
        result = ImportResult()
        labels: Dict[str, dict] = {}
        tools: set = set()
        delegated: Dict[str, int] = {}
        media_members = 0
        classification_only = 0

        for shard in data["webdataset_shards"]:
            try:
                archive = tarfile.open(shard, "r:*")
            except tarfile.TarError as exc:
                result.warnings.append(f"Could not open {shard.name}: {exc}")
                continue
            with archive:
                samples = self._group(archive)
                for key, members in sorted(samples.items()):
                    media = members.get("media")
                    if media is None:
                        continue
                    media_members += 1
                    media_name = self._extract(
                        archive, media, extract_to, shard) if extract_to \
                        else os.path.basename(media)

                    objects, source, label = self._annotations(
                        archive, members, result.warnings)
                    if source:
                        delegated[source] = delegated.get(source, 0) + 1
                    if label and not objects:
                        classification_only += 1

                    for obj in objects:
                        labels.setdefault(obj["label"], {"name": obj["label"]})
                        tools.add(obj["type"])

                    extra = {"image_url": apply_url_prefix(media_name, options),
                             "shard": shard.name}
                    if label:
                        # A .cls sidecar is a whole-image class, not geometry.
                        # Carried as an item field so a classification schema
                        # can use it without it posing as a drawn object.
                        extra["webdataset_class"] = label

                    width, height = self._size(members, archive)
                    result.images.append(ImportedImage(
                        instance_id=safe_instance_id(f"{shard.stem}_{key}"),
                        file_name=media_name,
                        width=width,
                        height=height,
                        objects=objects,
                        extra=extra,
                    ))

        if delegated:
            summary = ", ".join(f"{n} as {fmt}" for fmt, n in sorted(delegated.items()))
            result.warnings.append(
                f"Sidecars were read by the matching format importer: {summary}. "
                f"WebDataset is a container, so its contents keep their own "
                f"format's conventions and caveats.")
        if classification_only:
            result.warnings.append(
                f"{classification_only} sample(s) carry only a whole-image "
                f"class (.cls), not geometry. It is on each item as "
                f"webdataset_class; pair it with a radio or multiselect schema "
                f"rather than an image_annotation one.")
        if media_members and not extract_to:
            result.warnings.append(
                f"The {media_members} image(s) are still inside the shard, "
                f"which no web server can read, so the canvas will be blank. "
                f"Re-run with --extract-media <dir> to write them out, and "
                f"point --image-url-prefix at where you serve that directory.")

        result.labels = [labels[n] for n in sorted(labels)]
        result.tools = sorted(tools)
        result.summarize()
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _group(archive: tarfile.TarFile):
        """
        Group members by basename.

        WebDataset's rule is that everything up to the FIRST dot is the key, so
        ``000000.left.jpg`` and ``000000.json`` are one sample. Splitting on the
        last dot instead silently separates them into two half-samples.
        """
        samples: Dict[str, Dict[str, Any]] = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name
            base = os.path.basename(name)
            key = base.split(".", 1)[0]
            suffix = base[len(key):].lower()
            entry = samples.setdefault(key, {"sidecars": []})
            if suffix.endswith(MEDIA_EXTENSIONS):
                entry["media"] = name
            elif suffix.endswith(ANNOTATION_EXTENSIONS):
                entry["sidecars"].append((suffix, name))
        return samples

    def _annotations(self, archive, members, warnings):
        """Objects, the format they came from, and any whole-image class."""
        label = ""
        for suffix, name in members.get("sidecars", []):
            try:
                payload = archive.extractfile(name)
                raw = payload.read().decode("utf-8") if payload else ""
            except (tarfile.TarError, UnicodeDecodeError) as exc:
                warnings.append(f"Could not read {name}: {exc}")
                continue

            if suffix.endswith(".cls") or suffix.endswith(".txt"):
                text = raw.strip()
                if text and "\n" not in text:
                    label = text
                continue

            try:
                doc = json.loads(raw)
            except ValueError:
                warnings.append(f"{name} is not valid JSON; skipped.")
                continue

            objects, source = self._delegate(doc, name, warnings)
            if objects or source:
                return objects, source, label
        return [], "", label

    def _delegate(self, doc, name, warnings):
        """
        Hand the sidecar to whichever registered importer recognises it.

        Deliberately reuses the registry rather than reimplementing LabelMe or
        Darwin parsing: a WebDataset-wrapped LabelMe file should import exactly
        as the same file would loose on disk, warnings included.
        """
        from .registry import import_registry

        fmt = None
        try:
            fmt = import_registry.detect_format(doc)
        except Exception:
            fmt = None

        if fmt and fmt != self.format_name:
            try:
                nested = import_registry.parse(fmt, doc, {})
            except Exception as exc:
                warnings.append(f"{name}: {fmt} importer failed: {exc}")
                return [], ""
            objects = [o for image in nested.images for o in image.objects]
            warnings.extend(f"{name}: {w}" for w in nested.warnings[:2])
            return objects, fmt

        objects = self._plain_objects(doc)
        return objects, "plain objects" if objects else ""

    @staticmethod
    def _plain_objects(doc):
        """
        The common ad-hoc sidecar: a list of boxes with explicit dimensions.

        Accepts ``{"width", "height", "objects": [{"label", "bbox": [x,y,w,h]}]}``
        which is what most hand-rolled WebDataset detection sets look like.
        """
        if not isinstance(doc, dict):
            return []
        raw = doc.get("objects") or doc.get("annotations") or []
        if not isinstance(raw, list):
            return []
        width = float(doc.get("width") or doc.get("image_width") or 0)
        height = float(doc.get("height") or doc.get("image_height") or 0)
        if width <= 0 or height <= 0:
            return []

        objects = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            box = entry.get("bbox") or entry.get("box")
            label = str(entry.get("label") or entry.get("category")
                        or entry.get("class") or "").strip()
            if not label or not box or len(box) < 4:
                continue
            obj = to_client_object("bbox", label, img_w=width, img_h=height,
                                   bbox=[float(v) for v in box[:4]])
            if obj is not None:
                objects.append(obj)
        return objects

    @staticmethod
    def _size(members, archive):
        for suffix, name in members.get("sidecars", []):
            if not suffix.endswith(".json"):
                continue
            try:
                payload = archive.extractfile(name)
                doc = json.loads(payload.read().decode("utf-8")) if payload else {}
            except Exception:
                continue
            if isinstance(doc, dict):
                width = doc.get("width") or doc.get("image_width") or doc.get("imageWidth")
                height = doc.get("height") or doc.get("image_height") or doc.get("imageHeight")
                if width and height:
                    return int(width), int(height)
        return DEFAULT_SIZE

    @staticmethod
    def _extract(archive, member_name, extract_to, shard):
        """
        Write one image out of the shard.

        Members are written by BASENAME into the target directory: a tar can
        contain ``../`` and absolute paths, and extracting those would write
        outside the chosen directory.
        """
        target_dir = Path(extract_to)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = os.path.basename(member_name)
        out_path = target_dir / safe_name
        try:
            source = archive.extractfile(member_name)
            if source is not None:
                with open(out_path, "wb") as fh:
                    fh.write(source.read())
        except (tarfile.TarError, OSError) as exc:
            logger.warning("Could not extract %s from %s: %s",
                           member_name, shard, exc)
        return safe_name
