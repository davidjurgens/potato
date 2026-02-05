"""
Unit tests for the display registry.
"""

import pytest
from potato.server_utils.displays import display_registry, DisplayDefinition, DisplayRegistry
from potato.server_utils.displays.base import BaseDisplay


class TestDisplayRegistry:
    """Tests for the DisplayRegistry class."""

    def test_registry_has_builtin_types(self):
        """Test that built-in display types are registered."""
        supported = display_registry.get_supported_types()
        assert "text" in supported
        assert "image" in supported
        assert "video" in supported
        assert "audio" in supported
        assert "dialogue" in supported
        assert "pairwise" in supported
        assert "html" in supported

    def test_render_text(self):
        """Test rendering text content."""
        config = {"key": "text"}
        data = "Hello, world!"
        html = display_registry.render("text", config, data)
        assert "Hello, world!" in html
        assert "display-field" in html

    def test_render_image(self):
        """Test rendering image content."""
        config = {"key": "img"}
        data = "http://example.com/image.jpg"
        html = display_registry.render("image", config, data)
        assert "http://example.com/image.jpg" in html
        assert "display-image" in html

    def test_render_video(self):
        """Test rendering video content."""
        config = {"key": "vid"}
        data = "http://example.com/video.mp4"
        html = display_registry.render("video", config, data)
        assert "http://example.com/video.mp4" in html
        assert "display-video" in html

    def test_render_audio(self):
        """Test rendering audio content."""
        config = {"key": "aud"}
        data = "http://example.com/audio.mp3"
        html = display_registry.render("audio", config, data)
        assert "http://example.com/audio.mp3" in html
        assert "display-audio" in html

    def test_render_dialogue(self):
        """Test rendering dialogue content."""
        config = {"key": "dlg"}
        data = ["Speaker A: Hello", "Speaker B: Hi there"]
        html = display_registry.render("dialogue", config, data)
        assert "Speaker A" in html
        assert "Speaker B" in html
        assert "dialogue-turn" in html

    def test_render_pairwise(self):
        """Test rendering pairwise content."""
        config = {"key": "pair"}
        data = ["Option 1", "Option 2"]
        html = display_registry.render("pairwise", config, data)
        assert "Option 1" in html
        assert "Option 2" in html
        assert "pairwise-cell" in html

    def test_unknown_type_raises_error(self):
        """Test that unknown types raise ValueError."""
        with pytest.raises(ValueError) as excinfo:
            display_registry.render("unknown_type", {}, "data")
        assert "Unknown display type" in str(excinfo.value)

    def test_is_registered(self):
        """Test is_registered method."""
        assert display_registry.is_registered("text")
        assert display_registry.is_registered("image")
        assert not display_registry.is_registered("nonexistent")

    def test_supports_span_target(self):
        """Test supports_span_target method."""
        assert display_registry.supports_span_target("text")
        assert display_registry.supports_span_target("dialogue")
        assert not display_registry.supports_span_target("image")
        assert not display_registry.supports_span_target("video")

    def test_list_displays(self):
        """Test list_displays method."""
        displays = display_registry.list_displays()
        assert isinstance(displays, list)
        assert len(displays) > 0

        # Check structure of display info
        text_display = next((d for d in displays if d["name"] == "text"), None)
        assert text_display is not None
        assert "description" in text_display
        assert "required_fields" in text_display
        assert "supports_span_target" in text_display


class TestCustomPlugin:
    """Tests for plugin registration."""

    def test_register_plugin(self):
        """Test registering a custom plugin display type."""
        # Create a new registry for isolated testing
        registry = DisplayRegistry()

        class CustomDisplay(BaseDisplay):
            name = "custom_test"
            description = "A custom test display"

            def render(self, field_config, data):
                return f"<div>Custom: {data}</div>"

        # Register the plugin
        registry.register_plugin("custom_test", CustomDisplay())

        # Verify it's registered
        assert registry.is_registered("custom_test")
        assert "custom_test" in registry.get_supported_types()

        # Test rendering
        html = registry.render("custom_test", {"key": "test"}, "test data")
        assert "Custom: test data" in html

    def test_duplicate_registration_raises_error(self):
        """Test that duplicate registration raises ValueError."""
        registry = DisplayRegistry()

        class CustomDisplay(BaseDisplay):
            name = "duplicate"
            def render(self, config, data):
                return ""

        registry.register_plugin("duplicate", CustomDisplay())

        with pytest.raises(ValueError) as excinfo:
            registry.register_plugin("duplicate", CustomDisplay())
        assert "already registered" in str(excinfo.value)
