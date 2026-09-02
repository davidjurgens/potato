"""
Text-annotation importers: brat, CoNLL, doccano, Prodigy and REFI-QDA.

Kept in a subpackage rather than beside the CV importers so that
``potato/importers/*_importer.py`` keeps meaning "an image format", which is
what ``tests/unit/test_importer_contract.py`` globs for. See
:mod:`potato.importers.text.base` for why the two contracts are separate.
"""

from .base import (BaseTextImporter, ImportedDocument, ImportedSpan,
                   TextImportResult)
from .registry import text_import_registry

__all__ = [
    "BaseTextImporter",
    "ImportedDocument",
    "ImportedSpan",
    "TextImportResult",
    "text_import_registry",
]
