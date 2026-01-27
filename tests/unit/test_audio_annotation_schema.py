"""
Unit tests for audio annotation schema.

Tests the audio_annotation schema generator functionality including:
- HTML generation
- Label processing
- Mode validation
- Keybinding generation
- Config validation
"""

import pytest
import json
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.audio_annotation import (
    generate_audio_annotation_layout,
    _process_labels,
    _generate_label_selector,
    _generate_keybindings,
    VALID_MODES,
    DEFAULT_COLORS,
)


class TestAudioAnnotationSchema:
    """Tests for audio annotation schema generation."""

    def test_basic_generation_label_mode(self):
        """Test basic schema generation with label mode."""
        scheme = {
            "name": "test_audio",
            "description": "Test audio annotation",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [
                {"name": "speech", "color": "#FF0000"},
                {"name": "music", "color": "#00FF00"},
            ],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_audio" in html
        assert "Test audio annotation" in html
        assert "speech" in html
        assert "music" in html

    def test_default_mode_is_label(self):
        """Test that default mode is 'label' when not specified."""
        scheme = {
            "name": "test_default_mode",
            "description": "Test default mode",
            "annotation_type": "audio_annotation",
            "labels": [{"name": "test_label"}],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        assert html is not None
        # Should have label buttons since default mode is label
        assert "label-btn" in html

    def test_questions_mode_requires_segment_schemes(self):
        """Test that questions mode requires segment_schemes."""
        scheme = {
            "name": "test_questions",
            "description": "Test questions mode",
            "annotation_type": "audio_annotation",
            "mode": "questions",
            # Missing segment_schemes
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_audio_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "segment_schemes" in html.lower()

    def test_questions_mode_with_segment_schemes(self):
        """Test questions mode with valid segment_schemes."""
        scheme = {
            "name": "test_questions_valid",
            "description": "Test questions mode valid",
            "annotation_type": "audio_annotation",
            "mode": "questions",
            "segment_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "segment_type",
                    "labels": ["intro", "main", "outro"],
                }
            ],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        assert html is not None
        assert "test_questions_valid" in html
        # Should have segment questions panel
        assert "segment-questions" in html

    def test_both_mode_requires_labels_and_segment_schemes(self):
        """Test that 'both' mode requires both labels and segment_schemes."""
        # Missing labels
        scheme1 = {
            "name": "test_both_missing_labels",
            "description": "Test both mode",
            "annotation_type": "audio_annotation",
            "mode": "both",
            "segment_schemes": [{"annotation_type": "radio", "name": "test", "labels": ["a", "b"]}],
        }

        html, _ = generate_audio_annotation_layout(scheme1)
        assert "annotation-error" in html

        # Missing segment_schemes
        scheme2 = {
            "name": "test_both_missing_schemes",
            "description": "Test both mode",
            "annotation_type": "audio_annotation",
            "mode": "both",
            "labels": [{"name": "label1"}],
        }

        html, _ = generate_audio_annotation_layout(scheme2)
        assert "annotation-error" in html

    def test_both_mode_valid(self):
        """Test 'both' mode with all required fields."""
        scheme = {
            "name": "test_both_valid",
            "description": "Test both mode valid",
            "annotation_type": "audio_annotation",
            "mode": "both",
            "labels": [
                {"name": "speech", "color": "#FF0000"},
                {"name": "music", "color": "#00FF00"},
            ],
            "segment_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "quality",
                    "labels": ["good", "bad"],
                }
            ],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        assert html is not None
        assert "test_both_valid" in html
        assert "label-btn" in html
        assert "segment-questions" in html

    def test_label_color_assignment(self):
        """Test that labels get colors assigned."""
        scheme = {
            "name": "color_test",
            "description": "Color assignment test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": ["label1", "label2", "label3"],  # String labels
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        assert "label1" in html
        assert "label2" in html
        assert "label3" in html
        # Should have color indicators
        assert "label-color-dot" in html

    def test_keybinding_generation(self):
        """Test keybinding generation for labels."""
        scheme = {
            "name": "keybind_test",
            "description": "Keybinding test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [
                {"name": "speech", "key_value": "1"},
                {"name": "music", "key_value": "2"},
            ],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)

        # Should have label keybindings
        keys = [k for k, _ in keybindings]
        assert "1" in keys
        assert "2" in keys

        # Should have common keybindings
        assert "Space" in keys
        assert "Enter" in keys
        assert "Del" in keys

    def test_zoom_controls_present(self):
        """Test that zoom controls are generated."""
        scheme = {
            "name": "zoom_test",
            "description": "Zoom test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
            "zoom_enabled": True,
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert 'data-action="zoom-in"' in html
        assert 'data-action="zoom-out"' in html
        assert 'data-action="zoom-fit"' in html

    def test_playback_controls_present(self):
        """Test that playback controls are generated."""
        scheme = {
            "name": "playback_test",
            "description": "Playback test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert 'data-action="play"' in html
        assert 'data-action="stop"' in html
        assert "time-display" in html

    def test_playback_rate_control(self):
        """Test playback rate control when enabled."""
        scheme = {
            "name": "rate_test",
            "description": "Rate test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
            "playback_rate_control": True,
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert "playback-rate-select" in html
        assert "0.5x" in html
        assert "2x" in html

    def test_segment_controls_present(self):
        """Test that segment controls are generated."""
        scheme = {
            "name": "segment_test",
            "description": "Segment test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert 'data-action="create-segment"' in html
        assert 'data-action="delete-segment"' in html
        assert "segment-count" in html

    def test_hidden_input_present(self):
        """Test that hidden input for data storage is present."""
        scheme = {
            "name": "input_test",
            "description": "Input test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert 'type="hidden"' in html
        assert 'name="input_test"' in html
        assert 'class="annotation-data-input"' in html

    def test_waveform_container_present(self):
        """Test that waveform container is generated."""
        scheme = {
            "name": "waveform_test",
            "description": "Waveform test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
        }

        html, _ = generate_audio_annotation_layout(scheme)

        assert "waveform-container" in html
        assert "overview-container" in html
        assert "segment-list" in html

    def test_invalid_mode_error(self):
        """Test error when invalid mode is specified."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "audio_annotation",
            "mode": "invalid_mode",
            "labels": [{"name": "test"}],
        }

        html, keybindings = generate_audio_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "invalid" in html.lower() or "mode" in html.lower()

    def test_missing_labels_label_mode_error(self):
        """Test error when labels are missing in label mode."""
        scheme = {
            "name": "error_test",
            "description": "Error test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            # Missing labels
        }

        html, keybindings = generate_audio_annotation_layout(scheme)
        assert "annotation-error" in html
        assert "labels" in html.lower()


class TestLabelProcessing:
    """Tests for label processing functionality."""

    def test_string_labels(self):
        """Test processing of string labels."""
        labels = ["speech", "music", "silence"]
        processed = _process_labels(labels)

        assert len(processed) == 3
        assert processed[0]["name"] == "speech"
        assert processed[1]["name"] == "music"
        assert processed[2]["name"] == "silence"
        # Should have colors assigned
        for label in processed:
            assert "color" in label
            assert label["color"].startswith("#")

    def test_dict_labels_with_color(self):
        """Test processing of dict labels with custom colors."""
        labels = [
            {"name": "speech", "color": "#FF0000"},
            {"name": "music", "color": "#00FF00"},
        ]
        processed = _process_labels(labels)

        assert processed[0]["color"] == "#FF0000"
        assert processed[1]["color"] == "#00FF00"

    def test_dict_labels_without_color(self):
        """Test processing of dict labels without colors (should get default)."""
        labels = [
            {"name": "speech"},
            {"name": "music"},
        ]
        processed = _process_labels(labels)

        # Should have default colors assigned
        for label in processed:
            assert "color" in label
            assert label["color"] in DEFAULT_COLORS

    def test_labels_with_key_values(self):
        """Test processing of labels with key_value shortcuts."""
        labels = [
            {"name": "speech", "key_value": "1"},
            {"name": "music", "key_value": "2"},
        ]
        processed = _process_labels(labels)

        assert processed[0]["key_value"] == "1"
        assert processed[1]["key_value"] == "2"

    def test_color_cycling(self):
        """Test that colors cycle through defaults for many labels."""
        labels = [f"label_{i}" for i in range(15)]
        processed = _process_labels(labels)

        assert len(processed) == 15
        # Colors should cycle
        assert processed[0]["color"] == processed[10]["color"]


class TestLabelSelector:
    """Tests for label selector generation."""

    def test_label_buttons(self):
        """Test label button generation."""
        labels = [
            {"name": "speech", "color": "#FF0000"},
            {"name": "music", "color": "#00FF00"},
        ]
        html = _generate_label_selector(labels)

        assert 'data-label="speech"' in html
        assert 'data-label="music"' in html
        assert 'data-color="#FF0000"' in html
        assert 'data-color="#00FF00"' in html

    def test_color_dots(self):
        """Test color dot indicators."""
        labels = [{"name": "test", "color": "#FF0000"}]
        html = _generate_label_selector(labels)

        assert "label-color-dot" in html
        assert "background-color: #FF0000" in html


class TestKeybindings:
    """Tests for keybinding generation."""

    def test_label_keybindings(self):
        """Test label keybindings."""
        labels = [
            {"name": "speech", "key_value": "1"},
            {"name": "music", "key_value": "2"},
        ]
        keybindings = _generate_keybindings(labels, "label")

        keys = dict(keybindings)
        assert "1" in keys
        assert "2" in keys
        assert "speech" in keys["1"]
        assert "music" in keys["2"]

    def test_common_keybindings(self):
        """Test common keybindings are included."""
        labels = [{"name": "test"}]
        keybindings = _generate_keybindings(labels, "label")

        keys = [k for k, _ in keybindings]
        assert "Space" in keys
        assert "Del" in keys
        assert "+/-" in keys
        assert "0" in keys
        assert "Enter" in keys


class TestConfigValidation:
    """Tests for config validation in config_module.py."""

    def test_valid_audio_annotation_config(self):
        """Test validation passes for valid config."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_mode_validation(self):
        """Test validation fails for invalid mode."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "audio_annotation",
            "mode": "invalid_mode",
            "labels": [{"name": "speech"}],
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "mode" in str(exc_info.value).lower()

    def test_missing_labels_validation_label_mode(self):
        """Test validation fails for missing labels in label mode."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            # Missing labels
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "labels" in str(exc_info.value).lower()

    def test_missing_segment_schemes_validation_questions_mode(self):
        """Test validation fails for missing segment_schemes in questions mode."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "audio_annotation",
            "mode": "questions",
            # Missing segment_schemes
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "segment_schemes" in str(exc_info.value).lower()

    def test_min_segments_validation(self):
        """Test validation for min_segments field."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "test",
            "description": "Test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "speech"}],
            "min_segments": -1,  # Invalid
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        assert "min_segments" in str(exc_info.value).lower()


class TestSchemaRegistry:
    """Tests for schema registry integration."""

    def test_audio_annotation_registered(self):
        """Test that audio_annotation is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("audio_annotation")

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "registry_test",
            "description": "Registry test",
            "annotation_type": "audio_annotation",
            "mode": "label",
            "labels": [{"name": "test"}],
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert "registry_test" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
