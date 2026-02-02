"""
Tests for schema registry integration.

These tests verify that:
1. All annotation types in config_module are registered in the schema registry
2. The front_end module uses the schema registry (not a hardcoded dict)
3. Each registered schema type can generate valid HTML
"""

import pytest


class TestSchemaRegistryCompleteness:
    """Test that the schema registry contains all expected annotation types."""

    def test_all_config_types_registered(self):
        """All annotation types in config_module.valid_types should be in registry."""
        from potato.server_utils.schemas.registry import schema_registry

        # Valid types from config_module.py (line 275)
        config_valid_types = [
            'radio', 'multiselect', 'likert', 'text', 'slider', 'span',
            'select', 'number', 'multirate', 'pure_display', 'video',
            'image_annotation', 'audio_annotation', 'video_annotation', 'span_link'
        ]

        registry_types = schema_registry.get_supported_types()

        for annotation_type in config_valid_types:
            assert annotation_type in registry_types, \
                f"Annotation type '{annotation_type}' is in config_module.valid_types but not in schema registry"

    def test_registry_types_match_config_types(self):
        """Schema registry should not have extra types not in config_module."""
        from potato.server_utils.schemas.registry import schema_registry

        config_valid_types = [
            'radio', 'multiselect', 'likert', 'text', 'slider', 'span',
            'select', 'number', 'multirate', 'pure_display', 'video',
            'image_annotation', 'audio_annotation', 'video_annotation', 'span_link'
        ]

        registry_types = schema_registry.get_supported_types()

        for registry_type in registry_types:
            assert registry_type in config_valid_types, \
                f"Schema registry has type '{registry_type}' not in config_module.valid_types"


class TestSchemaGeneration:
    """Test that each schema type can generate HTML."""

    def test_radio_generates_html(self):
        """Radio annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "radio",
            "name": "test_radio",
            "description": "Test radio",
            "labels": [
                {"name": "Option A", "key_value": "1"},
                {"name": "Option B", "key_value": "2"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0
        assert "test_radio" in html or "Option A" in html

    def test_multiselect_generates_html(self):
        """Multiselect annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "multiselect",
            "name": "test_multiselect",
            "description": "Test multiselect",
            "labels": ["Option A", "Option B"]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_likert_generates_html(self):
        """Likert annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "likert",
            "name": "test_likert",
            "description": "Test likert",
            "size": 5,
            "min_label": "Bad",
            "max_label": "Good"
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_text_generates_html(self):
        """Text annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "text",
            "name": "test_text",
            "description": "Test text input"
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_slider_generates_html(self):
        """Slider annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "slider",
            "name": "test_slider",
            "description": "Test slider",
            "min": 0,
            "max": 100
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_span_generates_html(self):
        """Span annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "span",
            "name": "test_span",
            "description": "Test span",
            "labels": ["Person", "Location", "Organization"]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_audio_annotation_generates_html(self):
        """Audio annotation type should generate valid HTML.

        This was a bug: front_end.py had a hardcoded dict that didn't include
        audio_annotation, so it would fail with 'unsupported annotation type'.
        """
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test_audio",
            "description": "Test audio annotation",
            "mode": "label",
            "labels": [
                {"name": "Speech", "color": "#4ECDC4"},
                {"name": "Music", "color": "#FF6B6B"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_image_annotation_generates_html(self):
        """Image annotation type should generate valid HTML.

        This was a bug: front_end.py had a hardcoded dict that didn't include
        image_annotation, so it would fail with 'unsupported annotation type'.
        """
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "image_annotation",
            "name": "test_image",
            "description": "Test image annotation",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "Person", "color": "#FF6B6B"},
                {"name": "Vehicle", "color": "#4ECDC4"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0

    def test_video_annotation_generates_html(self):
        """Video annotation type should generate valid HTML."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "video_annotation",
            "name": "test_video",
            "description": "Test video annotation",
            "mode": "segment",
            "labels": [
                {"name": "Intro", "color": "#4ECDC4"},
                {"name": "Content", "color": "#FF6B6B"}
            ]
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestSchemaRegistryErrors:
    """Test error handling in schema registry."""

    def test_unknown_type_raises_valueerror(self):
        """Unknown annotation type should raise ValueError with helpful message."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "unknown_type",
            "name": "test",
            "description": "Test"
        }

        with pytest.raises(ValueError) as exc_info:
            schema_registry.generate(scheme)

        assert "unknown_type" in str(exc_info.value)
        assert "Unsupported annotation type" in str(exc_info.value)

    def test_missing_annotation_type_raises_valueerror(self):
        """Missing annotation_type should raise ValueError."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test",
            "description": "Test"
        }

        with pytest.raises(ValueError) as exc_info:
            schema_registry.generate(scheme)

        assert "annotation_type" in str(exc_info.value)


class TestFrontEndIntegration:
    """Test that front_end.py uses the schema registry."""

    def test_generate_schematic_uses_registry(self):
        """front_end.generate_schematic should use schema_registry.generate."""
        from potato.server_utils.front_end import generate_schematic
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "radio",
            "name": "test",
            "description": "Test",
            "labels": ["A", "B"]
        }

        # Both should produce the same result
        front_end_result = generate_schematic(scheme)
        registry_result = schema_registry.generate(scheme)

        assert front_end_result[0] == registry_result[0], \
            "front_end.generate_schematic should produce same HTML as schema_registry.generate"

    def test_front_end_handles_audio_annotation(self):
        """front_end.generate_schematic should handle audio_annotation type.

        This was the bug: the hardcoded dict didn't include audio_annotation.
        """
        from potato.server_utils.front_end import generate_schematic

        scheme = {
            "annotation_type": "audio_annotation",
            "name": "test",
            "description": "Test",
            "mode": "label",
            "labels": [{"name": "Label1", "color": "#000"}]
        }

        # This should not raise an exception
        html, keybindings = generate_schematic(scheme)
        assert html is not None

    def test_front_end_handles_image_annotation(self):
        """front_end.generate_schematic should handle image_annotation type.

        This was the bug: the hardcoded dict didn't include image_annotation.
        """
        from potato.server_utils.front_end import generate_schematic

        scheme = {
            "annotation_type": "image_annotation",
            "name": "test",
            "description": "Test",
            "tools": ["bbox"],
            "labels": [{"name": "Label1", "color": "#000"}]
        }

        # This should not raise an exception
        html, keybindings = generate_schematic(scheme)
        assert html is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
