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
        lazy_populated: When True, the display's data key is populated
            after initial render (e.g. ``interactive_chat``'s conversation
            is written only after the user finishes chatting). The
            ``instance_display`` validator uses this to decide whether a
            missing data key is a transient state (lazy) or a config
            error (not lazy).
    """
    name: str
    renderer: Union[BaseDisplay, Callable[[Dict[str, Any], Any], str]]
    required_fields: List[str] = field(default_factory=list)
    optional_fields: Dict[str, Any] = field(default_factory=dict)
    supports_span_target: bool = False
    description: str = ""
    lazy_populated: bool = False

    def __post_init__(self):
        """Take ``optional_fields`` from the renderer, which is what runs.

        ``BaseDisplay.get_display_options()`` merges the *renderer's*
        ``optional_fields``; this dataclass's copy only feeds ``list_displays()``,
        the generated JSON schema and the docs. So a key the renderer reads and
        this definition omits is an option that works but that no author, editor
        or agent can discover -- and a default declared in both that disagrees is
        documentation that contradicts the product.

        Both had happened. 14 of 24 displays hid 44 working options between them
        (``pdf`` alone hid 15, including ``ocr`` and ``link_schema``), and
        ``agent_trace.step_type_colors`` and ``eval_trace.pane_labels`` were
        published as ``None`` while the renderer supplied real defaults.

        Reading the renderer removes the copy rather than asking anyone to keep
        it in step. Keys declared only here still survive, for the entries whose
        renderer is a bare callable with no such attribute.
        """
        renderer_fields = getattr(self.renderer, "optional_fields", None)
        if isinstance(renderer_fields, dict):
            merged = dict(renderer_fields)
            for key, value in (self.optional_fields or {}).items():
                merged.setdefault(key, value)
            self.optional_fields = merged


#: Display types that accept ``span_target: true`` without satisfying the
#: standard ``.text-content`` contract, because they anchor spans themselves.
#: Each declares ``supports_span_target = False`` on its renderer -- correctly,
#: since that flag is about the standard contract -- and then emits its own
#: ``span-target-<type>`` class and handles the offsets.
#:
#:   pdf         - anchors into the PDF.js text layer
#:   spreadsheet - anchors per cell rather than by character offset
#:   agent_trace - anchors per step, using the step id
CUSTOM_SPAN_TARGET_TYPES = frozenset({"pdf", "spreadsheet", "agent_trace"})


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
            label = None if plugin.has_inline_label(field_config) else field_config.get("label")
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
                label = None if renderer.has_inline_label(field_config) else field_config.get("label")
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

    def type_supports_span_target(self, field_type: str) -> bool:
        """
        Check if a display type supports span annotation.

        Args:
            field_type: The display type name

        Returns:
            True if the display type supports span_target
        """
        if field_type in self._plugins:
            return self._plugins[field_type].supports_span_target
        if field_type in self._displays:
            display = self._displays[field_type]
            if isinstance(display.renderer, BaseDisplay):
                return display.renderer.supports_span_target
            return display.supports_span_target
        return False

    def get_span_target_types(self) -> List[str]:
        """
        Display types that support the standard span contract.

        "Standard" means the renderer wraps its content in the
        ``.text-content`` element that span offsets are measured against.
        This is narrower than the set of types that accept a ``span_target``
        field -- see :meth:`get_span_target_capable_types`.

        Returns:
            List of type names where supports_span_target is True
        """
        types = []
        for name in self.get_supported_types():
            if self.type_supports_span_target(name):
                types.append(name)
        return sorted(types)

    def get_span_target_capable_types(self) -> List[str]:
        """
        Every display type that accepts ``span_target: true``.

        The standard-contract types, plus the ones in
        :data:`CUSTOM_SPAN_TARGET_TYPES` that implement their own anchoring.
        Config validation must use this rather than
        :meth:`get_span_target_types`, and rather than a list of its own --
        a second hardcoded list is how ``eval_trace`` and ``coding_trace``
        came to be rejected by the validator while declaring support in the
        registry.
        """
        return sorted(set(self.get_span_target_types()) | CUSTOM_SPAN_TARGET_TYPES)

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

    def is_lazy_populated(self, name: str) -> bool:
        """
        Check whether a display type populates its data lazily (after
        initial render). Used by ``instance_display._validate_fields`` to
        distinguish an expected transient missing key (lazy) from a real
        configuration error (not lazy).

        Args:
            name: The display type name.

        Returns:
            True iff the display's ``lazy_populated`` attribute is set. False
            for unknown types (treat as strict for safety).
        """
        plugin = self._plugins.get(name)
        if plugin is not None:
            return bool(getattr(plugin, "lazy_populated", False))
        display = self._displays.get(name)
        if display is not None:
            # Prefer the DisplayDefinition flag; fall back to the BaseDisplay
            # class attr when a definition didn't explicitly set it.
            if getattr(display, "lazy_populated", False):
                return True
            renderer = getattr(display, "renderer", None)
            return bool(getattr(renderer, "lazy_populated", False))
        return False

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
    from .depth_display import DepthDisplay
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
    from .multi_agent_discussion_display import MultiAgentDiscussionDisplay
    from .agent_trace_display import AgentTraceDisplay
    from .eval_trace_display import EvalTraceDisplay
    from .gallery_display import GalleryDisplay
    from .interactive_chat_display import InteractiveChatDisplay
    from .web_agent_trace_display import WebAgentTraceDisplay
    from .live_agent_display import LiveAgentDisplay
    from .coding_trace_display import CodingTraceDisplay
    from .live_coding_agent_display import LiveCodingAgentDisplay
    from .cot_trace_display import CotTraceDisplay
    from .audio_dialogue_display import AudioDialogueDisplay

    displays = [
        DisplayDefinition(
            name="text",
            renderer=TextDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Plain text content display"
        ),
        DisplayDefinition(
            name="html",
            renderer=TextDisplay(allow_html=True),
            required_fields=["key"],
            supports_span_target=False,
            description="HTML content display (sanitized)"
        ),
        DisplayDefinition(
            name="image",
            renderer=ImageDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Image display with optional zoom"
        ),
        DisplayDefinition(
            name="depth_map",
            renderer=DepthDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Depth map with windowing, colormap and a metre readout"
        ),
        DisplayDefinition(
            name="video",
            renderer=VideoDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Video player display"
        ),
        DisplayDefinition(
            name="audio",
            renderer=AudioDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Audio player display"
        ),
        DisplayDefinition(
            name="dialogue",
            renderer=DialogueDisplay(),
            required_fields=["key"],
            # Must stay in step with DialogueDisplay.optional_fields — that class
            # attribute is what get_display_options() actually merges, while this
            # copy feeds the docs and the generated config schema.
            supports_span_target=True,
            description=(
                "Dialogue/conversation turns, optionally threaded by reply-to "
                "with timestamps and per-turn metadata"
            )
        ),
        DisplayDefinition(
            name="audio_dialogue",
            renderer=AudioDialogueDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Podcast / interview dialogue: speaker bubbles, per-turn audio playback, ratings, spans, cross-turn linking",
        ),
        DisplayDefinition(
            name="multi_agent_discussion",
            renderer=MultiAgentDiscussionDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Multi-agent discussion with agent legend, colors, addressees, and filtering"
        ),
        DisplayDefinition(
            name="pairwise",
            renderer=PairwiseDisplay(),
            required_fields=["key"],
            # Must stay in step with PairwiseDisplay.optional_fields -- that
            # class attribute is what get_display_options() merges, while this
            # copy feeds the docs and the generated config schema. This one had
            # drifted twice: the default was still "50%" after the renderer
            # moved to "auto", and `labels` was documented but never declared.
            supports_span_target=False,
            description="Side-by-side comparison display"
        ),
        DisplayDefinition(
            name="pdf",
            renderer=PDFDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="PDF document display with PDF.js rendering"
        ),
        DisplayDefinition(
            name="document",
            renderer=DocumentDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Document display for DOCX, Markdown, and other formats"
        ),
        DisplayDefinition(
            name="spreadsheet",
            renderer=SpreadsheetDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Spreadsheet/table display with row or cell annotation"
        ),
        DisplayDefinition(
            name="code",
            renderer=CodeDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Source code display with syntax highlighting"
        ),
        DisplayDefinition(
            name="conversation_tree",
            renderer=ConversationTreeDisplay(),
            required_fields=["key"],
            # Not a span target: collapsed subtrees make the container's
            # textContent depend on UI state, so span offsets would shift when a
            # branch is expanded. Pair it with a `dialogue` field for spans.
            supports_span_target=False,
            description="Conversation tree with collapsible branching nodes"
        ),
        DisplayDefinition(
            name="agent_trace",
            renderer=AgentTraceDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Agent trace display with step cards and type badges"
        ),
        DisplayDefinition(
            name="cot_trace",
            renderer=CotTraceDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Long chain-of-thought trace: vertical step cards with a sticky progress rail for process-reward verification",
        ),
        DisplayDefinition(
            name="eval_trace",
            renderer=EvalTraceDisplay(),
            required_fields=["key"],
            # Matches EvalTraceDisplay.supports_span_target: the three-pane block
            # is span-annotatable (offset-based highlight across panes).
            supports_span_target=True,
            description="Three-pane agent trace eval: reasoning, function calls, and final answer side-by-side"
        ),
        DisplayDefinition(
            name="gallery",
            renderer=GalleryDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Scrollable image gallery with captions"
        ),
        DisplayDefinition(
            name="interactive_chat",
            renderer=InteractiveChatDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            lazy_populated=True,  # conversation is written by /agent_chat/finish
            description="Interactive agent chat with post-interaction trace display"
        ),
        DisplayDefinition(
            name="web_agent_trace",
            renderer=WebAgentTraceDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            description="Web agent trace viewer with screenshots, SVG overlays, and step navigation"
        ),
        DisplayDefinition(
            name="coding_trace",
            renderer=CodingTraceDisplay(),
            required_fields=["key"],
            supports_span_target=True,
            description="Coding agent trace display with diff rendering, terminal blocks, and file tree"
        ),
        DisplayDefinition(
            name="live_agent",
            renderer=LiveAgentDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            lazy_populated=True,  # trace populated by live agent session
            description="Live AI agent viewer with real-time screenshots, controls, and interaction"
        ),
        DisplayDefinition(
            name="live_coding_agent",
            renderer=LiveCodingAgentDisplay(),
            required_fields=["key"],
            supports_span_target=False,
            lazy_populated=True,  # trace populated by live coding-agent session
            description="Live coding agent viewer with real-time streaming and intervention controls"
        ),
    ]

    for display in displays:
        display_registry.register(display)

    logger.debug(f"Registered {len(displays)} built-in display types")


# Auto-register built-in displays on import
_register_builtin_displays()
