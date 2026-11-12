"""
Pathology region exports from image_annotation: QuPath GeoJSON and ASAP XML.

Both write one file per annotator and image, ``<user>/<slide stem>.geojson``
or ``<user>/<slide stem>.xml``, with coordinates in the slide's level-0
pixels: what QuPath's "Import objects" and ASAP's file open expect for the
same slide. Labels become QuPath classifications (``{name, color}``) and
ASAP groups (``PartOfGroup``), coloured from the scheme's label colours.
See potato/media/pathology_regions.py for the shape mapping.

The slide's size comes from the item (``image_width``/``image_height``, which
``potato import -f qupath_geojson`` writes), else from the file itself:
openslide for slide formats (the ``wsi`` extra), Pillow for the rest.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _image_schemes(context) -> List[dict]:
    return [s for s in context.schemas if s.get("annotation_type") == "image_annotation"]


def _label_colors(context) -> Dict[str, str]:
    colors: Dict[str, str] = {}
    for scheme in _image_schemes(context):
        for label in scheme.get("labels") or []:
            if isinstance(label, dict) and label.get("name") and label.get("color"):
                colors.setdefault(str(label["name"]), str(label["color"]))
    return colors


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._") or "item"


def _item_dimensions(item: dict) -> Tuple[int, int]:
    for w_key, h_key in (("image_width", "image_height"), ("slide_width", "slide_height"),
                         ("width", "height")):
        try:
            w, h = int(item.get(w_key) or 0), int(item.get(h_key) or 0)
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            return w, h
    return 0, 0


def slide_size(context, item: dict, record: dict) -> Tuple[int, int]:
    """Level-0 (width, height) of the item's slide; (0, 0) when unknown."""
    from .cv_utils import get_image_dimensions, get_image_filename
    width, height = _item_dimensions(item)
    if width and height:
        return width, height
    reference = get_image_filename(item, context.config)
    if reference and "://" not in str(reference):
        from potato.media.paths import resolve_media_path
        from potato.media.pathology_regions import slide_dimensions
        ref = str(reference)
        for prefix in ("/media/", "media/"):
            if ref.startswith(prefix):
                ref = ref[len(prefix):]
                break
        try:
            _root, path = resolve_media_path(context.config, ref.lstrip("/"),
                                             context="Pathology export")
        except Exception:  # noqa: BLE001 - a path the media root refuses
            path = None
        if path:
            size = slide_dimensions(path)
            if size:
                return size
    return get_image_dimensions(item, config=context.config, annotation=record)


class _PathologyExporter(BaseExporter):
    extension = ""

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not _image_schemes(context):
            return False, "No image_annotation schema found in config"
        return True, ""

    def _write(self, path: str, regions: List[dict], colors: Dict[str, str],
               item_key: str, where: str, warnings: List[str]) -> None:
        raise NotImplementedError

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from .cv_utils import blank_item_warning, get_image_filename
        from potato.media.pathology_regions import canonical_regions
        image_schemes = {s.get("name") for s in _image_schemes(context)}
        colors = _label_colors(context)
        warnings: List[str] = []
        files: List[str] = []
        # (user, instance) -> objects from every image_annotation scheme
        by_key: Dict[Tuple[str, str], Tuple[dict, List[dict]]] = {}
        for record in context.annotations:
            stored = record.get("image_annotations")
            if not isinstance(stored, dict):
                continue
            key = (str(record.get("user_id")), str(record.get("instance_id")))
            for schema, objects in stored.items():
                if schema in image_schemes and isinstance(objects, list):
                    by_key.setdefault(key, (record, []))[1].extend(objects)

        used: Dict[str, set] = {}
        n_regions = 0
        unmeasured = []
        for (user, instance), (record, objects) in sorted(by_key.items()):
            item = context.items.get(instance) or {}
            width, height = slide_size(context, item, record)
            if width <= 0 or height <= 0:
                unmeasured.append(instance)
                continue
            where = f"{instance} ({user})"
            regions = canonical_regions(objects, width, height, where, warnings)
            name = os.path.basename(str(get_image_filename(item, context.config) or ""))
            stem = _safe(os.path.splitext(name)[0] if name else instance)
            taken = used.setdefault(user, set())
            if stem in taken:
                stem = f"{stem}__{_safe(instance)}"
            taken.add(stem)
            folder = os.path.join(output_path, _safe(user))
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{stem}{self.extension}")
            self._write(path, regions, colors, f"{instance}/{user}", where, warnings)
            files.append(path)
            n_regions += len(regions)
        if unmeasured:
            from potato.media.slides import INSTALL_HINT
            warnings.append(
                f"{len(unmeasured)} item(s) were not written because the slide's size could "
                f"not be read (add image_width and image_height to the item, or make the "
                f"slide readable from media_directory; {INSTALL_HINT}): "
                f"{', '.join(sorted(set(unmeasured))[:10])}")
        blank = blank_item_warning(context, f"the {self.format_name} export")
        if blank:
            warnings.append(blank)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=warnings,
                            stats={"num_files": len(files), "num_regions": n_regions})


class QuPathGeoJSONExporter(_PathologyExporter):
    format_name = "qupath_geojson"
    description = ("Image regions as QuPath GeoJSON (level-0 slide pixels, "
                   "classification name and colour), one file per annotator and slide")
    file_extensions = [".geojson"]
    extension = ".geojson"

    def _write(self, path, regions, colors, item_key, where, warnings):
        from potato.media.pathology_regions import write_qupath
        doc = write_qupath(regions, colors, item_key, where, warnings)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)


class AsapXmlExporter(_PathologyExporter):
    format_name = "asap_xml"
    description = ("Image regions as ASAP XML (level-0 slide pixels, PartOfGroup per "
                   "label), one file per annotator and slide")
    file_extensions = [".xml"]
    extension = ".xml"

    def _write(self, path, regions, colors, item_key, where, warnings):
        from potato.media.pathology_regions import write_asap
        text = write_asap(regions, colors, where, warnings)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
