"""
Whole-project importers: Label Studio, Argilla, Zooniverse, and tiered TextGrid / EAF files.

See :mod:`potato.importers.projects.base` for why these are separate from the
CV and text importers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .argilla import ArgillaImporter
from .label_studio import LabelStudioImporter
from .ibex import IbexImporter
from .interlinear import FlexTextImporter, ToolboxImporter
from .textgrid import EAFImporter, TextGridImporter
from .zooniverse import ZooniverseImporter
from .camera_traps import COCOCameraTrapsImporter, MegaDetectorImporter
from .bioacoustics import AudacityLabelsImporter, BirdNETImporter, RavenImporter
from .iiif import IIIFImporter
from .page_xml import PageXMLImporter
from .pathology import ASAPImporter, QuPathImporter
from .web_annotation import WebAnnotationImporter

IMPORTERS = {
    "label_studio": LabelStudioImporter(),
    "argilla": ArgillaImporter(),
    "textgrid": TextGridImporter(),
    "eaf": EAFImporter(),
    "zooniverse": ZooniverseImporter(),
    "ibex": IbexImporter(),
    "flextext": FlexTextImporter(),
    "toolbox": ToolboxImporter(),
    "megadetector": MegaDetectorImporter(),
    "coco_camera_traps": COCOCameraTrapsImporter(),
    # BirdNET before Raven: its selection tables are Raven tables too.
    "birdnet": BirdNETImporter(),
    "raven": RavenImporter(),
    "audacity_labels": AudacityLabelsImporter(),
    # IIIF before Web Annotation: a manifest holds annotation pages too.
    "iiif": IIIFImporter(),
    "web_annotation": WebAnnotationImporter(),
    "page_xml": PageXMLImporter(),
    "qupath_geojson": QuPathImporter(),
    "asap_xml": ASAPImporter(),
}

#: Spellings people type for the same format.
ALIASES = {
    "label-studio": "label_studio",
    "labelstudio": "label_studio",
    "ls": "label_studio",
    "praat": "textgrid",
    "elan": "eaf",
    "panoptes": "zooniverse",
    "pcibex": "ibex",
    "penncontroller": "ibex",
    "flex": "flextext",
    "fieldworks": "flextext",
    "shoebox": "toolbox",
    "sfm": "toolbox",
    "md": "megadetector",
    "cct": "coco_camera_traps",
    "coco-camera-traps": "coco_camera_traps",
    "audacity": "audacity_labels",
    "raven_selection": "raven",
    "iiif_manifest": "iiif",
    "w3c": "web_annotation",
    "web-annotation": "web_annotation",
    "hypothesis": "web_annotation",
    "page": "page_xml",
    "transkribus": "page_xml",
    "qupath": "qupath_geojson",
    "asap": "asap_xml",
}


def resolve(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = ALIASES.get(name.lower(), name.lower())
    return key if key in IMPORTERS else None


def detect(path: str) -> Optional[str]:
    for name, importer in IMPORTERS.items():
        try:
            if importer.detect_path(Path(path)):
                return name
        except (OSError, ValueError):
            continue
    return None


def list_importers():
    return [{"name": name, "description": imp.description,
             "file_extensions": imp.file_extensions}
            for name, imp in IMPORTERS.items()]
