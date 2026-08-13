"""
Annotation Importer Registry

Centralized registry for annotation format importers, following the same
pattern as SchemaRegistry, DisplayRegistry, ExportRegistry, and
TraceConverterRegistry.

Usage:
    from potato.importers.registry import import_registry

    result = import_registry.parse("coco", data)
    fmt = import_registry.detect_format(data)
    formats = import_registry.get_supported_formats()
"""

import logging
from typing import Any, Dict, List, Optional

from .base import BaseAnnotationImporter, ImportResult

logger = logging.getLogger(__name__)


class ImporterRegistry:
    """Centralized registry for annotation format importers."""

    def __init__(self):
        self._importers: Dict[str, BaseAnnotationImporter] = {}
        logger.debug("ImporterRegistry initialized")

    def register(self, importer: BaseAnnotationImporter) -> None:
        """Register an importer instance."""
        name = importer.format_name
        if not name:
            raise ValueError("Importer must have a non-empty format_name")
        if name in self._importers:
            raise ValueError(f"Importer '{name}' is already registered")
        self._importers[name] = importer
        logger.debug(f"Registered annotation importer: {name}")

    def get(self, name: str) -> Optional[BaseAnnotationImporter]:
        """Get an importer by format name."""
        return self._importers.get(name)

    def parse(self, format_name: str, data: Any,
              options: Optional[dict] = None) -> ImportResult:
        """
        Parse data using the named format importer.

        Args:
            format_name: Importer name (e.g. "coco")
            data: Parsed source document
            options: Format-specific options

        Returns:
            ImportResult

        Raises:
            ValueError: If the format is not registered
        """
        importer = self.get(format_name)
        if not importer:
            supported = ", ".join(sorted(self._importers.keys()))
            raise ValueError(
                f"Unknown annotation format: '{format_name}'. "
                f"Supported formats: {supported}"
            )
        return importer.parse(data, options)

    def detect_format(self, data: Any) -> Optional[str]:
        """Auto-detect the format of input data, or None."""
        for name, importer in self._importers.items():
            try:
                if importer.detect(data):
                    logger.info(f"Auto-detected annotation format: {name}")
                    return name
            except Exception:
                continue
        return None

    def get_supported_formats(self) -> List[str]:
        """Sorted list of supported format names."""
        return sorted(self._importers.keys())

    def list_importers(self) -> List[Dict[str, Any]]:
        """All registered importers with metadata."""
        return [
            importer.get_format_info()
            for importer in sorted(self._importers.values(),
                                   key=lambda i: i.format_name)
        ]

    def is_registered(self, name: str) -> bool:
        return name in self._importers


# Global registry instance
import_registry = ImporterRegistry()


def _register_builtin_importers():
    """Register built-in importers. Called on import."""
    from .coco_importer import COCOImporter

    for importer in [COCOImporter()]:
        import_registry.register(importer)

    logger.debug("Registered built-in annotation importers")


_register_builtin_importers()
