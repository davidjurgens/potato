"""
Schema Registry

Provides a centralized registry for managing annotation schema types.
This module serves as the single source of truth for available annotation
types and their generators, replacing the hardcoded dictionary in front_end.py.

Usage:
    from potato.server_utils.schemas.registry import schema_registry

    # Get a schema generator
    generator = schema_registry.get("radio")

    # Generate layout for an annotation scheme
    html, keybindings = schema_registry.generate(annotation_scheme_dict)

    # List all available schemas
    schemas = schema_registry.list_schemas()
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SchemaDefinition:
    """
    Defines metadata and generator for an annotation schema type.

    Attributes:
        name: Unique identifier for the schema type (e.g., "radio", "multiselect")
        generator: Callable that generates HTML and keybindings for this schema type
        required_fields: List of required configuration fields
        optional_fields: List of optional configuration fields
        supports_keybindings: Whether this schema type supports keyboard shortcuts
        description: Human-readable description of the schema type
    """
    name: str
    generator: Callable[[Dict[str, Any]], Tuple[str, List[Tuple[str, str]]]]
    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    supports_keybindings: bool = True
    description: str = ""


class SchemaRegistry:
    """
    Centralized registry for annotation schema types.

    Provides methods to register, retrieve, and list schema types,
    as well as generate layouts from annotation scheme configurations.
    """

    def __init__(self):
        self._schemas: Dict[str, SchemaDefinition] = {}
        logger.debug("SchemaRegistry initialized")

    def register(self, schema: SchemaDefinition) -> None:
        """
        Register a new schema type.

        Args:
            schema: SchemaDefinition to register

        Raises:
            ValueError: If a schema with the same name is already registered
        """
        if schema.name in self._schemas:
            raise ValueError(f"Schema '{schema.name}' is already registered")

        self._schemas[schema.name] = schema
        logger.debug(f"Registered schema: {schema.name}")

    def get(self, name: str) -> Optional[SchemaDefinition]:
        """
        Get a schema definition by name.

        Args:
            name: The schema type name

        Returns:
            SchemaDefinition if found, None otherwise
        """
        return self._schemas.get(name)

    def get_generator(self, name: str) -> Optional[Callable]:
        """
        Get the generator function for a schema type.

        Args:
            name: The schema type name

        Returns:
            Generator callable if found, None otherwise
        """
        schema = self.get(name)
        return schema.generator if schema else None

    def generate(self, annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Generate HTML and keybindings for an annotation scheme.

        Args:
            annotation_scheme: Configuration dictionary with 'annotation_type' key

        Returns:
            Tuple of (html_string, keybindings_list)

        Raises:
            ValueError: If annotation_type is missing or not supported
        """
        import json as json_module

        annotation_type = annotation_scheme.get("annotation_type")
        if not annotation_type:
            raise ValueError("annotation_scheme must have 'annotation_type' field")

        schema = self.get(annotation_type)
        if not schema:
            supported = ", ".join(sorted(self._schemas.keys()))
            raise ValueError(
                f"Unsupported annotation type: '{annotation_type}'. "
                f"Supported types are: {supported}"
            )

        logger.debug(f"Generating layout for annotation type: {annotation_type}")
        html, keybindings = schema.generator(annotation_scheme)

        # Wrap HTML with display_logic attributes if present
        html = self._wrap_with_display_logic(html, annotation_scheme)

        return html, keybindings

    def _wrap_with_display_logic(self, html: str, annotation_scheme: Dict[str, Any]) -> str:
        """
        Wrap the generated HTML with display_logic attributes and container if needed.

        If the annotation scheme has display_logic, wraps the HTML in a container
        div with data-display-logic attribute containing the serialized logic,
        and applies the initial hidden state.

        Args:
            html: The generated HTML from the schema generator
            annotation_scheme: The annotation scheme configuration

        Returns:
            The HTML, possibly wrapped with display_logic container
        """
        import json as json_module
        from html import escape

        display_logic = annotation_scheme.get("display_logic")
        if not display_logic:
            return html

        schema_name = annotation_scheme.get("name", "")

        # Serialize display_logic to JSON for the data attribute
        display_logic_json = json_module.dumps(display_logic)
        # Escape for HTML attribute (single quotes in JSON are safe)
        display_logic_escaped = escape(display_logic_json)

        # Wrap in a container with display logic attributes
        # Initially hidden - the frontend JS will evaluate and show if conditions are met
        wrapped_html = f'''<div class="display-logic-container display-logic-hidden"
     data-display-logic="{display_logic_escaped}"
     data-schema-name="{escape(schema_name)}"
     data-display-logic-target="true">
{html}
</div>'''

        return wrapped_html

    def list_schemas(self) -> List[Dict[str, Any]]:
        """
        List all registered schemas with their metadata.

        Returns:
            List of dictionaries containing schema metadata
        """
        return [
            {
                "name": schema.name,
                "description": schema.description,
                "required_fields": schema.required_fields,
                "optional_fields": schema.optional_fields,
                "supports_keybindings": schema.supports_keybindings,
            }
            for schema in sorted(self._schemas.values(), key=lambda s: s.name)
        ]

    def is_registered(self, name: str) -> bool:
        """
        Check if a schema type is registered.

        Args:
            name: The schema type name

        Returns:
            True if registered, False otherwise
        """
        return name in self._schemas

    def get_supported_types(self) -> List[str]:
        """
        Get a list of all supported annotation types.

        Returns:
            Sorted list of annotation type names
        """
        return sorted(self._schemas.keys())


# Global registry instance
schema_registry = SchemaRegistry()


def _register_builtin_schemas():
    """
    Register all built-in annotation schema types.
    Called automatically when this module is imported.
    """
    from .radio import generate_radio_layout
    from .multiselect import generate_multiselect_layout
    from .multirate import generate_multirate_layout
    from .likert import generate_likert_layout
    from .textbox import generate_textbox_layout
    from .number import generate_number_layout
    from .slider import generate_slider_layout
    from .span import generate_span_layout
    from .span_link import generate_span_link_layout
    from .select import generate_select_layout
    from .pure_display import generate_pure_display_layout
    from .video import generate_video_layout
    from .image_annotation import generate_image_annotation_layout
    from .audio_annotation import generate_audio_annotation_layout
    from .video_annotation import generate_video_annotation_layout
    from .pairwise import generate_pairwise_layout
    from .coreference import generate_coreference_layout
    from .tree_annotation import generate_tree_annotation_layout
    from .triage import generate_triage_layout
    from .event_annotation import generate_event_annotation_layout

    schemas = [
        SchemaDefinition(
            name="radio",
            generator=generate_radio_layout,
            required_fields=["name", "description", "labels"],
            optional_fields=["horizontal", "label_requirement", "sequential_key_binding", "has_free_response"],
            supports_keybindings=True,
            description="Single-choice radio button selection"
        ),
        SchemaDefinition(
            name="multiselect",
            generator=generate_multiselect_layout,
            required_fields=["name", "description", "labels"],
            optional_fields=["display_config", "label_requirement", "sequential_key_binding", "video_as_label", "has_free_response"],
            supports_keybindings=True,
            description="Multiple-choice checkbox selection"
        ),
        SchemaDefinition(
            name="multirate",
            generator=generate_multirate_layout,
            required_fields=["name", "description", "options", "labels"],
            optional_fields=["label_requirement"],
            supports_keybindings=False,
            description="Rate multiple items on a scale"
        ),
        SchemaDefinition(
            name="likert",
            generator=generate_likert_layout,
            required_fields=["name", "description", "min_label", "max_label", "size"],
            optional_fields=["label_requirement"],
            supports_keybindings=True,
            description="Likert scale rating"
        ),
        SchemaDefinition(
            name="text",
            generator=generate_textbox_layout,
            required_fields=["name", "description"],
            optional_fields=["label_requirement", "placeholder", "rows"],
            supports_keybindings=False,
            description="Free-form text input"
        ),
        SchemaDefinition(
            name="number",
            generator=generate_number_layout,
            required_fields=["name", "description"],
            optional_fields=["min", "max", "step", "label_requirement"],
            supports_keybindings=False,
            description="Numeric input field"
        ),
        SchemaDefinition(
            name="slider",
            generator=generate_slider_layout,
            required_fields=["name", "description", "min", "max"],
            optional_fields=["step", "default", "label_requirement"],
            supports_keybindings=False,
            description="Slider for selecting a value in a range"
        ),
        SchemaDefinition(
            name="span",
            generator=generate_span_layout,
            required_fields=["name", "description", "labels"],
            optional_fields=["sequential_key_binding", "bad_text_label", "title", "allow_discontinuous", "entity_linking"],
            supports_keybindings=True,
            description="Text span annotation/highlighting with optional entity linking to knowledge bases"
        ),
        SchemaDefinition(
            name="select",
            generator=generate_select_layout,
            required_fields=["name", "description", "labels"],
            optional_fields=["label_requirement"],
            supports_keybindings=False,
            description="Dropdown selection"
        ),
        SchemaDefinition(
            name="pure_display",
            generator=generate_pure_display_layout,
            required_fields=["name", "description"],
            optional_fields=["labels"],
            supports_keybindings=False,
            description="Display-only content (instructions, headers)"
        ),
        SchemaDefinition(
            name="video",
            generator=generate_video_layout,
            required_fields=["name", "description", "video_path"],
            optional_fields=["autoplay", "loop", "muted", "controls", "custom_css", "fallback_text", "additional_sources"],
            supports_keybindings=False,
            description="Video player display"
        ),
        SchemaDefinition(
            name="image_annotation",
            generator=generate_image_annotation_layout,
            required_fields=["name", "description", "tools", "labels"],
            optional_fields=["zoom_enabled", "pan_enabled", "min_annotations", "max_annotations", "freeform_brush_size", "freeform_simplify"],
            supports_keybindings=True,
            description="Image annotation with bounding boxes, polygons, freeform drawing, and landmarks"
        ),
        SchemaDefinition(
            name="audio_annotation",
            generator=generate_audio_annotation_layout,
            required_fields=["name", "description"],
            optional_fields=["mode", "labels", "segment_schemes", "min_segments", "max_segments", "zoom_enabled", "playback_rate_control"],
            supports_keybindings=True,
            description="Audio segmentation and annotation with waveform visualization"
        ),
        SchemaDefinition(
            name="video_annotation",
            generator=generate_video_annotation_layout,
            required_fields=["name", "description"],
            optional_fields=["mode", "labels", "segment_schemes", "min_segments", "max_segments", "timeline_height", "overview_height", "zoom_enabled", "playback_rate_control", "frame_stepping", "show_timecode", "video_fps", "tracking_options"],
            supports_keybindings=True,
            description="Video annotation with temporal segments, frame classification, keyframes, and object tracking"
        ),
        SchemaDefinition(
            name="span_link",
            generator=generate_span_link_layout,
            required_fields=["name", "description", "link_types", "span_schema"],
            optional_fields=["visual_display"],
            supports_keybindings=False,
            description="Create relationships/links between spans (e.g., PERSON works_for ORGANIZATION)"
        ),
        SchemaDefinition(
            name="pairwise",
            generator=generate_pairwise_layout,
            required_fields=["name", "description"],
            optional_fields=["mode", "items_key", "items", "show_labels", "labels", "allow_tie", "tie_label", "sequential_key_binding", "scale", "label_requirement"],
            supports_keybindings=True,
            description="Pairwise comparison of two items (binary selection or scale rating)"
        ),
        SchemaDefinition(
            name="coreference",
            generator=generate_coreference_layout,
            required_fields=["name", "description", "span_schema"],
            optional_fields=["entity_types", "allow_singletons", "visual_display"],
            supports_keybindings=False,
            description="Coreference chain annotation for grouping mentions of the same entity"
        ),
        SchemaDefinition(
            name="tree_annotation",
            generator=generate_tree_annotation_layout,
            required_fields=["name", "description"],
            optional_fields=["node_scheme", "path_selection", "branch_comparison"],
            supports_keybindings=False,
            description="Annotation of conversation tree nodes with path selection"
        ),
        SchemaDefinition(
            name="triage",
            generator=generate_triage_layout,
            required_fields=["name", "description"],
            optional_fields=["accept_label", "reject_label", "skip_label", "auto_advance", "show_progress", "accept_key", "reject_key", "skip_key"],
            supports_keybindings=True,
            description="Binary accept/reject triage for rapid data curation"
        ),
        SchemaDefinition(
            name="event_annotation",
            generator=generate_event_annotation_layout,
            required_fields=["name", "description", "event_types", "span_schema"],
            optional_fields=["visual_display"],
            supports_keybindings=False,
            description="N-ary event annotation with triggers and typed arguments"
        ),
    ]

    for schema in schemas:
        schema_registry.register(schema)

    logger.debug(f"Registered {len(schemas)} built-in schemas")


# Auto-register built-in schemas on import
_register_builtin_schemas()
