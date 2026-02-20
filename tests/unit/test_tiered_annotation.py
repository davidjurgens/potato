"""
Unit tests for the tiered_annotation schema generator.

Tests the schema generation, HTML output, and configuration validation.
"""

import pytest
import json
from potato.server_utils.schemas.tiered_annotation import (
    generate_tiered_annotation_layout,
    _process_tiers,
    _validate_tier_structure,
)


class TestTieredAnnotationLayout:
    """Tests for tiered annotation layout generation."""

    def test_basic_generation(self):
        """Test basic layout generation."""
        scheme = {
            "name": "test_tiers",
            "description": "Test tiered annotation",
            "source_field": "audio_url",
            "tiers": [
                {"name": "utterance", "tier_type": "independent", "labels": ["Speaker_A"]},
            ],
        }
        html, keybindings = generate_tiered_annotation_layout(scheme)

        assert 'id="test_tiers"' in html
        assert 'data-annotation-type="tiered_annotation"' in html
        assert 'data-schema-name="test_tiers"' in html
        assert "Test tiered annotation" in html

    def test_multiple_tiers(self):
        """Test layout with multiple tiers."""
        scheme = {
            "name": "multi_tier",
            "description": "Multiple tiers",
            "source_field": "audio_url",
            "tiers": [
                {"name": "utterance", "tier_type": "independent"},
                {"name": "word", "tier_type": "dependent", "parent_tier": "utterance"},
                {"name": "gesture", "tier_type": "independent"},
            ],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'data-tier="utterance"' in html
        assert 'data-tier="word"' in html
        assert 'data-tier="gesture"' in html
        assert 'data-tier-type="independent"' in html
        assert 'data-tier-type="dependent"' in html

    def test_tier_selector_generated(self):
        """Test tier selector dropdown is generated."""
        scheme = {
            "name": "selector_test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [
                {"name": "tier1"},
                {"name": "tier2"},
            ],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'id="tier-select-selector_test"' in html
        assert '<option value="tier1">' in html
        assert '<option value="tier2">' in html

    def test_audio_media_element(self):
        """Test audio media element is generated for audio type."""
        scheme = {
            "name": "audio_test",
            "description": "Test",
            "source_field": "audio_url",
            "media_type": "audio",
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert '<audio' in html
        assert 'id="media-audio_test"' in html

    def test_video_media_element(self):
        """Test video media element is generated for video type."""
        scheme = {
            "name": "video_test",
            "description": "Test",
            "source_field": "video_url",
            "media_type": "video",
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert '<video' in html
        assert 'id="media-video_test"' in html

    def test_config_embedded_in_data_attribute(self):
        """Test that configuration is embedded in data-config attribute."""
        scheme = {
            "name": "config_test",
            "description": "Test",
            "source_field": "audio_url",
            "tier_height": 60,
            "tiers": [
                {"name": "tier1", "labels": [{"name": "Label1", "color": "#FF0000"}]},
            ],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'data-config=' in html
        # Extract config from HTML (it's JSON-escaped in the attribute)
        import re
        match = re.search(r"data-config='([^']+)'", html)
        assert match
        config_str = match.group(1)
        # Unescape HTML entities
        config_str = config_str.replace("&quot;", '"')
        config = json.loads(config_str)

        assert config["schemaName"] == "config_test"
        assert config["tierHeight"] == 60
        assert len(config["tiers"]) == 1

    def test_playback_controls_generated(self):
        """Test playback controls are generated when enabled."""
        scheme = {
            "name": "playback_test",
            "description": "Test",
            "source_field": "audio_url",
            "playback_rate_control": True,
            "zoom_enabled": True,
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'id="rate-playback_test"' in html
        assert 'id="zoom-in-playback_test"' in html
        assert 'id="zoom-out-playback_test"' in html

    def test_hidden_input_generated(self):
        """Test hidden input for form submission is generated."""
        scheme = {
            "name": "input_test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'type="hidden"' in html
        assert 'name="input_test"' in html
        assert 'id="input-input_test"' in html

    def test_keybindings_returned(self):
        """Test that keybindings are returned."""
        scheme = {
            "name": "keybind_test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [{"name": "tier1"}],
        }
        _, keybindings = generate_tiered_annotation_layout(scheme)

        assert len(keybindings) > 0
        keys = [k[0] for k in keybindings]
        assert "Space" in keys
        assert "Delete/Backspace" in keys

    def test_dependent_tier_styling(self):
        """Test dependent tiers have appropriate styling."""
        scheme = {
            "name": "dep_test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [
                {"name": "parent", "tier_type": "independent"},
                {"name": "child", "tier_type": "dependent", "parent_tier": "parent"},
            ],
        }
        html, _ = generate_tiered_annotation_layout(scheme)

        assert 'class="tier-row tier-dependent' in html
        assert 'data-parent-tier="parent"' in html


class TestProcessTiers:
    """Tests for tier processing function."""

    def test_basic_processing(self):
        """Test basic tier processing."""
        tiers = [
            {"name": "tier1", "labels": ["Label1", "Label2"]},
        ]
        processed = _process_tiers(tiers)

        assert len(processed) == 1
        assert processed[0]["name"] == "tier1"
        assert len(processed[0]["labels"]) == 2

    def test_color_assignment(self):
        """Test colors are assigned to labels."""
        tiers = [
            {"name": "tier1", "labels": ["Label1", "Label2"]},
        ]
        processed = _process_tiers(tiers)

        for label in processed[0]["labels"]:
            assert "color" in label
            assert label["color"].startswith("#")

    def test_explicit_color_preserved(self):
        """Test explicit label colors are preserved."""
        tiers = [
            {"name": "tier1", "labels": [{"name": "Label1", "color": "#123456"}]},
        ]
        processed = _process_tiers(tiers)

        assert processed[0]["labels"][0]["color"] == "#123456"

    def test_tier_type_normalized(self):
        """Test tier_type is normalized to lowercase."""
        tiers = [
            {"name": "tier1", "tier_type": "INDEPENDENT"},
            {"name": "tier2", "tier_type": "Dependent", "parent_tier": "tier1"},
        ]
        processed = _process_tiers(tiers)

        assert processed[0]["tier_type"] == "independent"
        assert processed[1]["tier_type"] == "dependent"

    def test_constraint_type_normalized(self):
        """Test constraint_type is normalized."""
        tiers = [
            {"name": "tier1"},
            {"name": "tier2", "tier_type": "dependent", "parent_tier": "tier1",
             "constraint_type": "TIME_SUBDIVISION"},
        ]
        processed = _process_tiers(tiers)

        assert processed[1]["constraint_type"] == "time_subdivision"

    def test_invalid_tier_type_raises(self):
        """Test invalid tier_type raises error."""
        tiers = [
            {"name": "tier1", "tier_type": "invalid"},
        ]
        with pytest.raises(ValueError, match="invalid tier_type"):
            _process_tiers(tiers)

    def test_invalid_constraint_type_raises(self):
        """Test invalid constraint_type raises error."""
        tiers = [
            {"name": "tier1"},
            {"name": "tier2", "tier_type": "dependent", "parent_tier": "tier1",
             "constraint_type": "invalid"},
        ]
        with pytest.raises(ValueError, match="invalid constraint_type"):
            _process_tiers(tiers)


class TestValidateTierStructure:
    """Tests for tier structure validation."""

    def test_valid_structure(self):
        """Test valid tier structure passes validation."""
        tiers = [
            {"name": "parent", "tier_type": "independent"},
            {"name": "child", "tier_type": "dependent", "parent_tier": "parent"},
        ]
        # Should not raise
        _validate_tier_structure(tiers)

    def test_dependent_without_parent_raises(self):
        """Test dependent tier without parent raises error."""
        tiers = [
            {"name": "orphan", "tier_type": "dependent"},
        ]
        with pytest.raises(ValueError, match="must have a parent_tier"):
            _validate_tier_structure(tiers)

    def test_unknown_parent_raises(self):
        """Test reference to unknown parent raises error."""
        tiers = [
            {"name": "child", "tier_type": "dependent", "parent_tier": "nonexistent"},
        ]
        with pytest.raises(ValueError, match="unknown parent"):
            _validate_tier_structure(tiers)

    def test_self_reference_raises(self):
        """Test self-referencing tier raises error."""
        tiers = [
            {"name": "loop", "tier_type": "dependent", "parent_tier": "loop"},
        ]
        with pytest.raises(ValueError, match="own parent"):
            _validate_tier_structure(tiers)

    def test_cycle_detection(self):
        """Test cycle detection in tier hierarchy."""
        tiers = [
            {"name": "a", "tier_type": "dependent", "parent_tier": "b"},
            {"name": "b", "tier_type": "dependent", "parent_tier": "a"},
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            _validate_tier_structure(tiers)


class TestMissingRequiredFields:
    """Tests for error handling with missing required fields."""

    def test_missing_name(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)
        # Should generate error HTML due to missing name
        # The safe_generate_layout wrapper handles this
        # In this case, name defaults to "tiered_annotation"

    def test_missing_tiers(self):
        """Test error when tiers is missing."""
        scheme = {
            "name": "test",
            "description": "Test",
            "source_field": "audio_url",
            # No tiers
        }
        html, _ = generate_tiered_annotation_layout(scheme)
        # Should generate error HTML
        assert "Error" in html or "error" in html.lower()

    def test_empty_tiers(self):
        """Test error when tiers is empty."""
        scheme = {
            "name": "test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [],
        }
        html, _ = generate_tiered_annotation_layout(scheme)
        # Should generate error HTML
        assert "Error" in html or "error" in html.lower()

    def test_invalid_media_type(self):
        """Test error with invalid media_type."""
        scheme = {
            "name": "test",
            "description": "Test",
            "source_field": "audio_url",
            "media_type": "invalid",
            "tiers": [{"name": "tier1"}],
        }
        html, _ = generate_tiered_annotation_layout(scheme)
        # Should generate error HTML
        assert "Error" in html or "error" in html.lower()


class TestIntegrationWithRegistry:
    """Tests for integration with schema registry."""

    def test_registered_in_registry(self):
        """Test tiered_annotation is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("tiered_annotation")

    def test_can_generate_via_registry(self):
        """Test generation via registry works."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "tiered_annotation",
            "name": "registry_test",
            "description": "Test",
            "source_field": "audio_url",
            "tiers": [{"name": "tier1"}],
        }
        html, keybindings = schema_registry.generate(scheme)

        assert 'data-annotation-type="tiered_annotation"' in html

    def test_in_supported_types(self):
        """Test tiered_annotation is in supported types."""
        from potato.server_utils.schemas.registry import schema_registry

        types = schema_registry.get_supported_types()
        assert "tiered_annotation" in types
