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

        source = self._span_anchor_text(item, field_name)
        if source is None:
            # Fall back to the configured text field: an older span may carry a
            # target_field the item no longer has.
            fallback = (self.config.get("item_properties", {})
                        or {}).get("text_key", "text")
            source = self._span_anchor_text(item, fallback)
        if source is None:
            return ""

        return source[start:end]

    def _display_field_config(self, field_name: str) -> dict:
        """The `instance_display` entry for a field, or {}."""
        fields = (self.config.get("instance_display", {}) or {}).get("fields", [])
        for entry in fields or []:
            if isinstance(entry, dict) and entry.get("key") == field_name:
                return entry
        return {}

    def _span_anchor_text(self, item: dict, field_name: str):
        """The exact string a span's offsets index, or None.

        A `dialogue` field holds a list of turns, and its offsets are measured
        in the browser against the *rendered* container -- speaker labels,
        separators and all. The exporter only handled `str` sources, so every
        span on a conversational field exported with `text: ""`: not wrong, but
        unresolvable without rediscovering the join convention, and that is the
        whole coreference-over-dialogue and transcript-error-span family.

        `reconstruct_dialogue_dom_text()` is the server half of that contract
        and `/api/spans` already uses it; this is the third caller.
        """
        value = item.get(field_name)
        from potato.server_utils.displays.base import (
            concatenate_dialogue_text,
            document_dom_text,
            reconstruct_dialogue_dom_text,
            resolve_display_options,
        )

        field_config = self._display_field_config(field_name)
        if field_config.get("type") == "document":
            # A `document` field carries the same contract as `dialogue`: its
            # offsets index what the browser holds, which is the body with tags
            # stripped and entities decoded, and whitespace collapsed only when
            # the display does not apply the pre-wrap class. Returning the raw
            # string was right only for a document that happens to be plain
            # text with no markup and no entities.
            payload = (value.get("rendered_html", "")
                       if isinstance(value, dict) else value)
            if payload is None:
                return None
            return document_dom_text(payload, resolve_display_options(field_config))
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return None

        # Resolve the options the way the DISPLAY resolves them -- flat on the
        # field or nested -- or the two anchor to different strings and every
        # dialogue span exports shifted by the width of the turn numbering.
        options = resolve_display_options(field_config)
        if field_config.get("type") == "dialogue":
            return reconstruct_dialogue_dom_text(
                value,
                speaker_key=options.get("speaker_key", "speaker"),
                text_key=options.get("text_key", "text"),
                show_turn_numbers=options.get("show_turn_numbers", False),
            )
        # A list field that is not a declared dialogue: join it the way the
        # display does, which is what the offsets were measured against.
        return concatenate_dialogue_text(value)


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
