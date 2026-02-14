"""
Potato Export System

Pluggable export framework for converting Potato annotations into
standard formats (COCO, YOLO, Pascal VOC, CoNLL-2003, CoNLL-U, etc.).

Usage:
    from potato.export.registry import export_registry

    # List available exporters
    exporters = export_registry.list_exporters()

    # Export annotations
    result = export_registry.export("coco", context, output_path)

CLI:
    python -m potato.export --config config.yaml --format coco --output ./out/
"""

from .base import BaseExporter, ExportContext, ExportResult
from .registry import export_registry

__all__ = ["BaseExporter", "ExportContext", "ExportResult", "export_registry"]
