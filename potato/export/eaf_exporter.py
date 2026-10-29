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

#: Constraints whose annotations take their time from the parent.
SYMBOLIC = {"symbolic_association", "symbolic_subdivision"}


def _constraint_of(tier_def: dict) -> Optional[str]:
    """A dependent tier's constraint (``included_in`` when unset), else None."""
    if tier_def.get("tier_type") != "dependent":
        return None
    constraint = (tier_def.get("constraint_type") or "included_in").lower()
    return "included_in" if constraint == "none" else constraint


def _linguistic_type_of(tier_def: dict) -> str:
    constraint = _constraint_of(tier_def)
    return tier_def.get("linguistic_type") or (
        f"default-lt-{constraint}" if constraint else "default-lt")


from .textgrid_exporter import tiered_payload

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
        options = dict(options or {})
        files_written = []
        warnings = []
        self._run_warnings = warnings
        options.setdefault("_task_dir", (context.config or {}).get("task_dir"))
        stats = {"instances": 0, "annotations": 0, "tiers": 0}

        # Create output directory
        os.makedirs(output_path, exist_ok=True)

        # Find tiered_annotation schemas
        tiered_schemas = [
            s for s in context.schemas
            if s.get("annotation_type") == "tiered_annotation"
        ]
        for schema in tiered_schemas:
            point_tiers = [t.get("name") for t in schema.get("tiers", []) if t.get("point")]
            if point_tiers:
                warnings.append(
                    f"{schema.get('name')}: EAF has no point tiers, so the points on "
                    f"{', '.join(point_tiers)} are written as annotations that start and "
                    f"end on the same time slot. The textgrid export keeps them as points.")

        for instance_id, item in context.items.items():
            # Get annotations for this instance
            instance_annotations = [
                a for a in context.annotations
                if a.get("instance_id") == instance_id
            ]

            for schema in tiered_schemas:
                schema_name = schema.get("name", "tiered")

                # Every annotator's answer for this schema. Taking the first
                # and breaking dropped everyone after them from the export.
                answers = [
                    (str(ann.get("user_id") or ""), tiered_payload(ann["labels"][schema_name]))
                    for ann in instance_annotations
                    if schema_name in ann.get("labels", {})
                ]
                answers = [(user, data) for user, data in answers if data]

                for user, tiered_data in answers:

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
                    # One annotator keeps the old name; several get one file each.
                    if len(answers) > 1:
                        safe_user = "".join(c if c.isalnum() or c in "-_" else "_" for c in user)
                        filename = f"{safe_id}_{safe_user}_{schema_name}.eaf"
                    else:
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
            absolute, relative = self._media_urls(media_url, options.get("_task_dir"))
            media_descriptor = ET.SubElement(header, "MEDIA_DESCRIPTOR")
            media_descriptor.set("MEDIA_URL", absolute)
            media_descriptor.set("MIME_TYPE", self._get_mime_type(media_url))
            if relative:
                media_descriptor.set("RELATIVE_MEDIA_URL", relative)

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
        initial_slot_count = len(time_to_slot)

        # TIER elements
        tiers = schema.get("tiers", [])
        annotations = tiered_data.get("annotations", {})

        # EAF ids for every annotation before any tier is written, so a child
        # can name a parent written after it. ANNOTATION_REF used to carry
        # Potato's internal id, which no ANNOTATION_ID in the file matched.
        eaf_ids: Dict[str, str] = {}
        counter = 0
        for tier_def in tiers:
            for ann in sorted(annotations.get(tier_def["name"], []),
                              key=lambda a: a.get("start_time", 0)):
                counter += 1
                key = ann.get("id") or f"_anon{counter}"
                ann.setdefault("id", key)
                eaf_ids[key] = f"a{counter}"

        for tier_def in tiers:
            self._create_tier_element(
                root,
                tier_def,
                annotations.get(tier_def["name"], []),
                annotations.get(tier_def.get("parent_tier") or "", []),
                time_to_slot,
                eaf_ids
            )

        # Add any dynamically created time slots to TIME_ORDER
        if len(time_to_slot) > initial_slot_count:
            slot_to_time = {v: k for k, v in time_to_slot.items()}
            new_slots = sorted(
                [(sid, slot_to_time[sid]) for sid in slot_to_time if sid not in time_slots],
                key=lambda x: x[1]
            )
            for slot_id, time_ms in new_slots:
                ts = ET.SubElement(time_order, "TIME_SLOT")
                ts.set("TIME_SLOT_ID", slot_id)
                ts.set("TIME_VALUE", str(int(time_ms)))

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
        parent_annotations: List[dict],
        time_to_slot: dict,
        eaf_ids: Dict[str, str]
    ) -> ET.Element:
        """
        Create a TIER element with its annotations.

        Time-aligned tiers (independent, ``included_in``, ``time_subdivision``)
        get ALIGNABLE_ANNOTATIONs with their own time slots. Symbolic tiers get
        REF_ANNOTATIONs naming the parent's EAF id; a child saved without a
        parent link is matched to the parent annotation whose span holds it.
        """
        tier_el = ET.SubElement(root, "TIER")
        tier_el.set("TIER_ID", tier_def["name"])

        constraint = _constraint_of(tier_def)
        if constraint:
            tier_el.set("PARENT_REF", tier_def.get("parent_tier", ""))
        if tier_def.get("participant"):
            tier_el.set("PARTICIPANT", str(tier_def["participant"]))
        tier_el.set("LINGUISTIC_TYPE_REF", _linguistic_type_of(tier_def))
        tier_el.set("DEFAULT_LOCALE", "en")

        symbolic = constraint in SYMBOLIC
        for ann in sorted(tier_annotations, key=lambda a: a.get("start_time", 0)):
            ann_id = eaf_ids[ann["id"]]
            annotation_el = ET.SubElement(tier_el, "ANNOTATION")
            value = ann.get("value") or ann.get("label", "")

            if not symbolic:
                alignable = ET.SubElement(annotation_el, "ALIGNABLE_ANNOTATION")
                alignable.set("ANNOTATION_ID", ann_id)
                start_slot = self._get_or_create_slot(
                    time_to_slot, int(round(float(ann.get("start_time", 0)))))
                end_slot = self._get_or_create_slot(
                    time_to_slot, int(round(float(ann.get("end_time", 0)))))
                alignable.set("TIME_SLOT_REF1", start_slot)
                alignable.set("TIME_SLOT_REF2", end_slot)
                ET.SubElement(alignable, "ANNOTATION_VALUE").text = value
                continue

            ref_ann = ET.SubElement(annotation_el, "REF_ANNOTATION")
            ref_ann.set("ANNOTATION_ID", ann_id)
            parent = eaf_ids.get(ann.get("parent_id") or "")
            if parent is None:
                holder = next((p for p in parent_annotations
                               if p.get("start_time", 0) <= ann.get("start_time", 0)
                               and ann.get("end_time", 0) <= p.get("end_time", 0)), None)
                parent = eaf_ids.get(holder["id"]) if holder else None
            if not parent:
                # ANNOTATION_REF is required; a REF_ANNOTATION without one is
                # not a valid EAF file, so the orphan is left out and named.
                tier_el.remove(annotation_el)
                getattr(self, "_run_warnings", []).append(
                    f"{tier_def['name']}: '{value}' has no parent annotation on "
                    f"{tier_def.get('parent_tier')}; left out of the EAF file")
                continue
            ref_ann.set("ANNOTATION_REF", parent)
            ET.SubElement(ref_ann, "ANNOTATION_VALUE").text = value

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
        """Define every linguistic type a tier refers to.

        A tier imported from ELAN keeps its own type name (``ft``,
        ``gloss-lt``); that name used to be written on the tier with no
        LINGUISTIC_TYPE defining it, which ELAN refuses.
        """
        defined: Dict[str, Optional[str]] = {"default-lt": None}
        for tier in tiers:
            defined.setdefault(_linguistic_type_of(tier), _constraint_of(tier))
        for type_id, constraint in defined.items():
            lt = ET.SubElement(root, "LINGUISTIC_TYPE")
            lt.set("LINGUISTIC_TYPE_ID", type_id)
            if constraint:
                lt.set("CONSTRAINTS", self._constraint_to_elan(constraint))
            lt.set("TIME_ALIGNABLE", "false" if constraint in SYMBOLIC else "true")
            lt.set("GRAPHIC_REFERENCES", "false")

    @staticmethod
    def _media_urls(media_url: str, task_dir: Optional[str]) -> Tuple[str, str]:
        """MEDIA_URL and RELATIVE_MEDIA_URL for the header.

        The item holds the path Potato serves the file at (``/media/x.wav``),
        which means nothing to ELAN. A file that exists under the task
        directory gets its absolute ``file://`` URL; every local file gets
        ``./<name>``, which ELAN tries first, so the EAF opens once it sits
        beside the recording. A web URL is kept as it is.
        """
        from urllib.parse import quote, urlparse
        if urlparse(media_url).scheme in ("http", "https"):
            return media_url, ""
        name = os.path.basename(media_url.rstrip("/"))
        relative = f"./{name}" if name else ""
        if task_dir:
            candidate = os.path.abspath(os.path.join(task_dir, media_url.lstrip("/")))
            if os.path.isfile(candidate):
                return "file://" + quote(candidate), relative
        return (f"file:///{quote(name)}" if name else media_url), relative

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
