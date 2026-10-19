"""
Whole-project importers: Label Studio and Argilla.

See :mod:`potato.importers.projects.base` for why these are separate from the
CV and text importers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .argilla import ArgillaImporter
from .label_studio import LabelStudioImporter

IMPORTERS = {
    "label_studio": LabelStudioImporter(),
    "argilla": ArgillaImporter(),
}

#: Spellings people type for the same format.
ALIASES = {
    "label-studio": "label_studio",
    "labelstudio": "label_studio",
    "ls": "label_studio",
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
