"""
Export Registry

Centralized registry for export format handlers, following the same
pattern as SchemaRegistry and DisplayRegistry.

Usage:
    from potato.export.registry import export_registry

    # List all exporters
    exporters = export_registry.list_exporters()

    # Export annotations
    result = export_registry.export("coco", context, output_path)
"""

import logging
from typing import Dict, List, Optional, Any

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class ExportRegistry:
    """
    Centralized registry for annotation export formats.

    Provides methods to register, retrieve, and invoke exporters.
    """

    def __init__(self):
        self._exporters: Dict[str, BaseExporter] = {}
        logger.debug("ExportRegistry initialized")

    def register(self, exporter: BaseExporter) -> None:
        """
        Register an exporter instance.

        Args:
            exporter: BaseExporter subclass instance

        Raises:
            ValueError: If an exporter with the same format_name is already registered
        """
        name = exporter.format_name
        if not name:
            raise ValueError("Exporter must have a non-empty format_name")
        if name in self._exporters:
            raise ValueError(f"Exporter '{name}' is already registered")

        self._exporters[name] = exporter
        logger.debug(f"Registered exporter: {name}")

    def get(self, name: str) -> Optional[BaseExporter]:
        """Get an exporter by format name."""
        return self._exporters.get(name)

    def export(self, format_name: str, context: ExportContext,
               output_path: str, options: Optional[dict] = None) -> ExportResult:
        """
        Export annotations using the named format.

        Args:
            format_name: Export format identifier (e.g., "coco", "yolo")
            context: ExportContext with annotation data
            output_path: Output directory or file path
            options: Format-specific options

        Returns:
            ExportResult

        Raises:
            ValueError: If format is not registered or cannot handle the context
        """
        exporter = self.get(format_name)
        if not exporter:
            supported = ", ".join(sorted(self._exporters.keys()))
            raise ValueError(
                f"Unknown export format: '{format_name}'. "
                f"Supported formats: {supported}"
            )

        can, reason = exporter.can_export(context)
        if not can:
            return ExportResult(
                success=False,
                format_name=format_name,
                errors=[f"Cannot export: {reason}"],
            )

        return exporter.export(context, output_path, options)

    def list_exporters(self) -> List[Dict[str, Any]]:
        """List all registered exporters with metadata."""
        return [
            exporter.get_format_info()
            for exporter in sorted(self._exporters.values(),
                                   key=lambda e: e.format_name)
        ]

    def get_supported_formats(self) -> List[str]:
        """Get sorted list of supported format names."""
        return sorted(self._exporters.keys())

    def is_registered(self, name: str) -> bool:
        """Check if a format is registered."""
        return name in self._exporters


# Global registry instance
export_registry = ExportRegistry()


def _register_builtin_exporters():
    """Register all built-in exporters. Called on import."""
    from .coco_exporter import COCOExporter
    from .yolo_exporter import YOLOExporter
    from .pascal_voc_exporter import PascalVOCExporter
    from .conll_2003_exporter import CoNLL2003Exporter
    from .conll_u_exporter import CoNLLUExporter
    from .mask_exporter import MaskExporter
    from .eaf_exporter import EAFExporter
    from .textgrid_exporter import TextGridExporter

    exporters = [
        COCOExporter(),
        YOLOExporter(),
        PascalVOCExporter(),
        CoNLL2003Exporter(),
        CoNLLUExporter(),
        MaskExporter(),
        EAFExporter(),
        TextGridExporter(),
    ]

    for exporter in exporters:
        export_registry.register(exporter)

    logger.debug(f"Registered {len(exporters)} built-in exporters")


_register_builtin_exporters()
