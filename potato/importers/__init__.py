"""
Annotation format importers.

The mirror of ``potato.export``: reads existing annotation files into the shape
the annotation UI consumes, so model output or work from another platform can
be corrected in Potato rather than re-created.

Usage:
    from potato.importers import import_registry

    result = import_registry.parse("coco", data)
    fmt = import_registry.detect_format(data)

CLI:
    python -m potato.importers --input instances.json --output-dir project/
"""

from .base import BaseAnnotationImporter, ImportedImage, ImportResult
from .registry import ImporterRegistry, import_registry

__all__ = [
    "BaseAnnotationImporter",
    "ImportedImage",
    "ImportResult",
    "ImporterRegistry",
    "import_registry",
]
