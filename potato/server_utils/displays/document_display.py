"""
Document Display Component

Renders document content (DOCX, Markdown) with support for span annotation.
Handles pre-extracted content from format handlers.

Usage:
    In instance_display config:
    fields:
      - key: document
        type: document
        display_options:
          collapsible: false
          max_height: 500
"""

from typing import Dict, Any, List, Optional
import html
import logging

from .base import BaseDisplay

logger = logging.getLogger(__name__)


class DocumentDisplay(BaseDisplay):
    """
    Display type for rendered documents (DOCX, Markdown, HTML).

    Displays HTML content extracted from documents with support for
    span annotation on the text content, or bounding box annotation
    for image-like region selection.
    """

    name = "document"
    required_fields = ["key"]
    optional_fields = {
        "collapsible": False,        # Allow collapsing sections
        "max_height": None,          # Max container height in pixels
        "show_outline": False,       # Show document outline/TOC
        "preserve_structure": True,  # Keep paragraph/heading structure
        "style_theme": "default",    # CSS theme: default, minimal, print
        "annotation_mode": "span",   # "span" or "bounding_box"
        "bbox_min_size": 10,         # Minimum bounding box size in pixels
        "show_bbox_labels": True,    # Show labels on bounding boxes
    }
    description = "Document display for DOCX, Markdown, and other formats"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render document content.

        Args:
            field_config: Display configuration
            data: Either a dict with extracted content or raw HTML string

        Returns:
            HTML string for rendering
        """
        options = self.get_display_options(field_config)
        annotation_mode = options.get("annotation_mode", "span")

        # Use bounding box rendering if requested
        if annotation_mode == "bounding_box":
            return self._render_bbox_mode(field_config, data, options)

        return self._render_span_mode(field_config, data, options)

    def _render_span_mode(
        self,
        field_config: Dict[str, Any],
        data: Any,
        options: Dict[str, Any]
    ) -> str:
        """Render document in span annotation mode (default)."""
        field_key = field_config.get("key", "document")

        # Handle different data formats
        if isinstance(data, dict):
            # Pre-extracted FormatOutput data
            rendered_html = data.get("rendered_html", "")
            metadata = data.get("metadata", {})
            raw_text = data.get("text", "")
        elif isinstance(data, str):
            # Raw HTML or text content
            rendered_html = data
            metadata = {}
            raw_text = ""
        else:
            rendered_html = f"<p>Unsupported content type: {type(data)}</p>"
            metadata = {}
            raw_text = ""

        # Build container
        parts = []

        # Container styles
        styles = []
        max_height = options.get("max_height")
        if max_height:
            styles.append(f"max-height: {max_height}px")
            styles.append("overflow-y: auto")
        style_str = "; ".join(styles) if styles else ""

        theme = options.get("style_theme", "default")

        # Main container
        parts.append(
            f'<div class="document-display document-theme-{theme}" '
            f'data-field-key="{field_key}" '
            f'style="{style_str}">'
        )

        # Document outline/TOC if available and enabled
        if options.get("show_outline") and metadata.get("headings"):
            parts.append(self._render_outline(metadata["headings"]))

        # Determine content classes - add text-content for span annotation compatibility
        is_span_target = field_config.get("span_target", False)
        content_classes = ["document-content"]
        if is_span_target:
            content_classes.append("text-content")
        content_class_str = " ".join(content_classes)

        # Extract plain text for span annotation (strip HTML tags)
        import re
        plain_text = re.sub(r'<[^>]+>', '', rendered_html)
        plain_text = ' '.join(plain_text.split())  # Normalize whitespace
        data_original_attr = f'data-original-text="{html.escape(plain_text)}"' if is_span_target else ""

        # Collapsible wrapper if enabled
        if options.get("collapsible"):
            label = field_config.get("label", "Document")
            parts.append(f'''
                <details class="document-collapsible" open>
                    <summary class="document-summary">{html.escape(label)}</summary>
                    <div class="{content_class_str}" id="text-content-{field_key}" {data_original_attr}>
                        {rendered_html}
                    </div>
                </details>
            ''')
        else:
            parts.append(f'<div class="{content_class_str}" id="text-content-{field_key}" {data_original_attr}>{rendered_html}</div>')

        # Hidden text container for span annotation (if different from rendered)
        if raw_text and field_config.get("span_target"):
            parts.append(
                f'<div class="document-raw-text" style="display:none;">'
                f'{html.escape(raw_text)}'
                f'</div>'
            )

        # Metadata footer
        if metadata:
            parts.append(self._render_metadata(metadata))

        parts.append('</div>')

        return "\n".join(parts)

    def _render_bbox_mode(
        self,
        field_config: Dict[str, Any],
        data: Any,
        options: Dict[str, Any]
    ) -> str:
        """Render document in bounding box annotation mode."""
        field_key = field_config.get("key", "document")
        bbox_min_size = options.get("bbox_min_size", 10)
        show_labels = options.get("show_bbox_labels", True)
        max_height = options.get("max_height")
        theme = options.get("style_theme", "default")

        # Handle different data formats
        if isinstance(data, dict):
            rendered_html = data.get("rendered_html", "")
            metadata = data.get("metadata", {})
        elif isinstance(data, str):
            rendered_html = data
            metadata = {}
        else:
            rendered_html = f"<p>Unsupported content type: {type(data)}</p>"
            metadata = {}

        # Build container
        parts = []

        # Container styles
        styles = ["position: relative"]
        if max_height:
            styles.append(f"max-height: {max_height}px")
            styles.append("overflow-y: auto")
        style_str = "; ".join(styles)

        # Main container with bbox mode
        parts.append(
            f'<div class="document-display document-theme-{theme} document-bbox-mode" '
            f'data-field-key="{field_key}" '
            f'data-annotation-mode="bounding_box" '
            f'data-bbox-min-size="{bbox_min_size}" '
            f'data-show-bbox-labels="{str(show_labels).lower()}" '
            f'style="{style_str}">'
        )

        # Bounding box toolbar
        parts.append('''
            <div class="document-bbox-toolbar">
                <div class="document-bbox-tools">
                    <button type="button" class="document-bbox-draw-btn active" title="Draw bounding box">
                        &#x25A1; Draw
                    </button>
                    <button type="button" class="document-bbox-select-btn" title="Select bounding box">
                        &#x2191; Select
                    </button>
                    <button type="button" class="document-bbox-delete-btn" title="Delete selected">
                        &#x2715; Delete
                    </button>
                </div>
                <div class="document-bbox-info">
                    <span class="document-bbox-count">Boxes: <span class="count">0</span></span>
                </div>
            </div>
        ''')

        # Content container with bbox canvas overlay
        parts.append('<div class="document-bbox-container">')

        # The actual document content
        parts.append(f'<div class="document-content document-bbox-content">{rendered_html}</div>')

        # Canvas overlay for drawing bounding boxes
        parts.append('<canvas class="document-bbox-canvas"></canvas>')

        parts.append('</div>')  # Close bbox-container

        # Metadata footer
        if metadata:
            parts.append(self._render_metadata(metadata))

        parts.append('</div>')  # Close main container

        return "\n".join(parts)

    def _render_outline(self, headings: List[Dict[str, Any]]) -> str:
        """
        Render document outline/table of contents.
        """
        if not headings:
            return ""

        parts = ['<nav class="document-outline">']
        parts.append('<div class="outline-title">Contents</div>')
        parts.append('<ul class="outline-list">')

        for heading in headings:
            level = heading.get("level", 1)
            title = heading.get("title", "")
            offset = heading.get("offset", 0)

            indent_class = f"outline-level-{level}"
            parts.append(
                f'<li class="{indent_class}">'
                f'<a href="#" data-offset="{offset}" class="outline-link">'
                f'{html.escape(title)}'
                f'</a></li>'
            )

        parts.append('</ul>')
        parts.append('</nav>')

        return "\n".join(parts)

    def _render_metadata(self, metadata: Dict[str, Any]) -> str:
        """
        Render metadata footer.
        """
        info_items = []

        if "format" in metadata:
            info_items.append(f"Format: {metadata['format'].upper()}")

        if "paragraph_count" in metadata or "paragraphs" in metadata:
            count = len(metadata.get("paragraphs", [])) or metadata.get("paragraph_count", 0)
            if count:
                info_items.append(f"Paragraphs: {count}")

        if "line_count" in metadata:
            info_items.append(f"Lines: {metadata['line_count']}")

        if "char_count" in metadata:
            info_items.append(f"Characters: {metadata['char_count']:,}")

        if not info_items:
            return ""

        info_str = " | ".join(info_items)
        return f'<div class="document-metadata">{info_str}</div>'

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the display container."""
        classes = super().get_css_classes(field_config)
        options = self.get_display_options(field_config)

        if field_config.get("span_target"):
            classes.append("span-target-document")

        if options.get("collapsible"):
            classes.append("document-collapsible-enabled")

        theme = options.get("style_theme", "default")
        classes.append(f"document-theme-{theme}")

        annotation_mode = options.get("annotation_mode", "span")
        if annotation_mode == "bounding_box":
            classes.append("document-bbox-annotation")

        return classes

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        """Validate the field configuration."""
        errors = super().validate_config(field_config)
        options = field_config.get("display_options", {})

        # Validate annotation_mode
        valid_modes = ["span", "bounding_box"]
        annotation_mode = options.get("annotation_mode", "span")
        if annotation_mode not in valid_modes:
            errors.append(
                f"Invalid annotation_mode '{annotation_mode}'. "
                f"Must be one of: {', '.join(valid_modes)}"
            )

        # Validate style_theme
        valid_themes = ["default", "minimal", "print"]
        theme = options.get("style_theme", "default")
        if theme not in valid_themes:
            errors.append(
                f"Invalid style_theme '{theme}'. "
                f"Must be one of: {', '.join(valid_themes)}"
            )

        return errors

    def get_data_attributes(
        self,
        field_config: Dict[str, Any],
        data: Any
    ) -> Dict[str, str]:
        """Get data attributes for JavaScript initialization."""
        attrs = super().get_data_attributes(field_config, data)

        # Add format type if available
        if isinstance(data, dict) and "format_name" in data:
            attrs["format"] = data["format_name"]

        return attrs

    def has_inline_label(self, field_config: Dict[str, Any]) -> bool:
        """
        Check if the display handles its own label.

        For collapsible documents, the label is shown in the summary element.
        """
        options = self.get_display_options(field_config)
        return options.get("collapsible", False)
