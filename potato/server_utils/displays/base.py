"""
Base Display Class

Provides a base class for custom display types that can be registered
as plugins. Third-party developers can extend this class to create
custom content renderers.

Usage:
    from potato.server_utils.displays.base import BaseDisplay

    class MyCustomDisplay(BaseDisplay):
        name = "my_custom"
        required_fields = ["key"]
        optional_fields = {"my_option": "default_value"}

        def render(self, field_config, data):
            return f'<div class="my-custom">{data}</div>'

Span Target Contract:
    If a display declares ``supports_span_target = True``, its ``render()``
    output MUST contain a ``.text-content`` wrapper when the field has
    ``span_target: true``.  Use the ``render_span_wrapper()`` helper:

        if field_config.get("span_target"):
            inner_html = self.render_span_wrapper(field_key, inner_html, plain_text)

    SpanManager (span-core.js) discovers span-target fields via:
        document.querySelectorAll('.display-field[data-span-target="true"]')
    then looks inside each for:
        field.querySelector('.text-content')
    If ``.text-content`` is missing, span annotation silently fails.

    See displays/ARCHITECTURE.md for the full contract.
"""

import html as html_module
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseDisplay(ABC):
    """
    Abstract base class for display type implementations.

    Subclasses must implement the `render` method and define
    class attributes for registration.

    Class Attributes:
        name: Unique identifier for this display type (e.g., "text", "image")
        required_fields: List of required configuration field names
        optional_fields: Dictionary of optional fields with their default values
        description: Human-readable description of this display type
        supports_span_target: Whether this type can be a span annotation target.
            If True, render() MUST produce a .text-content wrapper when
            field_config["span_target"] is True.  Use render_span_wrapper().
    """

    name: str = ""
    required_fields: List[str] = []
    optional_fields: Dict[str, Any] = {}
    description: str = ""
    supports_span_target: bool = False

    @abstractmethod
    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render the content as HTML.

        Args:
            field_config: The field configuration from instance_display.fields
            data: The actual data value from the instance

        Returns:
            HTML string for rendering the content
        """
        pass

    def render_span_wrapper(self, field_key: str, inner_html: str, plain_text: str) -> str:
        """
        Wrap content in the standard .text-content div required by SpanManager.

        Call this from render() when field_config.get("span_target") is True.
        This ensures the HTML output satisfies the span annotation contract:
        - ``class="text-content"``
        - ``id="text-content-{field_key}"``
        - ``data-original-text="{escaped plain text}"``
        - ``padding-top: 24px`` (via style) for span label positioning

        Args:
            field_key: The field key (e.g., "conversation", "premise")
            inner_html: The HTML content to wrap
            plain_text: The plain text for offset-based span positioning.
                Must match the text extraction format in routes.py for this
                data type, or span offsets will misalign on reload.

        Returns:
            HTML string with the .text-content wrapper
        """
        escaped_text = html_module.escape(plain_text, quote=True)
        return (
            f'<div class="text-content" id="text-content-{html_module.escape(field_key, quote=True)}"'
            f' data-original-text="{escaped_text}"'
            f' style="position: relative; padding-top: 24px;">'
            f'{inner_html}'
            f'</div>'
        )

    def has_inline_label(self, field_config: Dict[str, Any]) -> bool:
        """
        Check if this display handles its own label rendering.

        If True, the registry will NOT add a label wrapper around the
        display container (avoiding duplicate labels).

        Override in subclasses where the display renders its own label
        (e.g., collapsible text with label in <summary>).

        Args:
            field_config: The field configuration

        Returns:
            True if the display renders its own label
        """
        return False

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """
        Get CSS classes to apply to the display container.

        Override in subclasses to add custom classes.

        Args:
            field_config: The field configuration

        Returns:
            List of CSS class names
        """
        return [f"display-field", f"display-type-{self.name}"]

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """
        Get data attributes to add to the display container.

        These are used for JavaScript interactions and linking
        annotation schemas to display fields.

        Args:
            field_config: The field configuration
            data: The actual data value

        Returns:
            Dictionary of data attribute names (without 'data-' prefix) to values
        """
        attrs = {
            "field-key": field_config.get("key", ""),
            "field-type": self.name,
        }
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs

    def get_js_init(self) -> Optional[str]:
        """
        Get JavaScript initialization code for this display type.

        Override in subclasses that need client-side initialization.

        Returns:
            JavaScript code string or None if not needed
        """
        return None

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        """
        Validate the field configuration.

        Args:
            field_config: The field configuration to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check required fields
        for field in self.required_fields:
            if field not in field_config:
                errors.append(f"Missing required field '{field}' for display type '{self.name}'")

        # Warn if span_target is set but display doesn't support it
        if field_config.get("span_target") and not self.supports_span_target:
            errors.append(
                f"Display type '{self.name}' does not support span_target. "
                f"Span annotation will not work on this field."
            )

        return errors

    def get_display_options(self, field_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get display options with defaults applied.

        Args:
            field_config: The field configuration

        Returns:
            Dictionary of display options with defaults filled in
        """
        options = field_config.get("display_options", {})
        result = dict(self.optional_fields)  # Start with defaults
        result.update(options)  # Override with user-specified options
        return result


def concatenate_dialogue_text(data: Any, speaker_key: str = "speaker", text_key: str = "text") -> str:
    """
    Concatenate dialogue data into a single plain text string.

    Format: "Speaker: text\\nSpeaker: text\\n..."
    Turns without a speaker omit the "Speaker: " prefix.

    Note: For span offset matching with dialogue displays, use
    ``reconstruct_dialogue_dom_text()`` instead — it accounts for
    turn numbers and DOM whitespace normalization.

    Args:
        data: Dialogue data — list of dicts, list of strings, or a string
        speaker_key: Key for speaker in dict format (default "speaker")
        text_key: Key for text in dict format (default "text")

    Returns:
        Concatenated plain text string
    """
    if isinstance(data, str):
        return data

    if not isinstance(data, list):
        return str(data)

    parts = []
    for item in data:
        if isinstance(item, dict):
            speaker = item.get(speaker_key, '')
            text = item.get(text_key, '')
            parts.append(f"{speaker}: {text}" if speaker else text)
        else:
            parts.append(str(item))
    return "\n".join(parts)


def reconstruct_dialogue_dom_text(
    data: Any,
    speaker_key: str = "speaker",
    text_key: str = "text",
    show_turn_numbers: bool = False,
) -> str:
    """
    Reconstruct the whitespace-normalized DOM textContent of a dialogue display.

    When DialogueDisplay renders HTML, the browser's ``textContent`` includes
    turn numbers, speaker prefixes, and the text of each turn — all separated
    by whitespace that ``normalizeText()`` collapses to single spaces.

    This function reproduces that collapsed form so that span offsets produced
    by the client (DOM-based) can be used server-side to extract the correct
    substring.

    Args:
        data: Dialogue data — list of dicts, list of strings, or a string
        speaker_key: Key for speaker in dict format
        text_key: Key for text in dict format
        show_turn_numbers: Whether turn numbers like ``[1]`` are shown

    Returns:
        Single-line text matching the browser's normalized textContent
    """
    if isinstance(data, str):
        return data.strip()

    if not isinstance(data, list):
        return str(data).strip()

    parts = []
    for i, item in enumerate(data):
        turn_parts = []
        if show_turn_numbers:
            turn_parts.append(f"[{i + 1}]")

        if isinstance(item, dict):
            speaker = item.get(speaker_key, "")
            text = item.get(text_key, "")
            if speaker:
                turn_parts.append(f"{speaker}:")
            turn_parts.append(str(text))
        else:
            turn_parts.append(str(item))

        parts.append(" ".join(turn_parts))

    # Join turns with single space (browser normalizes inter-turn whitespace)
    import re as _re
    joined = " ".join(parts)
    # Final normalization: collapse any remaining multi-space to single space
    return _re.sub(r"\s+", " ", joined).strip()


def render_display_container(
    inner_html: str,
    css_classes: List[str],
    data_attrs: Dict[str, str],
    label: Optional[str] = None
) -> str:
    """
    Render a display container with the given content.

    This helper function wraps content in a standard display container
    with proper classes and data attributes.

    Args:
        inner_html: The inner HTML content
        css_classes: CSS classes to apply
        data_attrs: Data attributes to add
        label: Optional label/header for the display

    Returns:
        Complete HTML for the display container
    """
    class_str = " ".join(css_classes)
    attr_str = " ".join(f'data-{k}="{v}"' for k, v in data_attrs.items())

    parts = []
    parts.append(f'<div class="{class_str}" {attr_str}>')

    if label:
        parts.append(f'  <div class="display-field-label">{label}</div>')

    parts.append(f'  <div class="display-field-content">')
    parts.append(f'    {inner_html}')
    parts.append(f'  </div>')
    parts.append(f'</div>')

    return "\n".join(parts)
