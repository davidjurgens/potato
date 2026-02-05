"""
Unit tests for the InstanceDisplayRenderer.
"""

import pytest
from potato.server_utils.instance_display import (
    InstanceDisplayRenderer,
    InstanceDisplayError,
    get_instance_display_renderer
)


class TestInstanceDisplayRenderer:
    """Tests for the InstanceDisplayRenderer class."""

    def test_no_instance_display_config(self):
        """Test renderer with no instance_display configuration."""
        config = {}
        renderer = InstanceDisplayRenderer(config)

        assert not renderer.has_instance_display
        assert renderer.span_targets == []
        assert renderer.should_use_legacy_display()

    def test_basic_text_display(self):
        """Test rendering a basic text field."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "text", "type": "text", "label": "Content"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"text": "Hello, world!"}

        html = renderer.render(instance_data)
        assert "Hello, world!" in html
        assert "instance-display-container" in html

    def test_image_display(self):
        """Test rendering an image field."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "image_url", "type": "image", "label": "Image"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"image_url": "http://example.com/img.jpg"}

        html = renderer.render(instance_data)
        assert "http://example.com/img.jpg" in html
        assert "display-image" in html

    def test_multiple_fields(self):
        """Test rendering multiple fields."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "image", "type": "image"},
                    {"key": "caption", "type": "text"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {
            "image": "http://example.com/img.jpg",
            "caption": "A beautiful sunset"
        }

        html = renderer.render(instance_data)
        assert "http://example.com/img.jpg" in html
        assert "A beautiful sunset" in html

    def test_span_target_tracking(self):
        """Test that span targets are properly tracked."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "image", "type": "image"},
                    {"key": "text1", "type": "text", "span_target": True},
                    {"key": "text2", "type": "text", "span_target": True}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)

        assert renderer.span_targets == ["text1", "text2"]

    def test_missing_field_raises_error(self):
        """Test that missing fields raise InstanceDisplayError."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "required_field", "type": "text"}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"other_field": "value"}

        with pytest.raises(InstanceDisplayError) as excinfo:
            renderer.render(instance_data)
        assert "required_field" in str(excinfo.value)
        assert "not found" in str(excinfo.value)

    def test_template_variables(self):
        """Test get_template_variables method."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "text", "type": "text", "span_target": True}
                ]
            }
        }
        renderer = InstanceDisplayRenderer(config)
        instance_data = {"text": "Test content"}

        vars = renderer.get_template_variables(instance_data)

        assert "display_html" in vars
        assert "display_fields" in vars
        assert "display_raw" in vars
        assert "span_targets" in vars
        assert "multi_span_mode" in vars
        assert "has_instance_display" in vars

        assert vars["has_instance_display"] is True
        assert vars["span_targets"] == ["text"]
        assert vars["display_raw"]["text"] == "Test content"

    def test_multi_span_mode(self):
        """Test multi_span_mode detection."""
        # Single span target
        config1 = {
            "instance_display": {
                "fields": [
                    {"key": "text", "type": "text", "span_target": True}
                ]
            }
        }
        renderer1 = InstanceDisplayRenderer(config1)
        vars1 = renderer1.get_template_variables({"text": "test"})
        assert vars1["multi_span_mode"] is False

        # Multiple span targets
        config2 = {
            "instance_display": {
                "fields": [
                    {"key": "source", "type": "text", "span_target": True},
                    {"key": "summary", "type": "text", "span_target": True}
                ]
            }
        }
        renderer2 = InstanceDisplayRenderer(config2)
        vars2 = renderer2.get_template_variables({"source": "a", "summary": "b"})
        assert vars2["multi_span_mode"] is True

    def test_layout_direction(self):
        """Test layout direction configuration."""
        config = {
            "instance_display": {
                "fields": [
                    {"key": "a", "type": "text"},
                    {"key": "b", "type": "text"}
                ],
                "layout": {
                    "direction": "horizontal",
                    "gap": "30px"
                }
            }
        }
        renderer = InstanceDisplayRenderer(config)
        html = renderer.render({"a": "A", "b": "B"})

        assert "layout-horizontal" in html
        assert "gap: 30px" in html

    def test_get_primary_text_field(self):
        """Test get_primary_text_field method."""
        # With span target
        config1 = {
            "instance_display": {
                "fields": [
                    {"key": "caption", "type": "text", "span_target": True}
                ]
            }
        }
        renderer1 = InstanceDisplayRenderer(config1)
        assert renderer1.get_primary_text_field() == "caption"

        # Without span target but with text field
        config2 = {
            "instance_display": {
                "fields": [
                    {"key": "text", "type": "text"}
                ]
            }
        }
        renderer2 = InstanceDisplayRenderer(config2)
        assert renderer2.get_primary_text_field() == "text"

        # No text fields
        config3 = {
            "instance_display": {
                "fields": [
                    {"key": "image", "type": "image"}
                ]
            }
        }
        renderer3 = InstanceDisplayRenderer(config3)
        assert renderer3.get_primary_text_field() is None


class TestGetInstanceDisplayRenderer:
    """Tests for the factory function."""

    def test_returns_renderer(self):
        """Test that get_instance_display_renderer returns a renderer."""
        config = {"instance_display": {"fields": [{"key": "x", "type": "text"}]}}
        renderer = get_instance_display_renderer(config)
        assert isinstance(renderer, InstanceDisplayRenderer)
