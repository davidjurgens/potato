"""
TextGrid Exporter

Exports tiered annotations to Praat TextGrid format.
TextGrid is the native format for Praat (https://www.fon.hum.uva.nl/praat/),
a tool widely used for phonetic analysis and annotation.

The TextGrid format supports:
- Interval tiers (segments with start/end times)
- Point tiers (single-point annotations)
- Multiple tiers with independent time alignments

Note: TextGrid doesn't natively support hierarchical relationships between
tiers, so the export flattens the hierarchy while preserving all annotations.
"""

import logging
import os
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class TextGridExporter(BaseExporter):
    """
    Exports tiered annotations to Praat TextGrid format.

    This exporter creates TextGrid files that can be opened in Praat
    for phonetic analysis or further annotation.
    """

    format_name = "textgrid"
    description = "Praat TextGrid format for phonetic annotation"
    file_extensions = [".TextGrid"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        """
        Check if the context contains tiered_annotation schema.

        Args:
            context: ExportContext to validate

        Returns:
            Tuple of (can_export, reason)
        """
        for schema in context.schemas:
            if schema.get("annotation_type") == "tiered_annotation":
                return True, ""

        return False, "No tiered_annotation schema found in configuration"

    def export(
        self,
        context: ExportContext,
        output_path: str,
        options: Optional[dict] = None
    ) -> ExportResult:
        """
        Export annotations to TextGrid format.

        Args:
            context: ExportContext with annotation data
            output_path: Directory path for output files
            options: Optional settings:
                - format: "long" (default) or "short" TextGrid format
                - fill_gaps: Whether to fill gaps between annotations

        Returns:
            ExportResult with status and file paths
        """
        options = options or {}
        files_written = []
        warnings = []
        stats = {"instances": 0, "annotations": 0, "tiers": 0}

        # Create output directory
        os.makedirs(output_path, exist_ok=True)

        use_short_format = options.get("format", "long") == "short"

        # Find tiered_annotation schemas
        tiered_schemas = [
            s for s in context.schemas
            if s.get("annotation_type") == "tiered_annotation"
        ]

        for instance_id, item in context.items.items():
            # Get annotations for this instance
            instance_annotations = [
                a for a in context.annotations
                if a.get("instance_id") == instance_id
            ]

            for schema in tiered_schemas:
                schema_name = schema.get("name", "tiered")

                # Get tiered annotation data for this schema
                tiered_data = None
                for ann in instance_annotations:
                    if schema_name in ann.get("labels", {}):
                        try:
                            import json
                            raw_value = ann["labels"][schema_name]
                            if isinstance(raw_value, str):
                                tiered_data = json.loads(raw_value)
                            elif isinstance(raw_value, dict):
                                tiered_data = raw_value
                        except (json.JSONDecodeError, TypeError):
                            pass
                        break

                if not tiered_data:
                    continue

                # Generate TextGrid content
                content = self._create_textgrid(
                    schema,
                    tiered_data,
                    use_short_format
                )

                # Write to file
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in instance_id)
                filename = f"{safe_id}_{schema_name}.TextGrid"
                filepath = os.path.join(output_path, filename)

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)

                files_written.append(filepath)
                stats["instances"] += 1

                # Count annotations
                annotations = tiered_data.get("annotations", {})
                for tier_anns in annotations.values():
                    stats["annotations"] += len(tier_anns)
                stats["tiers"] = len(schema.get("tiers", []))

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats=stats
        )

    def _create_textgrid(
        self,
        schema: dict,
        tiered_data: dict,
        use_short_format: bool = False
    ) -> str:
        """
        Create TextGrid file content.

        Args:
            schema: The tiered_annotation schema configuration
            tiered_data: The annotation data
            use_short_format: Whether to use short TextGrid format

        Returns:
            TextGrid file content as string
        """
        tiers = schema.get("tiers", [])
        annotations = tiered_data.get("annotations", {})

        # Calculate time bounds
        min_time = 0.0
        max_time = self._get_max_time(annotations)

        if max_time == 0:
            max_time = 1.0  # Default duration if no annotations

        if use_short_format:
            return self._create_short_textgrid(tiers, annotations, min_time, max_time)
        else:
            return self._create_long_textgrid(tiers, annotations, min_time, max_time)

    def _create_long_textgrid(
        self,
        tiers: List[dict],
        annotations: Dict[str, List[dict]],
        min_time: float,
        max_time: float
    ) -> str:
        """Create long format TextGrid (more readable)."""
        lines = []
        lines.append('File type = "ooTextFile"')
        lines.append('Object class = "TextGrid"')
        lines.append('')
        lines.append(f'xmin = {min_time}')
        lines.append(f'xmax = {max_time}')
        lines.append('tiers? <exists>')
        lines.append(f'size = {len(tiers)}')
        lines.append('item []:')

        for i, tier_def in enumerate(tiers, 1):
            tier_name = tier_def["name"]
            tier_anns = annotations.get(tier_name, [])

            # Sort annotations by start time
            sorted_anns = sorted(tier_anns, key=lambda a: a.get("start_time", 0))

            # Fill gaps to create complete intervals
            intervals = self._create_intervals(sorted_anns, min_time, max_time)

            lines.append(f'    item [{i}]:')
            lines.append('        class = "IntervalTier"')
            lines.append(f'        name = "{self._escape_text(tier_name)}"')
            lines.append(f'        xmin = {min_time}')
            lines.append(f'        xmax = {max_time}')
            lines.append(f'        intervals: size = {len(intervals)}')

            for j, interval in enumerate(intervals, 1):
                lines.append(f'        intervals [{j}]:')
                lines.append(f'            xmin = {interval["start"]}')
                lines.append(f'            xmax = {interval["end"]}')
                lines.append(f'            text = "{self._escape_text(interval["text"])}"')

        return '\n'.join(lines)

    def _create_short_textgrid(
        self,
        tiers: List[dict],
        annotations: Dict[str, List[dict]],
        min_time: float,
        max_time: float
    ) -> str:
        """Create short format TextGrid (more compact)."""
        lines = []
        lines.append('File type = "ooTextFile"')
        lines.append('Object class = "TextGrid"')
        lines.append('')
        lines.append(str(min_time))
        lines.append(str(max_time))
        lines.append('<exists>')
        lines.append(str(len(tiers)))

        for tier_def in tiers:
            tier_name = tier_def["name"]
            tier_anns = annotations.get(tier_name, [])

            # Sort and create intervals
            sorted_anns = sorted(tier_anns, key=lambda a: a.get("start_time", 0))
            intervals = self._create_intervals(sorted_anns, min_time, max_time)

            lines.append('"IntervalTier"')
            lines.append(f'"{self._escape_text(tier_name)}"')
            lines.append(str(min_time))
            lines.append(str(max_time))
            lines.append(str(len(intervals)))

            for interval in intervals:
                lines.append(str(interval["start"]))
                lines.append(str(interval["end"]))
                lines.append(f'"{self._escape_text(interval["text"])}"')

        return '\n'.join(lines)

    def _create_intervals(
        self,
        annotations: List[dict],
        min_time: float,
        max_time: float
    ) -> List[dict]:
        """
        Create a complete list of intervals, filling gaps with empty intervals.

        Args:
            annotations: Sorted list of annotations
            min_time: Start time of the TextGrid
            max_time: End time of the TextGrid

        Returns:
            List of interval dicts with start, end, and text
        """
        intervals = []
        current_time = min_time

        for ann in annotations:
            start_sec = ann.get("start_time", 0) / 1000.0  # Convert ms to seconds
            end_sec = ann.get("end_time", 0) / 1000.0
            text = ann.get("value") or ann.get("label", "")

            # Add empty interval for gap
            if start_sec > current_time + 0.0001:  # Small tolerance
                intervals.append({
                    "start": current_time,
                    "end": start_sec,
                    "text": ""
                })

            # Add annotation interval
            intervals.append({
                "start": start_sec,
                "end": end_sec,
                "text": text
            })
            current_time = end_sec

        # Add final empty interval if needed
        if current_time < max_time - 0.0001:
            intervals.append({
                "start": current_time,
                "end": max_time,
                "text": ""
            })

        # If no intervals at all, create one empty interval
        if not intervals:
            intervals.append({
                "start": min_time,
                "end": max_time,
                "text": ""
            })

        return intervals

    def _get_max_time(self, annotations: Dict[str, List[dict]]) -> float:
        """Get the maximum end time from all annotations in seconds."""
        max_time = 0.0

        for tier_anns in annotations.values():
            for ann in tier_anns:
                end_time = ann.get("end_time", 0)
                if end_time:
                    max_time = max(max_time, end_time / 1000.0)  # Convert ms to seconds

        return max_time

    def _escape_text(self, text: str) -> str:
        """Escape special characters for TextGrid format."""
        if not text:
            return ""
        # Escape quotes and backslashes
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        # Remove or replace newlines
        text = text.replace('\n', ' ').replace('\r', '')
        return text
