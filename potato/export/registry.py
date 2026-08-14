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
    from .cityscapes_exporter import CityscapesExporter
    from .cvat_exporter import CVATExporter
    from .darwin_exporter import DarwinExporter
    from .davis_exporter import DAVISExporter
    from .kitti_exporter import KITTIExporter
    from .labelme_exporter import LabelMeExporter
    from .mot_exporter import MOTExporter
    from .conll_2003_exporter import CoNLL2003Exporter
    from .conll_u_exporter import CoNLLUExporter
    from .mask_exporter import MaskExporter
    from .eaf_exporter import EAFExporter
    from .textgrid_exporter import TextGridExporter
    from .agent_eval_exporter import AgentEvalExporter
    from .coding_eval_exporter import CodingEvalExporter
    from .trajectory_correction_exporter import TrajectoryCorrectionExporter
    from .parquet_exporter import ParquetExporter
    from .tabular_exporter import CSVExporter, TSVExporter, JSONLExporter
    from .codebook_exporter import CodebookExporter
    from .quotation_report_exporter import QuotationReportExporter
    from .convokit_exporter import ConvoKitExporter
    from .keystroke_exporter import KeystrokeExporter
    from .annotation_telemetry_exporter import AnnotationTelemetryExporter

    exporters = [
        COCOExporter(),
        YOLOExporter(),
        PascalVOCExporter(),
        # Close the round trips: both formats were import-only, and a
        # one-way import means a team cannot move back or hand corrected
        # annotations to a colleague still on the source tool.
        CVATExporter(),
        LabelMeExporter(),
        # Closing the remaining migration round trips. Darwin in particular
        # matters both ways: an import-only path lets a team move off V7 but
        # never hand work back to a colleague still on it.
        DarwinExporter(),
        KITTIExporter(),
        MOTExporter(),
        CityscapesExporter(),
        DAVISExporter(),
        CoNLL2003Exporter(),
        CoNLLUExporter(),
        MaskExporter(),
        EAFExporter(),
        TextGridExporter(),
        AgentEvalExporter(),
        CodingEvalExporter(),
        TrajectoryCorrectionExporter(),
        ParquetExporter(),
        CSVExporter(),
        TSVExporter(),
        JSONLExporter(),
        CodebookExporter(),
        QuotationReportExporter(),
        # Reads and writes the ConvoKit format with the standard library only,
        # so it belongs here rather than among the optional exporters below.
        ConvoKitExporter(),
        # Reads the project SQLite database rather than user_state.json; falls
        # back to JSONL when pyarrow is absent, so it has no hard dependency.
        KeystrokeExporter(),
        AnnotationTelemetryExporter(),
    ]

    # Optional exporters with external dependencies
    try:
        from .huggingface_exporter import HuggingFaceExporter
        exporters.append(HuggingFaceExporter())
    except ImportError:
        logger.debug("HuggingFace exporter not available (missing dependencies)")

    for exporter in exporters:
        export_registry.register(exporter)

    logger.debug(f"Registered {len(exporters)} built-in exporters")


_register_builtin_exporters()
