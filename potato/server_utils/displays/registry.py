"""
Display Registry

Provides a centralized registry for managing display types.
This module serves as the single source of truth for available display
types and their renderers, separating content display from annotation collection.

Usage:
    from potato.server_utils.displays.registry import display_registry

    # Render content
    html = display_registry.render("image", field_config, data)

    # List all available display types
    types = display_registry.get_supported_types()

    # Register a custom display type (plugin support)
    display_registry.register_plugin("my_custom", MyCustomDisplay())
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional, Union
import logging

from .base import BaseDisplay, render_display_container

logger = logging.getLogger(__name__)


@dataclass
class DisplayDefinition:
    """
    Defines metadata and renderer for a display type.

    Attributes:
        name: Unique identifier for the display type (e.g., "text", "image")
        renderer: Either a BaseDisplay instance or callable that renders content
        required_fields: List of required configuration fields
        optional_fields: Dictionary of optional fields with default values
        supports_span_target: Whether this type can be a span annotation target
        description: Human-readable description of the display type
    """
    name: str
    renderer: Union[BaseDisplay, Callable[[Dict[str, Any], Any], str]]
    required_fields: List[str] = field(default_factory=list)
    optional_fields: Dict[str, Any] = field(default_factory=dict)
    supports_span_target: bool = False
    description: str = ""


class DisplayRegistry:
    """
    Centralized registry for display types.

    Provides methods to register, retrieve, and render display types.
    Supports both built-in display types and custom plugins.
    """

    def __init__(self):
        self._displays: Dict[str, DisplayDefinition] = {}
        self._plugins: Dict[str, BaseDisplay] = {}
        logger.debug("DisplayRegistry initialized")

    def register(self, display: DisplayDefinition) -> None:
        """
        Register a built-in display type.

        Args:
            display: DisplayDefinition to register

        Raises:
            ValueError: If a display with the same name is already registered
        """
        if display.name in self._displays:
            raise ValueError(f"Display type '{display.name}' is already registered")

        self._displays[display.name] = display
        logger.debug(f"Registered display type: {display.name}")

    def register_plugin(self, name: str, plugin: BaseDisplay) -> None:
        """
        Register a custom display type from a plugin.

        Args:
            name: Unique name for the display type
            plugin: BaseDisplay instance implementing the display logic

        Raises:
            ValueError: If a display with the same name is already registered
        """
        if name in self._displays or name in self._plugins:
            raise ValueError(f"Display type '{name}' is already registered")

        self._plugins[name] = plugin
        logger.debug(f"Registered plugin display type: {name}")

    def get(self, name: str) -> Optional[Union[DisplayDefinition, BaseDisplay]]:
        """
        Get a display definition or plugin by name.

        Args:
            name: The display type name

        Returns:
            DisplayDefinition or BaseDisplay if found, None otherwise
        """
        if name in self._displays:
            return self._displays[name]
        return self._plugins.get(name)

    def render(self, field_type: str, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render content using the appropriate display type.

        Args:
            field_type: The display type name (e.g., "text", "image")
            field_config: Configuration for this field from instance_display.fields
            data: The actual data value from the instance

        Returns:
            HTML string for rendering the content

        Raises:
            ValueError: If the display type is not registered
        """
        # Check plugins first (allows overriding built-ins)
        if field_type in self._plugins:
            plugin = self._plugins[field_type]
            inner_html = plugin.render(field_config, data)
            css_classes = plugin.get_css_classes(field_config)
            data_attrs = plugin.get_data_attributes(field_config, data)
            # Check if plugin handles its own label
            has_inline_label = (
                hasattr(plugin, 'has_inline_label') and
                plugin.has_inline_label(field_config)
            )
            label = None if has_inline_label else field_config.get("label")
            return render_display_container(inner_html, css_classes, data_attrs, label)

        # Check built-in displays
        if field_type in self._displays:
            display = self._displays[field_type]
            renderer = display.renderer

            # Handle BaseDisplay instances
            if isinstance(renderer, BaseDisplay):
                inner_html = renderer.render(field_config, data)
                css_classes = renderer.get_css_classes(field_config)
                data_attrs = renderer.get_data_attributes(field_config, data)
                # Check if display handles its own label (e.g., collapsible text)
                has_inline_label = (
                    hasattr(renderer, 'has_inline_label') and
                    renderer.has_inline_label(field_config)
                )
                label = None if has_inline_label else field_config.get("label")
                return render_display_container(inner_html, css_classes, data_attrs, label)

            # Handle callable renderers
            return renderer(field_config, data)

        supported = ", ".join(sorted(self.get_supported_types()))
        raise ValueError(
            f"Unknown display type: '{field_type}'. "
            f"Supported types are: {supported}"
        )

    def validate_config(self, field_type: str, field_config: Dict[str, Any]) -> List[str]:
        """
        Validate display configuration.

        Args:
            field_type: The display type name
            field_config: The field configuration to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check if display type exists
        display = self.get(field_type)
        if not display:
            errors.append(f"Unknown display type: '{field_type}'")
            return errors

        # Get required fields
        if isinstance(display, BaseDisplay):
            errors.extend(display.validate_config(field_config))
        elif isinstance(display, DisplayDefinition):
            for req_field in display.required_fields:
                if req_field not in field_config:
                    errors.append(
                        f"Missing required field '{req_field}' for display type '{field_type}'"
                    )

        return errors

    def list_displays(self) -> List[Dict[str, Any]]:
        """
        List all registered displays with their metadata.

        Returns:
            List of dictionaries containing display metadata
        """
        result = []

        # Add built-in displays
        for display in sorted(self._displays.values(), key=lambda d: d.name):
            result.append({
                "name": display.name,
                "description": display.description,
                "required_fields": display.required_fields,
                "optional_fields": list(display.optional_fields.keys()),
                "supports_span_target": display.supports_span_target,
                "is_plugin": False,
            })

        # Add plugins
        for name, plugin in sorted(self._plugins.items()):
            result.append({
                "name": name,
                "description": plugin.description,
                "required_fields": plugin.required_fields,
                "optional_fields": list(plugin.optional_fields.keys()),
                "supports_span_target": plugin.supports_span_target,
                "is_plugin": True,
            })

        return result

    def is_registered(self, name: str) -> bool:
        """
        Check if a display type is registered.

        Args:
            name: The display type name

        Returns:
            True if registered, False otherwise
        """
        return name in self._displays or name in self._plugins

    def get_supported_types(self) -> List[str]:
        """
        Get a list of all supported display types.

        Returns:
            Sorted list of display type names
        """
        types = set(self._displays.keys()) | set(self._plugins.keys())
        return sorted(types)

    def supports_span_target(self, name: str) -> bool:
        """
        Check if a display type supports span annotation targeting.

        Args:
            name: The display type name

        Returns:
            True if the type supports span targets, False otherwise
        """
        if name in self._plugins:
            return self._plugins[name].supports_span_target
        if name in self._displays:
            return self._displays[name].supports_span_target
        return False


# Global registry instance
display_registry = DisplayRegistry()


def _register_builtin_displays():
    """
    Register all built-in display types.
    Called automatically when this module is imported.
    """
    from .text_display import TextDisplay
    from .image_display import ImageDisplay
    from .video_display import VideoDisplay
    from .audio_display import AudioDisplay
    from .dialogue_display import DialogueDisplay
    from .pairwise_display import PairwiseDisplay
    from .pdf_display import PDFDisplay
    from .document_display import DocumentDisplay
    from .spreadsheet_display import SpreadsheetDisplay
    from .code_display import CodeDisplay
    from .conversation_tree_display import ConversationTreeDisplay

    displays = [
        DisplayDefinition(
            name="text",
            renderer=TextDisplay(),
            required_fields=["key"],
            optional_fields={
                "collapsible": False,
                "max_height": None,
                "preserve_whitespace": True,
            },
            supports_span_target=True,
            description="Plain text content display"
        ),
        DisplayDefinition(
            name="html",
            renderer=TextDisplay(allow_html=True),
            required_fields=["key"],
            optional_fields={
                "collapsible": False,
                "max_height": None,
            },
            supports_span_target=False,
            description="HTML content display (sanitized)"
        ),
        DisplayDefinition(
            name="image",
            renderer=ImageDisplay(),
            required_fields=["key"],
            optional_fields={
                "max_width": None,
                "max_height": None,
                "zoomable": True,
                "alt_text": "",
            },
            supports_span_target=False,
            description="Image display with optional zoom"
        ),
        DisplayDefinition(
            name="video",
            renderer=VideoDisplay(),
            required_fields=["key"],
            optional_fields={
                "max_width": None,
                "max_height": None,
                "controls": True,
                "autoplay": False,
                "loop": False,
                "muted": False,
            },
            supports_span_target=False,
            description="Video player display"
        ),
        DisplayDefinition(
            name="audio",
            renderer=AudioDisplay(),
            required_fields=["key"],
            optional_fields={
                "controls": True,
                "autoplay": False,
                "loop": False,
                "show_waveform": False,
            },
            supports_span_target=False,
            description="Audio player display"
        ),
        DisplayDefinition(
            name="dialogue",
            renderer=DialogueDisplay(),
            required_fields=["key"],
            optional_fields={
                "alternating_shading": True,
                "speaker_extraction": True,
                "show_turn_numbers": False,
            },
            supports_span_target=True,
            description="Dialogue/conversation turns display"
        ),
        DisplayDefinition(
            name="pairwise",
            renderer=PairwiseDisplay(),
            required_fields=["key"],
            optional_fields={
                "cell_width": "50%",
                "show_labels": True,
                "vertical_on_mobile": True,
            },
            supports_span_target=False,
            description="Side-by-side comparison display"
        ),
        DisplayDefinition(
            name="pdf",
            renderer=PDFDisplay(),
            required_fields=["key"],
            optional_fields={
                "view_mode": "scroll",
                "max_height": 700,
                "max_width": None,
                "text_layer": True,
                "show_page_controls": True,
                "initial_page": 1,
                "zoom": "auto",
            },
            supports_span_target=True,
            description="PDF document display with PDF.js rendering"
        ),
        DisplayDefinition(
            name="document",
            renderer=DocumentDisplay(),
            required_fields=["key"],
            optional_fields={
                "collapsible": False,
                "max_height": None,
                "show_outline": False,
                "preserve_structure": True,
                "style_theme": "default",
            },
            supports_span_target=True,
            description="Document display for DOCX, Markdown, and other formats"
        ),
        DisplayDefinition(
            name="spreadsheet",
            renderer=SpreadsheetDisplay(),
            required_fields=["key"],
            optional_fields={
                "annotation_mode": "row",
                "show_headers": True,
                "max_height": 400,
                "max_width": None,
                "striped": True,
                "hoverable": True,
                "sortable": False,
                "selectable": True,
                "compact": False,
            },
            supports_span_target=True,
            description="Spreadsheet/table display with row or cell annotation"
        ),
        DisplayDefinition(
            name="code",
            renderer=CodeDisplay(),
            required_fields=["key"],
            optional_fields={
                "language": None,
                "show_line_numbers": True,
                "max_height": 500,
                "max_width": None,
                "wrap_lines": False,
                "highlight_lines": None,
                "start_line": 1,
                "theme": "default",
                "copy_button": True,
            },
            supports_span_target=True,
            description="Source code display with syntax highlighting"
        ),
        DisplayDefinition(
            name="conversation_tree",
            renderer=ConversationTreeDisplay(),
            required_fields=["key"],
            optional_fields={
                "collapsed_depth": 2,
                "node_style": "card",
                "show_node_ids": False,
                "max_depth": None,
            },
            supports_span_target=False,
            description="Conversation tree with collapsible branching nodes"
        ),
    ]

    for display in displays:
        display_registry.register(display)

    logger.debug(f"Registered {len(displays)} built-in display types")


# Auto-register built-in displays on import
_register_builtin_displays()
