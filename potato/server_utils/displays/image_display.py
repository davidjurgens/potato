"""
Image Display Type

Renders images for display in the annotation interface.
Supports zoom functionality and links to image annotation schemas.
"""

import html
from typing import Dict, Any, List
from urllib.parse import urlparse

from .base import BaseDisplay


class ImageDisplay(BaseDisplay):
    """
    Display type for image content.

    Displays images with optional zoom functionality.
    Can be linked to image_annotation schemas via source_field.
    """

    name = "image"
    required_fields = ["key"]
    optional_fields = {
        "max_width": None,
        "max_height": None,
        "zoomable": True,
        "alt_text": "",
        "object_fit": "contain",
    }
    description = "Image display with optional zoom"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render an image as HTML.

        Args:
            field_config: The field configuration
            data: The image URL or path

        Returns:
            HTML string for the image display
        """
        if not data:
            return '<div class="image-placeholder">No image provided</div>'

        # Get the image URL
        image_url = str(data)

        # Validate URL (basic check)
        if not self._is_valid_url(image_url):
            return f'<div class="image-error">Invalid image URL: {html.escape(image_url)}</div>'

        # Get display options
        options = self.get_display_options(field_config)
        max_width = options.get("max_width")
        max_height = options.get("max_height")
        zoomable = options.get("zoomable", True)
        alt_text = options.get("alt_text", "")
        object_fit = options.get("object_fit", "contain")

        # Build style
        style_parts = []
        if max_width:
            style_parts.append(f"max-width: {max_width}px" if isinstance(max_width, int) else f"max-width: {max_width}")
        if max_height:
            style_parts.append(f"max-height: {max_height}px" if isinstance(max_height, int) else f"max-height: {max_height}")
        style_parts.append(f"object-fit: {object_fit}")

        style_attr = f' style="{"; ".join(style_parts)}"' if style_parts else ""

        # Escape values for HTML attributes
        escaped_url = html.escape(image_url, quote=True)
        escaped_alt = html.escape(alt_text or "Image content", quote=True)
        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Build the image HTML
        img_classes = ["display-image"]
        if zoomable:
            img_classes.append("zoomable-image")

        img_html = f'''<img
            src="{escaped_url}"
            alt="{escaped_alt}"
            class="{' '.join(img_classes)}"
            data-source-url="{escaped_url}"
            data-field-key="{field_key}"
            {style_attr}
            loading="lazy"
        />'''

        # Wrap in zoom container if zoomable
        if zoomable:
            return f'''
            <div class="image-zoom-container" data-field-key="{field_key}">
                {img_html}
                <div class="image-zoom-controls">
                    <button type="button" class="btn btn-sm btn-outline-secondary zoom-in" title="Zoom in">
                        <span>+</span>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary zoom-out" title="Zoom out">
                        <span>-</span>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary zoom-reset" title="Reset zoom">
                        <span>⟲</span>
                    </button>
                </div>
            </div>
            '''

        return f'<div class="image-container" data-field-key="{field_key}">{img_html}</div>'

    def _is_valid_url(self, url: str) -> bool:
        """
        Check if a URL is valid and safe.

        Args:
            url: The URL to validate

        Returns:
            True if valid, False otherwise
        """
        if not url:
            return False

        # Allow relative paths
        if url.startswith('/') or url.startswith('./') or url.startswith('../'):
            return True

        # Parse the URL
        try:
            parsed = urlparse(url)
            # Must have a scheme (http/https) or be a relative path
            if parsed.scheme:
                return parsed.scheme.lower() in ('http', 'https', 'data')
            # No scheme - treat as relative path
            return True
        except Exception:
            return False

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        options = self.get_display_options(field_config)
        if options.get("zoomable", True):
            classes.append("zoomable")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """Get data attributes for the container."""
        attrs = super().get_data_attributes(field_config, data)
        if data:
            attrs["source-url"] = str(data)
        return attrs

    def get_js_init(self) -> str:
        """Get JavaScript initialization code for zoom functionality."""
        return '''
        // Initialize image zoom controls
        document.querySelectorAll('.image-zoom-container').forEach(container => {
            const img = container.querySelector('img');
            let scale = 1;

            container.querySelector('.zoom-in')?.addEventListener('click', () => {
                scale = Math.min(scale * 1.25, 5);
                img.style.transform = `scale(${scale})`;
            });

            container.querySelector('.zoom-out')?.addEventListener('click', () => {
                scale = Math.max(scale / 1.25, 0.5);
                img.style.transform = `scale(${scale})`;
            });

            container.querySelector('.zoom-reset')?.addEventListener('click', () => {
                scale = 1;
                img.style.transform = 'scale(1)';
            });
        });
        '''
