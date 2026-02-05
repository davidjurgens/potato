"""
Text Display Type

Renders plain text or HTML content for display in the annotation interface.
Supports span annotation targeting when used with span annotation schemes.
"""

import html
from typing import Dict, Any, List

from .base import BaseDisplay


class TextDisplay(BaseDisplay):
    """
    Display type for text content.

    Supports both plain text (with HTML escaping) and sanitized HTML content.
    Can be used as a target for span annotations.
    """

    name = "text"
    required_fields = ["key"]
    optional_fields = {
        "collapsible": False,
        "max_height": None,
        "preserve_whitespace": True,
    }
    description = "Plain text content display"
    supports_span_target = True

    def __init__(self, allow_html: bool = False):
        """
        Initialize the text display.

        Args:
            allow_html: If True, render as sanitized HTML. If False, escape all HTML.
        """
        self.allow_html = allow_html
        if allow_html:
            self.name = "html"
            self.description = "HTML content display (sanitized)"
            self.supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render text content as HTML.

        Args:
            field_config: The field configuration
            data: The text content to display

        Returns:
            HTML string for the text content
        """
        if data is None:
            return '<span class="text-placeholder">No content</span>'

        # Convert to string if needed
        text = str(data)

        # Get display options
        options = self.get_display_options(field_config)
        preserve_whitespace = options.get("preserve_whitespace", True)
        collapsible = options.get("collapsible", False)
        max_height = options.get("max_height")

        # Process the text
        if self.allow_html:
            # Sanitize HTML but allow safe tags
            from potato.server_utils.html_sanitizer import sanitize_html
            content = str(sanitize_html(text))
        else:
            # Escape all HTML for plain text
            content = html.escape(text)
            # Convert newlines to <br> for display
            if preserve_whitespace:
                content = content.replace('\n', '<br>')

        # Build the content wrapper
        wrapper_classes = ["text-display-content"]
        wrapper_style = []

        if preserve_whitespace and not self.allow_html:
            wrapper_classes.append("preserve-whitespace")

        if max_height:
            wrapper_style.append(f"max-height: {max_height}px")
            wrapper_style.append("overflow-y: auto")

        # Check if this is a span target - add special wrapper for span annotations
        is_span_target = field_config.get("span_target", False)
        if is_span_target:
            wrapper_classes.append("span-target-text")
            # Add data attribute for original text (used by span manager)
            field_key = field_config.get("key", "")
            content = f'<div class="text-content" id="text-content-{field_key}" data-original-text="{html.escape(text)}">{content}</div>'

        style_attr = f' style="{"; ".join(wrapper_style)}"' if wrapper_style else ""
        class_attr = f'class="{" ".join(wrapper_classes)}"'

        if collapsible:
            return self._render_collapsible(content, class_attr, style_attr, field_config)

        return f'<div {class_attr}{style_attr}>{content}</div>'

    def _render_collapsible(
        self,
        content: str,
        class_attr: str,
        style_attr: str,
        field_config: Dict[str, Any]
    ) -> str:
        """
        Render content in a collapsible container.

        Args:
            content: The HTML content
            class_attr: CSS class attribute string
            style_attr: CSS style attribute string
            field_config: The field configuration

        Returns:
            HTML for collapsible content
        """
        field_key = field_config.get("key", "text")
        collapse_id = f"collapse-{field_key}"
        label = field_config.get("label", "")

        # Build header row with label and button inline
        label_html = f'<span class="collapsible-label">{label}</span>' if label else ''

        return f'''
        <div class="collapsible-text-container" data-has-inline-label="true">
            <div class="collapsible-header">
                {label_html}
                <button class="btn btn-sm btn-outline-secondary collapsible-toggle"
                        type="button"
                        data-bs-toggle="collapse"
                        data-bs-target="#{collapse_id}"
                        aria-expanded="true"
                        aria-controls="{collapse_id}">
                    <span class="collapse-text-show">Show</span>
                    <span class="collapse-text-hide">Hide</span>
                </button>
            </div>
            <div class="collapse show" id="{collapse_id}">
                <div {class_attr}{style_attr}>
                    {content}
                </div>
            </div>
        </div>
        '''

    def has_inline_label(self, field_config: Dict[str, Any]) -> bool:
        """
        Check if this display handles its own label rendering.

        Returns True for collapsible text so the registry doesn't add
        a duplicate label.

        Args:
            field_config: The field configuration

        Returns:
            True if label is rendered inline by this display
        """
        options = self.get_display_options(field_config)
        return options.get("collapsible", False)

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        if field_config.get("span_target"):
            classes.append("span-target-field")
        if self.allow_html:
            classes.append("html-content")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """Get data attributes for the container."""
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs
