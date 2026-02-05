"""
Video Display Type

Renders video content for display in the annotation interface.
Supports video controls and links to video annotation schemas.
"""

import html
from typing import Dict, Any, List
from urllib.parse import urlparse

from .base import BaseDisplay


class VideoDisplay(BaseDisplay):
    """
    Display type for video content.

    Displays videos with standard HTML5 video player controls.
    Can be linked to video_annotation schemas via source_field.
    """

    name = "video"
    required_fields = ["key"]
    optional_fields = {
        "max_width": None,
        "max_height": None,
        "controls": True,
        "autoplay": False,
        "loop": False,
        "muted": False,
        "poster": None,
    }
    description = "Video player display"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render a video as HTML.

        Args:
            field_config: The field configuration
            data: The video URL or path

        Returns:
            HTML string for the video display
        """
        if not data:
            return '<div class="video-placeholder">No video provided</div>'

        # Get the video URL
        video_url = str(data)

        # Validate URL
        if not self._is_valid_url(video_url):
            return f'<div class="video-error">Invalid video URL: {html.escape(video_url)}</div>'

        # Get display options
        options = self.get_display_options(field_config)
        max_width = options.get("max_width")
        max_height = options.get("max_height")
        controls = options.get("controls", True)
        autoplay = options.get("autoplay", False)
        loop = options.get("loop", False)
        muted = options.get("muted", False)
        poster = options.get("poster")

        # Build style
        style_parts = ["max-width: 100%"]
        if max_width:
            style_parts.append(f"width: {max_width}px" if isinstance(max_width, int) else f"width: {max_width}")
        if max_height:
            style_parts.append(f"max-height: {max_height}px" if isinstance(max_height, int) else f"max-height: {max_height}")

        style_attr = f' style="{"; ".join(style_parts)}"'

        # Build attributes
        attrs = []
        if controls:
            attrs.append("controls")
        if autoplay:
            attrs.append("autoplay")
        if loop:
            attrs.append("loop")
        if muted:
            attrs.append("muted")
        if poster:
            attrs.append(f'poster="{html.escape(poster, quote=True)}"')

        attrs_str = " ".join(attrs)

        # Escape values
        escaped_url = html.escape(video_url, quote=True)
        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Determine video type from URL
        video_type = self._get_video_type(video_url)
        type_attr = f' type="{video_type}"' if video_type else ""

        return f'''
        <div class="video-container" data-field-key="{field_key}">
            <video class="display-video" data-source-url="{escaped_url}" {attrs_str}{style_attr}>
                <source src="{escaped_url}"{type_attr}>
                Your browser does not support the video element.
            </video>
        </div>
        '''

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid."""
        if not url:
            return False

        if url.startswith('/') or url.startswith('./') or url.startswith('../'):
            return True

        try:
            parsed = urlparse(url)
            if parsed.scheme:
                return parsed.scheme.lower() in ('http', 'https')
            return True
        except Exception:
            return False

    def _get_video_type(self, url: str) -> str:
        """Get video MIME type from URL extension."""
        url_lower = url.lower()
        if url_lower.endswith('.mp4'):
            return 'video/mp4'
        elif url_lower.endswith('.webm'):
            return 'video/webm'
        elif url_lower.endswith('.ogg') or url_lower.endswith('.ogv'):
            return 'video/ogg'
        elif url_lower.endswith('.mov'):
            return 'video/quicktime'
        return ""

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """Get data attributes for the container."""
        attrs = super().get_data_attributes(field_config, data)
        if data:
            attrs["source-url"] = str(data)
        return attrs
