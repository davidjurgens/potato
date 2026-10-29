"""
Pathology regions on whole-slide images: QuPath GeoJSON and ASAP XML.

Input is one region file or a folder of them. Neither format names its slide,
so each file is paired with the slide that has its stem: ``case_01.geojson``
or ``case_01.svs.geojson`` with ``case_01.svs`` (or ``.ndpi``, ``.mrxs``,
``.tif``, any image). Slides are looked for in ``--image-dir`` and beside the
region file, and only there.

The project opens each slide in the deep-zoom viewer with the regions as
pre-annotations (a starting point every annotator corrects; nothing is
anyone's saved work until they save). Slides are not copied: the project's
``media_directory`` points at the folder they are in, as an absolute path,
because a slide is often gigabytes and an MRXS slide is a folder of files.

Coordinates are level-0 slide pixels in both formats, and are stored as
fractions of the slide's level-0 size, the same as anything drawn on it. The
``qupath_geojson`` and ``asap_xml`` exporters write them back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from potato.importers._common import IMAGE_EXTENSIONS

from . import _dh
from .base import ProjectImportResult, ProjectItem

SCHEME = "regions"
SLIDE_SUFFIXES = (".svs", ".ndpi", ".mrxs", ".scn", ".vms", ".vmu", ".bif", ".svslide",
                  ".tif", ".tiff") + tuple(e for e in IMAGE_EXTENSIONS if e not in (".tif", ".tiff"))


def _peek(path: Path, n: int = 8192) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.read(n)
    except OSError:
        return b""


class _PathologyImporter:
    format_name = ""
    description = ""
    file_extensions: List[str] = []
    source_name = ""

    # -- detection -------------------------------------------------------------
    def _is_region_file(self, path: Path) -> bool:
        raise NotImplementedError

    def _files(self, path: Path) -> List[Path]:
        if path.is_dir():
            return sorted(p for p in path.iterdir()
                          if p.is_file() and p.suffix.lower() in self.file_extensions
                          and self._is_region_file(p))
        return [path] if path.is_file() and self._is_region_file(path) else []

    def detect_path(self, path: Path) -> bool:
        path = Path(path)
        if path.is_file():
            return path.suffix.lower() in self.file_extensions and self._is_region_file(path)
        return path.is_dir() and bool(self._files(path))

    # -- reading ---------------------------------------------------------------
    def _load(self, path: Path, width: int, height: int):
        raise NotImplementedError

    def _slide_for(self, region_file: Path, roots: List[Path]) -> Optional[Path]:
        stem = region_file.name[: -len(region_file.suffix)]
        names = []
        if Path(stem).suffix.lower() in SLIDE_SUFFIXES:     # case_01.svs.geojson
            names.append(stem)
        names.extend(stem + suffix for suffix in SLIDE_SUFFIXES)
        for root in roots:
            for name in names:
                for candidate in (root / name, root / name.lower()):
                    if candidate.is_file() and _dh.within(candidate, roots):
                        return candidate
        return None

    def parse_path(self, path: Path, options: Optional[dict] = None) -> ProjectImportResult:
        from potato.media.pathology_regions import RegionFormatError, slide_dimensions
        options = options or {}
        path = Path(path)
        files = self._files(path)
        if not files:
            raise ValueError(f"no {self.source_name} region files at {path}")
        input_dir = path if path.is_dir() else path.parent
        roots = [Path(options["image_dir"])] if options.get("image_dir") else []
        roots.append(input_dir)
        result = ProjectImportResult(source_format=self.source_name, text_key="note")
        result.media_roots = [str(r) for r in roots]
        labels: Dict[str, Optional[str]] = {}
        tools: set = set()
        seen: set = set()
        media_dir: Optional[Path] = None

        for region_file in files:
            slide = self._slide_for(region_file, roots)
            if slide is None:
                result.warn(f"{region_file.name}: no slide named {region_file.stem}.* in "
                            f"{' or '.join(str(r) for r in roots)}; left out (pass --image-dir)")
                result.skipped["region files without a slide"] += 1
                continue
            if media_dir is None:
                media_dir = slide.parent.resolve()
            elif slide.parent.resolve() != media_dir:
                result.warn(f"{region_file.name}: its slide is in {slide.parent}, not "
                            f"{media_dir}; the project serves one slide folder, so it was "
                            f"left out")
                result.skipped["slides outside the first slide folder"] += 1
                continue
            size = slide_dimensions(slide)
            if size is None:
                from potato.media.slides import INSTALL_HINT
                result.warn(f"{slide.name}: its size could not be read, so the regions "
                            f"cannot be placed; left out. {INSTALL_HINT}")
                result.skipped["slides of unknown size"] += 1
                continue
            width, height = size
            try:
                reader = self._load(region_file, width, height)
            except (RegionFormatError, OSError) as exc:
                result.warn(f"{exc}; left out")
                result.skipped["unreadable region files"] += 1
                continue
            for message in reader.warnings:
                result.warn(message)
            for what, n in reader.counts.items():
                if what != "regions" and not what.startswith(("QuPath ", "ASAP ")):
                    result.skipped[what] += n
            for name, color in reader.labels.items():
                if name not in labels or (color and not labels[name]):
                    labels[name] = color
            tools.update(reader.tools)
            iid = _dh.unique_id(_dh.slug(Path(slide.name).stem, "slide"), seen)
            fields = {
                "note": (f"{slide.name}: {len(reader.objects)} region(s) from "
                         f"{region_file.name}"),
                "image": slide.name,
                "image_width": width,
                "image_height": height,
                "regions_file": region_file.name,
            }
            item = ProjectItem(instance_id=iid, fields=fields)
            if reader.objects:
                item.predictions[SCHEME] = reader.objects
                item.prediction_sources[SCHEME] = {"model": f"imported {self.format_name}"}
            result.items.append(item)

        if not result.items:
            raise ValueError(f"no {self.source_name} file at {path} could be paired with a "
                             f"readable slide" + (f": {result.warnings[0]}" if result.warnings else ""))
        from potato.media.pathology_regions import DEFAULT_COLOR
        result.schemes = [{
            "annotation_type": "image_annotation", "name": SCHEME,
            "description": "Correct the imported regions",
            "source_field": "image",
            # Slides need tiles: the default viewer sends the image as one file.
            "viewer": "deepzoom",
            "tiles": {"navigator": True},
            "tools": sorted(tools | {"polygon", "bbox"}),
            "labels": [{"name": n, "color": c or DEFAULT_COLOR} for n, c in labels.items()]
                      or [{"name": "region", "color": DEFAULT_COLOR}],
        }]
        result.extra_config = {"media_directory": str(media_dir)}
        return result


class QuPathImporter(_PathologyImporter):
    format_name = "qupath_geojson"
    description = "QuPath GeoJSON regions on whole-slide images (deep-zoom correction project)"
    file_extensions = [".geojson", ".json"]
    source_name = "QuPath GeoJSON"

    def _is_region_file(self, path: Path) -> bool:
        from potato.media.pathology_regions import MAX_FILE_BYTES, qupath_features
        head = _peek(path)
        if b"Feature" not in head:
            return False
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return False
            doc = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError):
            return False
        return qupath_features(doc) is not None

    def _load(self, path, width, height):
        from potato.media.pathology_regions import load_qupath
        return load_qupath(path, width, height)


class ASAPImporter(_PathologyImporter):
    format_name = "asap_xml"
    description = "ASAP XML regions on whole-slide images (deep-zoom correction project)"
    file_extensions = [".xml"]
    source_name = "ASAP XML"

    def _is_region_file(self, path: Path) -> bool:
        from potato.media.pathology_regions import is_asap
        return is_asap(_peek(path))

    def _load(self, path, width, height):
        from potato.media.pathology_regions import load_asap
        return load_asap(path, width, height)
