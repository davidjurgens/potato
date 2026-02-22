"""
EAF Exporter

Exports tiered annotations to ELAN Annotation Format (EAF) XML files.
EAF is the native format for ELAN (https://archive.mpi.nl/tla/elan),
a tool widely used for linguistic annotation of audio/video data.

The EAF format supports:
- Time-aligned annotations with millisecond precision
- Hierarchical tier structures with parent-child relationships
- Multiple linguistic types with different constraints
- Media references (audio/video files)
"""

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


class EAFExporter(BaseExporter):
    """
    Exports tiered annotations to ELAN Annotation Format (EAF).

    This exporter creates valid EAF 3.0 XML files that can be opened
    directly in ELAN for review or further annotation.
    """

    format_name = "eaf"
    description = "ELAN Annotation Format (EAF) for linguistic annotation"
    file_extensions = [".eaf"]

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
        Export annotations to EAF format.

        Args:
            context: ExportContext with annotation data
            output_path: Directory path for output files
            options: Optional settings:
                - author: Author name for EAF header
                - include_empty_tiers: Whether to include tiers with no annotations

        Returns:
            ExportResult with status and file paths
        """
        options = options or {}
        files_written = []
        warnings = []
        stats = {"instances": 0, "annotations": 0, "tiers": 0}

        # Create output directory
        os.makedirs(output_path, exist_ok=True)

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

                # Get media URL
                source_field = schema.get("source_field", "audio_url")
                media_url = item.get(source_field, "")

                # Generate EAF XML
                root = self._create_eaf_document(
                    schema,
                    tiered_data,
                    media_url,
                    options
                )

                # Write to file
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in instance_id)
                filename = f"{safe_id}_{schema_name}.eaf"
                filepath = os.path.join(output_path, filename)

                tree = ET.ElementTree(root)
                tree.write(filepath, encoding="utf-8", xml_declaration=True)

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

    def _create_eaf_document(
        self,
        schema: dict,
        tiered_data: dict,
        media_url: str,
        options: dict
    ) -> ET.Element:
        """
        Create the EAF XML document structure.

        Args:
            schema: The tiered_annotation schema configuration
            tiered_data: The annotation data
            media_url: URL/path to the media file
            options: Export options

        Returns:
            ET.Element root of the EAF document
        """
        # Root element
        root = ET.Element("ANNOTATION_DOCUMENT")
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:noNamespaceSchemaLocation",
                 "http://www.mpi.nl/tools/elan/EAFv3.0.xsd")
        root.set("DATE", datetime.now().isoformat())
        root.set("FORMAT", "3.0")
        root.set("VERSION", "3.0")
        root.set("AUTHOR", options.get("author", "Potato Annotation Tool"))

        # Header
        header = ET.SubElement(root, "HEADER")
        header.set("MEDIA_FILE", "")
        header.set("TIME_UNITS", "milliseconds")

        if media_url:
            media_descriptor = ET.SubElement(header, "MEDIA_DESCRIPTOR")
            media_descriptor.set("MEDIA_URL", media_url)
            media_descriptor.set("MIME_TYPE", self._get_mime_type(media_url))
            media_descriptor.set("RELATIVE_MEDIA_URL", "")

        # Property elements
        props = [
            ("lastUsedAnnotationId", "0"),
        ]
        for name, value in props:
            prop = ET.SubElement(header, "PROPERTY")
            prop.set("NAME", name)
            prop.text = value

        # TIME_ORDER - collect all unique time slots
        time_order = ET.SubElement(root, "TIME_ORDER")
        time_slots = tiered_data.get("time_slots", {})

        if not time_slots:
            # Generate from annotations
            time_slots = self._generate_time_slots(tiered_data.get("annotations", {}))

        # Sort and add time slots
        slot_items = sorted(time_slots.items(), key=lambda x: x[1])
        for slot_id, time_ms in slot_items:
            ts = ET.SubElement(time_order, "TIME_SLOT")
            ts.set("TIME_SLOT_ID", slot_id)
            ts.set("TIME_VALUE", str(int(time_ms)))

        # Create reverse mapping for looking up slot IDs
        time_to_slot = {v: k for k, v in time_slots.items()}

        # TIER elements
        tiers = schema.get("tiers", [])
        annotations = tiered_data.get("annotations", {})
        annotation_id_counter = [0]  # Use list to allow mutation in nested function

        for tier_def in tiers:
            tier_el = self._create_tier_element(
                root,
                tier_def,
                annotations.get(tier_def["name"], []),
                time_to_slot,
                annotation_id_counter
            )

        # LINGUISTIC_TYPE elements
        self._create_linguistic_types(root, tiers)

        # CONSTRAINT elements (for dependent tiers)
        self._create_constraints(root)

        return root

    def _create_tier_element(
        self,
        root: ET.Element,
        tier_def: dict,
        tier_annotations: List[dict],
        time_to_slot: dict,
        annotation_id_counter: List[int]
    ) -> ET.Element:
        """
        Create a TIER element with its annotations.

        Args:
            root: The root EAF element
            tier_def: Tier definition from schema
            tier_annotations: List of annotations for this tier
            time_to_slot: Mapping of time values to slot IDs
            annotation_id_counter: Counter for generating annotation IDs

        Returns:
            The created TIER element
        """
        tier_el = ET.SubElement(root, "TIER")
        tier_el.set("TIER_ID", tier_def["name"])

        # Determine linguistic type
        if tier_def.get("tier_type") == "dependent":
            constraint_type = tier_def.get("constraint_type", "included_in")
            ling_type = f"default-lt-{constraint_type}"
            tier_el.set("PARENT_REF", tier_def.get("parent_tier", ""))
        else:
            ling_type = "default-lt"

        tier_el.set("LINGUISTIC_TYPE_REF", tier_def.get("linguistic_type", ling_type))
        tier_el.set("DEFAULT_LOCALE", "en")

        # Add annotations
        for ann in sorted(tier_annotations, key=lambda a: a.get("start_time", 0)):
            annotation_id_counter[0] += 1
            ann_id = f"a{annotation_id_counter[0]}"

            annotation_el = ET.SubElement(tier_el, "ANNOTATION")

            if tier_def.get("tier_type") == "independent":
                # ALIGNABLE_ANNOTATION for independent tiers
                alignable = ET.SubElement(annotation_el, "ALIGNABLE_ANNOTATION")
                alignable.set("ANNOTATION_ID", ann_id)

                start_time = int(ann.get("start_time", 0))
                end_time = int(ann.get("end_time", 0))

                start_slot = self._get_or_create_slot(time_to_slot, start_time)
                end_slot = self._get_or_create_slot(time_to_slot, end_time)

                alignable.set("TIME_SLOT_REF1", start_slot)
                alignable.set("TIME_SLOT_REF2", end_slot)

                value_el = ET.SubElement(alignable, "ANNOTATION_VALUE")
                value_el.text = ann.get("value") or ann.get("label", "")

            else:
                # REF_ANNOTATION for dependent tiers
                ref_ann = ET.SubElement(annotation_el, "REF_ANNOTATION")
                ref_ann.set("ANNOTATION_ID", ann_id)

                # Reference parent annotation
                parent_id = ann.get("parent_id", "")
                if parent_id:
                    # Convert internal ID to EAF annotation ID
                    # For simplicity, use annotation reference
                    ref_ann.set("ANNOTATION_REF", parent_id)

                value_el = ET.SubElement(ref_ann, "ANNOTATION_VALUE")
                value_el.text = ann.get("value") or ann.get("label", "")

        return tier_el

    def _get_or_create_slot(
        self,
        time_to_slot: dict,
        time_ms: int
    ) -> str:
        """Get existing slot ID or create a new mapping."""
        if time_ms in time_to_slot:
            return time_to_slot[time_ms]

        # Create new slot
        slot_id = f"ts{len(time_to_slot) + 1}"
        time_to_slot[time_ms] = slot_id
        return slot_id

    def _generate_time_slots(
        self,
        annotations: Dict[str, List[dict]]
    ) -> Dict[str, int]:
        """Generate time slots from annotations."""
        times: Set[int] = set()

        for tier_anns in annotations.values():
            for ann in tier_anns:
                if ann.get("start_time") is not None:
                    times.add(int(ann["start_time"]))
                if ann.get("end_time") is not None:
                    times.add(int(ann["end_time"]))

        return {
            f"ts{i+1}": time
            for i, time in enumerate(sorted(times))
        }

    def _create_linguistic_types(
        self,
        root: ET.Element,
        tiers: List[dict]
    ) -> None:
        """Create LINGUISTIC_TYPE elements for all tier types."""
        # Default linguistic type for independent tiers
        lt = ET.SubElement(root, "LINGUISTIC_TYPE")
        lt.set("LINGUISTIC_TYPE_ID", "default-lt")
        lt.set("TIME_ALIGNABLE", "true")
        lt.set("GRAPHIC_REFERENCES", "false")

        # Linguistic types for each constraint type
        constraint_types = set()
        for tier in tiers:
            if tier.get("tier_type") == "dependent":
                constraint_types.add(tier.get("constraint_type", "included_in"))

        for constraint in constraint_types:
            lt = ET.SubElement(root, "LINGUISTIC_TYPE")
            lt.set("LINGUISTIC_TYPE_ID", f"default-lt-{constraint}")
            lt.set("CONSTRAINTS", self._constraint_to_elan(constraint))
            lt.set("TIME_ALIGNABLE", "true" if constraint in ("time_subdivision", "included_in") else "false")
            lt.set("GRAPHIC_REFERENCES", "false")

    def _constraint_to_elan(self, constraint_type: str) -> str:
        """Map constraint type to ELAN constraint stereotype."""
        mapping = {
            "time_subdivision": "Time_Subdivision",
            "included_in": "Included_In",
            "symbolic_association": "Symbolic_Association",
            "symbolic_subdivision": "Symbolic_Subdivision",
        }
        return mapping.get(constraint_type, "Included_In")

    def _create_constraints(self, root: ET.Element) -> None:
        """Create CONSTRAINT elements for the standard ELAN constraint types."""
        constraints = [
            ("Time_Subdivision", "Time subdivision of parent annotation's time interval, no time gaps allowed within this interval"),
            ("Symbolic_Subdivision", "Symbolic subdivision of a parent annotation. Annotations refer to the same time interval as the parent"),
            ("Symbolic_Association", "1-1 association with a parent annotation"),
            ("Included_In", "Time alignable annotations within the parent annotation's time interval, gaps are allowed"),
        ]

        for constraint_id, description in constraints:
            constraint = ET.SubElement(root, "CONSTRAINT")
            constraint.set("DESCRIPTION", description)
            constraint.set("STEREOTYPE", constraint_id)

    def _get_mime_type(self, url: str) -> str:
        """Determine MIME type from file extension."""
        url_lower = url.lower()
        if url_lower.endswith((".mp4", ".m4v")):
            return "video/mp4"
        elif url_lower.endswith((".webm",)):
            return "video/webm"
        elif url_lower.endswith((".avi",)):
            return "video/avi"
        elif url_lower.endswith((".mov",)):
            return "video/quicktime"
        elif url_lower.endswith((".wav",)):
            return "audio/wav"
        elif url_lower.endswith((".mp3",)):
            return "audio/mpeg"
        elif url_lower.endswith((".ogg", ".oga")):
            return "audio/ogg"
        elif url_lower.endswith((".flac",)):
            return "audio/flac"
        else:
            return "audio/x-wav"  # Default
