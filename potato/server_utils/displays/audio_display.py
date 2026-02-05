"""
Audio Display Type

Renders audio content for display in the annotation interface.
Supports standard audio controls and links to audio annotation schemas.
"""

import html
from typing import Dict, Any, List
from urllib.parse import urlparse

from .base import BaseDisplay


class AudioDisplay(BaseDisplay):
    """
    Display type for audio content.

    Displays audio with standard HTML5 audio player controls.
    Can be linked to audio_annotation schemas via source_field.
    """

    name = "audio"
    required_fields = ["key"]
    optional_fields = {
        "controls": True,
        "autoplay": False,
        "loop": False,
        "muted": False,
        "preload": "metadata",
        "show_waveform": False,
    }
    description = "Audio player display"
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render audio as HTML.

        Args:
            field_config: The field configuration
            data: The audio URL or path

        Returns:
            HTML string for the audio display
        """
        if not data:
            return '<div class="audio-placeholder">No audio provided</div>'

        # Get the audio URL
        audio_url = str(data)

        # Validate URL
        if not self._is_valid_url(audio_url):
            return f'<div class="audio-error">Invalid audio URL: {html.escape(audio_url)}</div>'

        # Get display options
        options = self.get_display_options(field_config)
        controls = options.get("controls", True)
        autoplay = options.get("autoplay", False)
        loop = options.get("loop", False)
        muted = options.get("muted", False)
        preload = options.get("preload", "metadata")
        show_waveform = options.get("show_waveform", False)

        # Build attributes
        attrs = [f'preload="{preload}"']
        if controls:
            attrs.append("controls")
        if autoplay:
            attrs.append("autoplay")
        if loop:
            attrs.append("loop")
        if muted:
            attrs.append("muted")

        attrs_str = " ".join(attrs)

        # Escape values
        escaped_url = html.escape(audio_url, quote=True)
        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Determine audio type from URL
        audio_type = self._get_audio_type(audio_url)
        type_attr = f' type="{audio_type}"' if audio_type else ""

        # Build HTML
        waveform_html = ""
        if show_waveform:
            waveform_html = f'''
            <div class="audio-waveform" data-audio-url="{escaped_url}">
                <canvas class="waveform-canvas"></canvas>
            </div>
            '''

        return f'''
        <div class="audio-container" data-field-key="{field_key}">
            {waveform_html}
            <audio class="display-audio" data-source-url="{escaped_url}" {attrs_str}>
                <source src="{escaped_url}"{type_attr}>
                Your browser does not support the audio element.
            </audio>
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

    def _get_audio_type(self, url: str) -> str:
        """Get audio MIME type from URL extension."""
        url_lower = url.lower()
        if url_lower.endswith('.mp3'):
            return 'audio/mpeg'
        elif url_lower.endswith('.wav'):
            return 'audio/wav'
        elif url_lower.endswith('.ogg') or url_lower.endswith('.oga'):
            return 'audio/ogg'
        elif url_lower.endswith('.m4a') or url_lower.endswith('.aac'):
            return 'audio/aac'
        elif url_lower.endswith('.webm'):
            return 'audio/webm'
        elif url_lower.endswith('.flac'):
            return 'audio/flac'
        return ""

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        if self.get_display_options(field_config).get("show_waveform"):
            classes.append("with-waveform")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """Get data attributes for the container."""
        attrs = super().get_data_attributes(field_config, data)
        if data:
            attrs["source-url"] = str(data)
        return attrs
