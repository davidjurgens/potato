"""
Text-annotation importer registry.

Mirrors :mod:`potato.importers.registry` on the text side. Kept separate from
it rather than merged because the two halves detect differently -- the CV
registry matches on a parsed JSON document, this one matches on a path -- and a
single registry would have to accept both and dispatch on which one it got.

Usage:
    from potato.importers.text.registry import text_import_registry

    fmt = text_import_registry.detect_path(Path("corpus/"))
    result = text_import_registry.parse_path(fmt, Path("corpus/"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTextImporter, TextImportResult

logger = logging.getLogger(__name__)


class TextImporterRegistry:
    """Centralized registry for text-annotation format importers."""

    def __init__(self):
        self._importers: Dict[str, BaseTextImporter] = {}
        #: Detection order, most specific first. A dict preserves insertion
        #: order, but relying on that would make the order an accident of the
        #: registration list rather than a decision, so it is explicit.
        self._detect_order: List[str] = []

    def register(self, importer: BaseTextImporter) -> None:
        name = importer.format_name
        if not name:
            raise ValueError("Importer must have a non-empty format_name")
        if name in self._importers:
            raise ValueError(f"Text importer '{name}' is already registered")
        self._importers[name] = importer
        self._detect_order.append(name)
        logger.debug("Registered text annotation importer: %s", name)

    def get(self, name: str) -> Optional[BaseTextImporter]:
        return self._importers.get(name)

    def parse_path(self, format_name: str, path: Path,
                   options: Optional[dict] = None) -> TextImportResult:
        importer = self.get(format_name)
        if not importer:
            supported = ", ".join(sorted(self._importers))
            raise ValueError(
                f"Unknown text annotation format: '{format_name}'. "
                f"Supported formats: {supported}"
            )
        return importer.parse_path(Path(path), options)

    def detect_path(self, path: Path) -> Optional[str]:
        """Guess a source's format, or None when nothing claims it."""
        path = Path(path)
        for name in self._detect_order:
            importer = self._importers[name]
            try:
                if importer.detect_path(path):
                    logger.info("Auto-detected text annotation format: %s", name)
                    return name
            except Exception:
                # A raising detect() must not take out the formats after it.
                logger.debug("%s.detect_path raised on %s", name, path,
                             exc_info=True)
                continue
        return None

    def get_supported_formats(self) -> List[str]:
        return sorted(self._importers)

    def list_importers(self) -> List[Dict[str, Any]]:
        return [self._importers[name].get_format_info()
                for name in sorted(self._importers)]

    def is_registered(self, name: str) -> bool:
        return name in self._importers


text_import_registry = TextImporterRegistry()


def _register_builtin_text_importers() -> None:
    from .brat_importer import BratImporter
    from .conll_importer import CoNLLImporter
    from .doccano_importer import DoccanoImporter
    from .prodigy_importer import ProdigyImporter
    from .qdpx_importer import QDPXImporter

    # Order matters. QDPX is a ZIP with a signature member, so it can never be
    # confused with anything else and goes first. brat is a directory of .ann
    # files, equally unambiguous. Doccano and Prodigy are BOTH JSONL and their
    # records overlap heavily -- Prodigy is checked first because it keys on
    # fields doccano never emits, while doccano's own shape would happily claim
    # a Prodigy file.
    for importer in (QDPXImporter(), BratImporter(), CoNLLImporter(),
                     ProdigyImporter(), DoccanoImporter()):
        text_import_registry.register(importer)


_register_builtin_text_importers()
