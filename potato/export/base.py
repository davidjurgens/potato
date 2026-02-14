"""
Export Base Classes

Defines the abstract base class for exporters and data structures
for passing annotation data through the export pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


@dataclass
class ExportContext:
    """
    Container for all data needed by an exporter.

    Attributes:
        config: Full Potato YAML configuration dictionary
        annotations: Flattened list of annotation records, each containing:
            - instance_id: str
            - user_id: str
            - labels: dict mapping schema_name -> {label: value}
            - spans: dict mapping schema_name -> list of span dicts
            - links: dict mapping schema_name -> list of link dicts
        items: Mapping of instance_id -> item data dict (original data)
        schemas: List of annotation_scheme configuration dicts
        output_dir: Base output directory path
    """
    config: dict
    annotations: List[dict]
    items: Dict[str, dict]
    schemas: List[dict]
    output_dir: str


@dataclass
class ExportResult:
    """
    Result of an export operation.

    Attributes:
        success: Whether the export completed successfully
        format_name: Name of the export format used
        files_written: List of file paths that were created
        warnings: Non-fatal issues encountered during export
        errors: Fatal errors that prevented full export
        stats: Summary statistics (e.g., num_images, num_annotations)
    """
    success: bool
    format_name: str
    files_written: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class BaseExporter(ABC):
    """
    Abstract base class for annotation exporters.

    Subclasses must implement:
        - export(): Perform the actual export
        - can_export(): Check if the context is compatible with this format
    """

    format_name: str = ""
    description: str = ""
    file_extensions: List[str] = []

    @abstractmethod
    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        """
        Export annotations to the target format.

        Args:
            context: ExportContext containing all annotation data
            output_path: Directory or file path for output
            options: Format-specific options

        Returns:
            ExportResult with status and written file paths
        """
        ...

    @abstractmethod
    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        """
        Check whether this exporter can handle the given context.

        Args:
            context: ExportContext to validate

        Returns:
            Tuple of (can_export: bool, reason: str).
            If can_export is False, reason explains why.
        """
        ...

    def get_format_info(self) -> dict:
        """Return metadata about this export format."""
        return {
            "format_name": self.format_name,
            "description": self.description,
            "file_extensions": self.file_extensions,
        }
