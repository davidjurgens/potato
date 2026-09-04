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
    phase_responses: List[dict] = field(default_factory=list)

    def covered_text(self, instance_id: str, span: dict) -> str:
        """The words a span covers, sliced out of the item it was drawn on.

        Spans are stored as offsets and a label, with no content: the span
        manager records `{"schema", "name", "start", "end", "target_field"}`
        and nothing else. (`extractSpanAnnotationsFromDOM` in annotation.js
        does build a `value` from the overlay text, but it reads
        `.span-overlay` elements, and a page using `instance_display` has
        none.) So every tabular export carried offsets that the reader had to
        join back to the data file to interpret, while `conll` -- which
        re-tokenises the source itself -- was the one format that showed the
        marked words.

        Deriving it here rather than storing it at write time keeps it honest:
        the text can never disagree with the offsets it came from, and spans
        recorded before this existed export the same as new ones.

        Returns "" when the offsets or the field cannot be resolved, which is
        the same thing the column held before.
        """
        item = self.items.get(instance_id)
        if not isinstance(item, dict):
            return ""

        start, end = span.get("start"), span.get("end")
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            return ""
        if start < 0 or end <= start:
            return ""

        # A multi-span page marks up several fields, and the span says which.
        field_name = span.get("target_field")
        if not field_name:
            field_name = (self.config.get("item_properties", {})
                          or {}).get("text_key", "text")

        source = item.get(field_name)
        if not isinstance(source, str):
            # Fall back to the configured text field: an older span may carry a
            # target_field the item no longer has.
            source = item.get((self.config.get("item_properties", {})
                               or {}).get("text_key", "text"))
        if not isinstance(source, str):
            return ""

        return source[start:end]


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
