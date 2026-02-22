"""
PDF Display Component

Renders PDF documents using PDF.js for browser-side rendering.
Supports span annotation on extracted text.

Usage:
    In instance_display config:
    fields:
      - key: document
        type: pdf
        display_options:
          view_mode: scroll
          max_height: 700
          text_layer: true
"""

from typing import Dict, Any, List, Optional
import html
import json
import logging

from .base import BaseDisplay

logger = logging.getLogger(__name__)


class PDFDisplay(BaseDisplay):
    """
    Display type for PDF documents.

    Renders PDFs using PDF.js with an optional text layer for span annotation.
    Can display either a PDF URL or pre-extracted content.

    Supports two annotation modes:
    - span: Text selection and span annotation (default)
    - bounding_box: Draw bounding boxes on PDF pages
    """

    name = "pdf"
    required_fields = ["key"]
    optional_fields = {
        "view_mode": "scroll",      # "scroll", "paginated", or "side-by-side"
        "max_height": 700,          # Max container height in pixels
        "max_width": None,          # Max container width
        "text_layer": True,         # Enable text selection layer
        "show_page_controls": True,  # Show page navigation controls
        "initial_page": 1,          # Page to display initially
        "zoom": "auto",             # "auto", "page-fit", "page-width", or percentage
        "extracted_content": None,  # Pre-extracted FormatOutput data
        "annotation_mode": "span",  # "span" or "bounding_box"
        "bbox_min_size": 10,        # Min bounding box size in pixels
        "bbox_colors": None,        # Custom colors for bounding box labels
        "show_bbox_labels": True,   # Show labels on bounding boxes
    }
    description = "PDF document display with PDF.js rendering"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render a PDF document.

        Args:
            field_config: Display configuration
            data: Either a PDF file path/URL or a dictionary with extracted content

        Returns:
            HTML string for rendering
        """
        options = self.get_display_options(field_config)
        annotation_mode = options.get("annotation_mode", "span")

        # Check if data is pre-extracted content or a file path
        if isinstance(data, dict):
            # Pre-extracted content from format handler
            if annotation_mode == "bounding_box":
                return self._render_extracted_bbox(data, options, field_config)
            return self._render_extracted(data, options, field_config)
        else:
            # File path or URL - render with PDF.js
            if annotation_mode == "bounding_box":
                return self._render_pdfjs_bbox(str(data), options, field_config)
            return self._render_pdfjs(str(data), options, field_config)

    def _render_pdfjs(
        self,
        pdf_source: str,
        options: Dict[str, Any],
        field_config: Dict[str, Any]
    ) -> str:
        """
        Render PDF using PDF.js viewer.
        """
        field_key = field_config.get("key", "pdf")
        view_mode = options.get("view_mode", "scroll")
        max_height = options.get("max_height", 700)
        max_width = options.get("max_width")
        text_layer = options.get("text_layer", True)
        show_controls = options.get("show_page_controls", True)
        zoom = options.get("zoom", "auto")
        initial_page = options.get("initial_page", 1)

        # Build style string
        styles = []
        if max_height:
            styles.append(f"max-height: {max_height}px")
        if max_width:
            styles.append(f"max-width: {max_width}px")
        style_str = "; ".join(styles) if styles else ""

        # Build container
        parts = []

        # Container div with PDF.js viewer
        parts.append(
            f'<div class="pdf-display pdf-viewer-{view_mode}" '
            f'data-field-key="{field_key}" '
            f'data-pdf-source="{html.escape(pdf_source)}" '
            f'data-view-mode="{view_mode}" '
            f'data-text-layer="{str(text_layer).lower()}" '
            f'data-initial-page="{initial_page}" '
            f'data-zoom="{zoom}" '
            f'style="{style_str}">'
        )

        # Page controls
        if show_controls:
            parts.append('''
                <div class="pdf-controls">
                    <button type="button" class="pdf-prev-btn" title="Previous page">&#x25C0;</button>
                    <span class="pdf-page-info">
                        <span class="pdf-current-page">1</span> /
                        <span class="pdf-total-pages">-</span>
                    </span>
                    <button type="button" class="pdf-next-btn" title="Next page">&#x25B6;</button>
                    <select class="pdf-zoom-select">
                        <option value="auto">Auto</option>
                        <option value="page-fit">Page Fit</option>
                        <option value="page-width">Page Width</option>
                        <option value="0.5">50%</option>
                        <option value="0.75">75%</option>
                        <option value="1">100%</option>
                        <option value="1.25">125%</option>
                        <option value="1.5">150%</option>
                        <option value="2">200%</option>
                    </select>
                </div>
            ''')

        # Canvas container for PDF.js
        parts.append('''
            <div class="pdf-canvas-container">
                <canvas class="pdf-canvas"></canvas>
        ''')

        # Text layer for selection (if enabled)
        if text_layer:
            parts.append('<div class="pdf-text-layer"></div>')

        parts.append('</div>')  # Close canvas container

        # Loading indicator
        parts.append('''
            <div class="pdf-loading">
                <span class="pdf-loading-spinner"></span>
                Loading PDF...
            </div>
        ''')

        # Error display
        parts.append('<div class="pdf-error" style="display: none;"></div>')

        parts.append('</div>')  # Close main container

        return "\n".join(parts)

    def _render_extracted(
        self,
        content: Dict[str, Any],
        options: Dict[str, Any],
        field_config: Dict[str, Any]
    ) -> str:
        """
        Render pre-extracted PDF content as HTML.

        This is used when the PDF has already been processed by the
        format handler and we want to display the extracted text.
        """
        field_key = field_config.get("key", "pdf")
        max_height = options.get("max_height", 700)

        # Check if this is FormatOutput-style content
        if "rendered_html" in content:
            inner_html = content["rendered_html"]
        elif "text" in content:
            # Fall back to plain text
            inner_html = f'<pre class="pdf-extracted-text">{html.escape(content["text"])}</pre>'
        else:
            inner_html = '<div class="pdf-error">No content available</div>'

        # Build container
        style_str = f"max-height: {max_height}px; overflow-y: auto;" if max_height else ""

        # Add metadata if available
        metadata_html = ""
        if "metadata" in content:
            meta = content["metadata"]
            if "total_pages" in meta:
                metadata_html = f'<div class="pdf-metadata">Pages: {meta["total_pages"]}</div>'

        return f'''
            <div class="pdf-display pdf-extracted"
                 data-field-key="{field_key}"
                 style="{style_str}">
                {metadata_html}
                <div class="pdf-content-wrapper">
                    {inner_html}
                </div>
            </div>
        '''

    def _render_pdfjs_bbox(
        self,
        pdf_source: str,
        options: Dict[str, Any],
        field_config: Dict[str, Any]
    ) -> str:
        """
        Render PDF with bounding box annotation support.

        Uses paginated view mode by default for better bbox drawing experience.
        """
        field_key = field_config.get("key", "pdf")
        # Force paginated mode for bounding box annotation
        view_mode = "paginated"
        max_height = options.get("max_height", 700)
        max_width = options.get("max_width")
        show_controls = options.get("show_page_controls", True)
        zoom = options.get("zoom", "page-fit")
        initial_page = options.get("initial_page", 1)
        bbox_min_size = options.get("bbox_min_size", 10)
        show_labels = options.get("show_bbox_labels", True)

        # Build style string
        styles = []
        if max_height:
            styles.append(f"max-height: {max_height}px")
        if max_width:
            styles.append(f"max-width: {max_width}px")
        style_str = "; ".join(styles) if styles else ""

        parts = []

        # Container div with bbox annotation mode
        parts.append(
            f'<div class="pdf-display pdf-viewer-paginated pdf-bbox-mode" '
            f'data-field-key="{field_key}" '
            f'data-pdf-source="{html.escape(pdf_source)}" '
            f'data-view-mode="paginated" '
            f'data-annotation-mode="bounding_box" '
            f'data-initial-page="{initial_page}" '
            f'data-zoom="{zoom}" '
            f'data-bbox-min-size="{bbox_min_size}" '
            f'data-show-bbox-labels="{str(show_labels).lower()}" '
            f'style="{style_str}">'
        )

        # Enhanced page controls for paginated navigation
        if show_controls:
            parts.append('''
                <div class="pdf-controls pdf-bbox-controls">
                    <div class="pdf-navigation">
                        <button type="button" class="pdf-first-btn" title="First page">&#x23EA;</button>
                        <button type="button" class="pdf-prev-btn" title="Previous page">&#x25C0;</button>
                        <span class="pdf-page-info">
                            Page <input type="number" class="pdf-page-input" min="1" value="1" /> of
                            <span class="pdf-total-pages">-</span>
                        </span>
                        <button type="button" class="pdf-next-btn" title="Next page">&#x25B6;</button>
                        <button type="button" class="pdf-last-btn" title="Last page">&#x23E9;</button>
                    </div>
                    <div class="pdf-bbox-tools">
                        <button type="button" class="pdf-bbox-draw-btn active" title="Draw bounding box">
                            &#x25A1; Draw
                        </button>
                        <button type="button" class="pdf-bbox-select-btn" title="Select bounding box">
                            &#x2191; Select
                        </button>
                        <button type="button" class="pdf-bbox-delete-btn" title="Delete selected">
                            &#x2715; Delete
                        </button>
                    </div>
                    <select class="pdf-zoom-select">
                        <option value="page-fit" selected>Page Fit</option>
                        <option value="page-width">Page Width</option>
                        <option value="0.5">50%</option>
                        <option value="0.75">75%</option>
                        <option value="1">100%</option>
                        <option value="1.25">125%</option>
                        <option value="1.5">150%</option>
                        <option value="2">200%</option>
                    </select>
                </div>
            ''')

        # Canvas container for PDF rendering and bbox overlay
        parts.append('''
            <div class="pdf-canvas-container pdf-bbox-container">
                <canvas class="pdf-canvas"></canvas>
                <canvas class="pdf-bbox-canvas" title="Draw bounding boxes here"></canvas>
                <div class="pdf-bbox-list" style="display: none;"></div>
            </div>
        ''')

        # Bounding box info panel
        parts.append('''
            <div class="pdf-bbox-info">
                <div class="pdf-bbox-count">Boxes on page: <span class="count">0</span></div>
                <div class="pdf-bbox-total">Total boxes: <span class="count">0</span></div>
            </div>
        ''')

        # Loading indicator
        parts.append('''
            <div class="pdf-loading">
                <span class="pdf-loading-spinner"></span>
                Loading PDF...
            </div>
        ''')

        # Error display
        parts.append('<div class="pdf-error" style="display: none;"></div>')

        parts.append('</div>')  # Close main container

        return "\n".join(parts)

    def _render_extracted_bbox(
        self,
        content: Dict[str, Any],
        options: Dict[str, Any],
        field_config: Dict[str, Any]
    ) -> str:
        """
        Render pre-extracted PDF content with bounding box support.

        For pre-extracted content, we render page images for bbox annotation.
        """
        field_key = field_config.get("key", "pdf")
        max_height = options.get("max_height", 700)
        bbox_min_size = options.get("bbox_min_size", 10)
        show_labels = options.get("show_bbox_labels", True)

        metadata = content.get("metadata", {})
        total_pages = metadata.get("total_pages", 1)
        pages = metadata.get("pages", [])

        style_str = f"max-height: {max_height}px; overflow-y: auto;" if max_height else ""

        parts = []
        parts.append(
            f'<div class="pdf-display pdf-extracted pdf-bbox-mode" '
            f'data-field-key="{field_key}" '
            f'data-annotation-mode="bounding_box" '
            f'data-total-pages="{total_pages}" '
            f'data-bbox-min-size="{bbox_min_size}" '
            f'data-show-bbox-labels="{str(show_labels).lower()}" '
            f'style="{style_str}">'
        )

        # Page navigation
        parts.append(f'''
            <div class="pdf-controls pdf-bbox-controls">
                <div class="pdf-navigation">
                    <button type="button" class="pdf-prev-btn" title="Previous page">&#x25C0;</button>
                    <span class="pdf-page-info">
                        Page <input type="number" class="pdf-page-input" min="1" max="{total_pages}" value="1" /> of
                        <span class="pdf-total-pages">{total_pages}</span>
                    </span>
                    <button type="button" class="pdf-next-btn" title="Next page">&#x25B6;</button>
                </div>
                <div class="pdf-bbox-tools">
                    <button type="button" class="pdf-bbox-draw-btn active" title="Draw bounding box">
                        &#x25A1; Draw
                    </button>
                    <button type="button" class="pdf-bbox-select-btn" title="Select">
                        &#x2191; Select
                    </button>
                    <button type="button" class="pdf-bbox-delete-btn" title="Delete">
                        &#x2715; Delete
                    </button>
                </div>
            </div>
        ''')

        # Render each page with bbox overlay
        if "rendered_html" in content:
            # Content has pre-rendered HTML
            parts.append('<div class="pdf-pages-container">')
            parts.append(content["rendered_html"])
            parts.append('</div>')
        else:
            # Render pages from metadata
            parts.append('<div class="pdf-pages-container">')
            for i, page_meta in enumerate(pages, start=1):
                page_width = page_meta.get("width", 612)
                page_height = page_meta.get("height", 792)
                parts.append(
                    f'<div class="pdf-page-wrapper" '
                    f'data-page="{i}" '
                    f'data-page-width="{page_width}" '
                    f'data-page-height="{page_height}">'
                )
                parts.append(f'<div class="pdf-page-number">Page {i}</div>')
                parts.append('<div class="pdf-page-content-bbox">')
                parts.append(f'<canvas class="pdf-bbox-canvas-{i}"></canvas>')
                parts.append('</div></div>')
            parts.append('</div>')

        # Bounding box info
        parts.append('''
            <div class="pdf-bbox-info">
                <div class="pdf-bbox-count">Boxes on page: <span class="count">0</span></div>
                <div class="pdf-bbox-total">Total boxes: <span class="count">0</span></div>
            </div>
        ''')

        parts.append('</div>')

        return "\n".join(parts)

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the display container."""
        classes = super().get_css_classes(field_config)
        options = self.get_display_options(field_config)

        if field_config.get("span_target"):
            classes.append("span-target-pdf")

        view_mode = options.get("view_mode", "scroll")
        classes.append(f"pdf-mode-{view_mode}")

        annotation_mode = options.get("annotation_mode", "span")
        if annotation_mode == "bounding_box":
            classes.append("pdf-bbox-annotation")

        return classes

    def get_data_attributes(
        self,
        field_config: Dict[str, Any],
        data: Any
    ) -> Dict[str, str]:
        """Get data attributes for JavaScript initialization."""
        attrs = super().get_data_attributes(field_config, data)
        options = self.get_display_options(field_config)

        attrs["view-mode"] = options.get("view_mode", "scroll")
        attrs["text-layer"] = str(options.get("text_layer", True)).lower()

        return attrs

    def get_js_init(self) -> Optional[str]:
        """
        Return JavaScript initialization code for PDF.js.
        """
        return '''
            // PDF display initialization is handled by pdf-viewer.js
            // which is loaded as a separate script
            if (typeof initPDFViewers === 'function') {
                initPDFViewers();
            }
        '''

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        """Validate the field configuration."""
        errors = super().validate_config(field_config)
        options = field_config.get("display_options", {})

        # Validate view_mode
        valid_modes = ["scroll", "paginated", "side-by-side"]
        view_mode = options.get("view_mode", "scroll")
        if view_mode not in valid_modes:
            errors.append(
                f"Invalid view_mode '{view_mode}'. "
                f"Must be one of: {', '.join(valid_modes)}"
            )

        # Validate annotation_mode
        valid_annotation_modes = ["span", "bounding_box"]
        annotation_mode = options.get("annotation_mode", "span")
        if annotation_mode not in valid_annotation_modes:
            errors.append(
                f"Invalid annotation_mode '{annotation_mode}'. "
                f"Must be one of: {', '.join(valid_annotation_modes)}"
            )

        # Validate zoom
        zoom = options.get("zoom", "auto")
        valid_zoom = ["auto", "page-fit", "page-width"]
        if zoom not in valid_zoom:
            try:
                float(zoom)
            except (TypeError, ValueError):
                errors.append(
                    f"Invalid zoom '{zoom}'. "
                    f"Must be one of {valid_zoom} or a number"
                )

        return errors
