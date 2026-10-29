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
    from .kitti3d_exporter import KITTI3DExporter
    from .volume_exporter import DicomSegExporter, DicomSrExporter, VolumeNiftiExporter
    from .pathology_exporter import AsapXmlExporter, QuPathGeoJSONExporter
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
    from .qdpx_exporter import QDPXExporter
    from .quotation_report_exporter import QuotationReportExporter
    from .convokit_exporter import ConvoKitExporter
    from .keystroke_exporter import KeystrokeExporter
    from .runtime_exporter import JsPsychExporter, RuntimeExporter
    from .web_annotation_exporter import WebAnnotationExporter
    from .listening_exporter import ListeningTestExporter
    from .signal_exporter import IntervalLabelExporter, BIDSEventsExporter
    from .peak_exporter import PeakTableExporter
    from .chemistry_exporter import ChemistryExporter
    from .microscopy_exporter import MicroscopyExporter
    from .ontology_terms_exporter import OntologyTermsExporter
    from .geo_exporter import GeoJSONExporter, GeoOverlapExporter
    from .camera_trap_exporter import MegaDetectorExporter, CamtrapDPExporter, DarwinCoreExporter
    from .bioacoustics_exporter import RavenExporter, AudacityLabelsExporter
    from .iiif_exporter import IIIFAnnotationExporter
    from .page_xml_exporter import PageXMLExporter
    from .tei_exporter import TEIExporter
    from .cultural_domain_exporter import CulturalDomainExporter
    from .ego_network_exporter import EgoNetworkExporter
    from .incentives_exporter import IncentivesExporter
    from .interlinear_exporter import FlexTextExporter, ToolboxExporter, IGTExporter
    from .survey_experiment_exporter import SurveyExperimentExporter
    from .reliability_exporter import ReliabilityExporter
    from .consensus_exporter import ConsensusExporter
    from .lextale_exporter import LexTALEExporter
    from .data_package_exporter import DataPackageExporter, PsychDSExporter
    from .annotation_telemetry_exporter import AnnotationTelemetryExporter
    from .episode_exporter import EpisodeJsonlExporter
    from .adjudication_exporter import AdjudicationExporter
    from .labeling_engine_exporter import LabelingEngineExporter
    from .schedule_exporter import ScheduleExporter

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
        KITTI3DExporter(),
        VolumeNiftiExporter(),
        DicomSegExporter(),
        DicomSrExporter(),
        # Pathology regions on whole-slide images, in slide pixels at level 0.
        QuPathGeoJSONExporter(),
        AsapXmlExporter(),
        MOTExporter(),
        CityscapesExporter(),
        DAVISExporter(),
        CoNLL2003Exporter(),
        CoNLLUExporter(),
        MaskExporter(),
        EAFExporter(),
        TextGridExporter(),
        AgentEvalExporter(),
        # Embodied episodes: a per-frame sidecar keyed by
        # (episode_id, frame_index), so the read-only source
        # dataset is never rewritten.
        EpisodeJsonlExporter(),
        CodingEvalExporter(),
        TrajectoryCorrectionExporter(),
        ParquetExporter(),
        CSVExporter(),
        TSVExporter(),
        JSONLExporter(),
        CodebookExporter(),
        # REFI-QDA project exchange: the format qualitative researchers
        # actually move projects with, and the only way a Potato project can
        # be handed to a colleague on NVivo, ATLAS.ti or MAXQDA.
        QDPXExporter(),
        QuotationReportExporter(),
        # Reads and writes the ConvoKit format with the standard library only,
        # so it belongs here rather than among the optional exporters below.
        ConvoKitExporter(),
        # Reads the project SQLite database rather than user_state.json; falls
        # back to JSONL when pyarrow is absent, so it has no hard dependency.
        KeystrokeExporter(),
        # Trial data from embedded jsPsych timelines, also from the SQLite store.
        RuntimeExporter(),
        WebAnnotationExporter(),
        ListeningTestExporter(),
        IntervalLabelExporter(), BIDSEventsExporter(),
        PeakTableExporter(),
        ChemistryExporter(),
        MicroscopyExporter(),
        OntologyTermsExporter(),
        GeoJSONExporter(), GeoOverlapExporter(),
        # Ecology: camera-trap review and bioacoustic boxes.
        MegaDetectorExporter(), CamtrapDPExporter(), DarwinCoreExporter(),
        RavenExporter(), AudacityLabelsExporter(),
        IIIFAnnotationExporter(), PageXMLExporter(), TEIExporter(),
        CulturalDomainExporter(),
        EgoNetworkExporter(),
        IncentivesExporter(),
        FlexTextExporter(), ToolboxExporter(), IGTExporter(),
        SurveyExperimentExporter(),
        ReliabilityExporter(),
        # Zooniverse-style consensus: vote fractions, point clusters, box groups.
        ConsensusExporter(),
        LexTALEExporter(),
        DataPackageExporter(),
        PsychDSExporter(),
        JsPsychExporter(),
        AnnotationTelemetryExporter(),
        # The adjudicated label is the deliverable of an adjudicated
        # workflow, and no other format here carried it: csv, jsonl and
        # parquet all read per-annotator state, so an export shipped the
        # disagreements and not the resolution.
        AdjudicationExporter(),
        # The labeling engine's deliverable: resolved labels (machine and
        # human) with provenance, and the quality certificate.
        LabelingEngineExporter(),
        # Scheduled sessions, compliance and the notification log.
        ScheduleExporter(),
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
