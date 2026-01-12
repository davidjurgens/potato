"""
Unit tests for the video annotation schema.

Tests the video layout generation functionality including:
- Basic video element generation
- Video attributes (controls, autoplay, loop, muted)
- Custom CSS styling
- Multiple source support
- Fallback content
- URL and file path handling
"""

import pytest
import os
import tempfile
from potato.server_utils.schemas.video import (
    generate_video_layout,
    _generate_video_attributes,
    _generate_css_style,
    _generate_video_sources,
    _generate_fallback_content,
    _get_mime_type,
    _is_url
)


class TestVideoLayout:
    """Tests for the main generate_video_layout function."""

    def test_basic_video_layout_with_url(self):
        """Test that video layout generates correctly with a URL."""
        scheme = {
            "name": "test_video",
            "description": "Test Video",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4"
        }

        html, keybindings = generate_video_layout(scheme)

        # Should return HTML and empty keybindings
        assert isinstance(html, str)
        assert isinstance(keybindings, list)
        assert len(keybindings) == 0

        # Should contain video element
        assert "<video" in html
        assert "</video>" in html

        # Should contain the video source
        assert "https://example.com/video.mp4" in html
        assert 'type="video/mp4"' in html

    def test_video_layout_with_local_file(self):
        """Test that video layout works with a local file path."""
        # Create a temporary video file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            temp_path = f.name
            f.write(b"fake video content")

        try:
            scheme = {
                "name": "local_video",
                "description": "Local Video Test",
                "annotation_type": "video",
                "video_path": temp_path
            }

            html, keybindings = generate_video_layout(scheme)

            assert "<video" in html
            assert temp_path in html
        finally:
            os.unlink(temp_path)

    def test_video_with_controls_enabled(self):
        """Test that controls attribute is added by default."""
        scheme = {
            "name": "controls_test",
            "description": "Controls Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4"
        }

        html, _ = generate_video_layout(scheme)

        # Controls should be enabled by default
        assert "controls" in html

    def test_video_with_controls_disabled(self):
        """Test that controls can be disabled."""
        scheme = {
            "name": "no_controls",
            "description": "No Controls Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "controls": False
        }

        html, _ = generate_video_layout(scheme)

        # Should not have controls attribute (check it's not in the video tag)
        # The word "controls" might appear elsewhere, so check the video attributes specifically
        attrs = _generate_video_attributes(scheme)
        assert "controls" not in attrs

    def test_video_with_autoplay(self):
        """Test autoplay attribute."""
        scheme = {
            "name": "autoplay_test",
            "description": "Autoplay Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "autoplay": True
        }

        html, _ = generate_video_layout(scheme)

        assert "autoplay" in html

    def test_video_with_loop(self):
        """Test loop attribute."""
        scheme = {
            "name": "loop_test",
            "description": "Loop Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "loop": True
        }

        html, _ = generate_video_layout(scheme)

        assert "loop" in html

    def test_video_with_muted(self):
        """Test muted attribute."""
        scheme = {
            "name": "muted_test",
            "description": "Muted Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "muted": True
        }

        html, _ = generate_video_layout(scheme)

        assert "muted" in html

    def test_video_with_custom_dimensions(self):
        """Test custom width and height."""
        scheme = {
            "name": "custom_size",
            "description": "Custom Size Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "custom_css": {
                "width": "640",
                "height": "480"
            }
        }

        html, _ = generate_video_layout(scheme)

        assert "width: 640px" in html
        assert "height: 480px" in html

    def test_video_with_fallback_text(self):
        """Test custom fallback text."""
        scheme = {
            "name": "fallback_test",
            "description": "Fallback Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4",
            "fallback_text": "Please upgrade your browser"
        }

        html, _ = generate_video_layout(scheme)

        assert "Please upgrade your browser" in html

    def test_video_missing_path_shows_error(self):
        """Test that missing video_path is handled gracefully."""
        scheme = {
            "name": "missing_path",
            "description": "Missing Path Test",
            "annotation_type": "video"
            # video_path is missing
        }

        # Should return error HTML, not raise exception (due to safe_generate_layout)
        html, keybindings = generate_video_layout(scheme)

        # The safe_generate_layout wrapper should catch the error
        assert "error" in html.lower() or "Error" in html

    def test_video_escapes_html_in_description(self):
        """Test that HTML in description is escaped."""
        scheme = {
            "name": "xss_test",
            "description": "<script>alert('xss')</script>",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4"
        }

        html, _ = generate_video_layout(scheme)

        # Script tags should be escaped
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestVideoAttributes:
    """Tests for _generate_video_attributes function."""

    def test_default_attributes(self):
        """Test default attributes (controls only)."""
        scheme = {"video_path": "test.mp4"}

        attrs = _generate_video_attributes(scheme)

        assert "controls" in attrs
        assert "autoplay" not in attrs
        assert "loop" not in attrs
        assert "muted" not in attrs

    def test_all_attributes_enabled(self):
        """Test with all attributes enabled."""
        scheme = {
            "video_path": "test.mp4",
            "controls": True,
            "autoplay": True,
            "loop": True,
            "muted": True
        }

        attrs = _generate_video_attributes(scheme)

        assert "controls" in attrs
        assert "autoplay" in attrs
        assert "loop" in attrs
        assert "muted" in attrs


class TestCssStyle:
    """Tests for _generate_css_style function."""

    def test_default_dimensions(self):
        """Test default width and height."""
        scheme = {}

        css = _generate_css_style(scheme)

        assert "width: 320px" in css
        assert "height: 240px" in css

    def test_custom_dimensions(self):
        """Test custom width and height."""
        scheme = {
            "custom_css": {
                "width": "800",
                "height": "600"
            }
        }

        css = _generate_css_style(scheme)

        assert "width: 800px" in css
        assert "height: 600px" in css


class TestVideoSources:
    """Tests for _generate_video_sources function."""

    def test_single_source(self):
        """Test single video source."""
        scheme = {"video_path": "video.mp4"}

        sources = _generate_video_sources(scheme)

        assert '<source src="video.mp4"' in sources
        assert 'type="video/mp4"' in sources

    def test_multiple_sources(self):
        """Test multiple video sources."""
        scheme = {
            "video_path": "video.mp4",
            "additional_sources": ["video.webm", "video.ogg"]
        }

        sources = _generate_video_sources(scheme)

        assert "video.mp4" in sources
        assert "video.webm" in sources
        assert "video.ogg" in sources
        assert 'type="video/mp4"' in sources
        assert 'type="video/webm"' in sources
        assert 'type="video/ogg"' in sources


class TestMimeType:
    """Tests for _get_mime_type function."""

    def test_mp4_mime_type(self):
        """Test MP4 MIME type detection."""
        assert _get_mime_type("video.mp4") == "video/mp4"
        assert _get_mime_type("video.MP4") == "video/mp4"

    def test_webm_mime_type(self):
        """Test WebM MIME type detection."""
        assert _get_mime_type("video.webm") == "video/webm"

    def test_ogg_mime_type(self):
        """Test Ogg MIME type detection."""
        assert _get_mime_type("video.ogg") == "video/ogg"

    def test_unknown_extension_defaults_to_mp4(self):
        """Test unknown extension defaults to MP4."""
        assert _get_mime_type("video.avi") == "video/mp4"
        assert _get_mime_type("video.mov") == "video/mp4"

    def test_url_mime_type(self):
        """Test MIME type detection for URLs."""
        assert _get_mime_type("https://example.com/video.mp4") == "video/mp4"
        assert _get_mime_type("https://example.com/video.webm") == "video/webm"


class TestFallbackContent:
    """Tests for _generate_fallback_content function."""

    def test_default_fallback(self):
        """Test default fallback text."""
        scheme = {}

        fallback = _generate_fallback_content(scheme)

        assert "browser does not support" in fallback.lower()

    def test_custom_fallback(self):
        """Test custom fallback text."""
        scheme = {"fallback_text": "Custom fallback message"}

        fallback = _generate_fallback_content(scheme)

        assert fallback == "Custom fallback message"

    def test_fallback_escapes_html(self):
        """Test that HTML in fallback is escaped."""
        scheme = {"fallback_text": "<script>alert('xss')</script>"}

        fallback = _generate_fallback_content(scheme)

        assert "<script>" not in fallback
        assert "&lt;script&gt;" in fallback


class TestIsUrl:
    """Tests for _is_url function."""

    def test_http_url(self):
        """Test HTTP URL detection."""
        assert _is_url("http://example.com/video.mp4") is True

    def test_https_url(self):
        """Test HTTPS URL detection."""
        assert _is_url("https://example.com/video.mp4") is True

    def test_protocol_relative_url(self):
        """Test protocol-relative URL detection."""
        assert _is_url("//example.com/video.mp4") is True

    def test_data_url(self):
        """Test data URL detection."""
        assert _is_url("data:video/mp4;base64,AAAA") is True

    def test_local_path(self):
        """Test local file path is not detected as URL."""
        assert _is_url("/path/to/video.mp4") is False
        assert _is_url("video.mp4") is False
        assert _is_url("./videos/video.mp4") is False
        assert _is_url("../videos/video.mp4") is False

    def test_windows_path(self):
        """Test Windows-style path is not detected as URL."""
        assert _is_url("C:\\videos\\video.mp4") is False


class TestVideoRegistryIntegration:
    """Tests for video schema integration with the registry."""

    def test_video_registered_in_registry(self):
        """Test that video schema is registered in the schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("video")

    def test_video_in_supported_types(self):
        """Test that video is in the list of supported types."""
        from potato.server_utils.schemas.registry import schema_registry

        supported = schema_registry.get_supported_types()
        assert "video" in supported

    def test_video_schema_metadata(self):
        """Test video schema metadata in registry."""
        from potato.server_utils.schemas.registry import schema_registry

        schema = schema_registry.get("video")
        assert schema is not None
        assert schema.name == "video"
        assert "video_path" in schema.required_fields
        assert schema.supports_keybindings is False

    def test_generate_via_registry(self):
        """Test generating video layout via the registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "registry_test",
            "description": "Registry Test",
            "annotation_type": "video",
            "video_path": "https://example.com/video.mp4"
        }

        html, keybindings = schema_registry.generate(scheme)

        assert "<video" in html
        assert "https://example.com/video.mp4" in html
        assert keybindings == []
