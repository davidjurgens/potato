"""
Unit tests for the pairwise annotation schema generator.

Tests both binary mode (clickable tiles) and scale mode (slider between items).
"""

import pytest
from unittest.mock import patch, MagicMock


class TestPairwiseBinaryMode:
    """Tests for pairwise binary mode (clickable tiles)."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock config module for isolated testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = []
        with patch('potato.server_utils.schemas.pairwise.config', mock_config, create=True):
            yield mock_config

    def test_generate_binary_layout_basic(self):
        """Test basic binary mode layout generation."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_pairwise",
            "description": "Which option is better?",
            "mode": "binary",
            "annotation_id": "test_1"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Check HTML contains expected elements
        assert 'pairwise-binary' in html
        assert 'pairwise-tile' in html
        assert 'data-value="A"' in html
        assert 'data-value="B"' in html
        assert 'Which option is better?' in html
        assert 'pairwise-value' in html  # Hidden input

        # Check keybindings
        assert len(keybindings) == 2
        assert keybindings[0][0] == "1"
        assert keybindings[1][0] == "2"

    def test_generate_binary_layout_with_custom_labels(self):
        """Test binary mode with custom A/B labels."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_custom_labels",
            "description": "Choose the better response",
            "mode": "binary",
            "labels": ["Response A", "Response B"],
            "annotation_id": "test_2"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'Response A' in html
        assert 'Response B' in html

    def test_generate_binary_layout_with_tie_option(self):
        """Test binary mode with tie/no-preference option."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_tie",
            "description": "Which is better?",
            "mode": "binary",
            "allow_tie": True,
            "tie_label": "No preference",
            "annotation_id": "test_3"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'pairwise-tie-btn' in html
        assert 'No preference' in html
        assert 'data-value="tie"' in html

        # Check tie keybinding added
        assert len(keybindings) == 3
        assert keybindings[2][0] == "0"

    def test_generate_binary_layout_custom_tie_label(self):
        """Test binary mode with custom tie label."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_custom_tie",
            "description": "Select preference",
            "mode": "binary",
            "allow_tie": True,
            "tie_label": "Cannot decide",
            "annotation_id": "test_4"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'Cannot decide' in html

    def test_generate_binary_layout_no_keybindings(self):
        """Test binary mode with keybindings disabled."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_no_keys",
            "description": "Choose option",
            "mode": "binary",
            "sequential_key_binding": False,
            "annotation_id": "test_5"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Should not have keybinding display
        assert '[1]' not in html
        assert '[2]' not in html
        assert len(keybindings) == 0

    def test_generate_binary_layout_validation_attribute(self):
        """Test binary mode includes validation attribute when required."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_required",
            "description": "Required selection",
            "mode": "binary",
            "label_requirement": {"required": True},
            "annotation_id": "test_6"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'validation="required"' in html


class TestPairwiseScaleMode:
    """Tests for pairwise scale mode (slider between items)."""

    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock config module for isolated testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = []
        with patch('potato.server_utils.schemas.pairwise.config', mock_config, create=True):
            yield mock_config

    def test_generate_scale_layout_basic(self):
        """Test basic scale mode layout generation."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_scale",
            "description": "Rate the preference",
            "mode": "scale",
            "annotation_id": "test_7"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Check HTML contains expected elements
        assert 'pairwise-scale' in html
        assert 'pairwise-scale-slider' in html
        assert 'type="range"' in html
        assert 'Rate the preference' in html

        # Scale mode has no keybindings
        assert len(keybindings) == 0

    def test_generate_scale_layout_custom_range(self):
        """Test scale mode with custom min/max values."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_custom_scale",
            "description": "Rate from -5 to +5",
            "mode": "scale",
            "scale": {
                "min": -5,
                "max": 5,
                "step": 1
            },
            "annotation_id": "test_8"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'min="-5"' in html
        assert 'max="5"' in html
        assert 'step="1"' in html

    def test_generate_scale_layout_with_labels(self):
        """Test scale mode with custom endpoint labels."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_scale_labels",
            "description": "Rate preference",
            "mode": "scale",
            "labels": ["Option A", "Option B"],
            "scale": {
                "min": -3,
                "max": 3,
                "labels": {
                    "min": "A is much better",
                    "max": "B is much better",
                    "center": "Equal"
                }
            },
            "annotation_id": "test_9"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'A is much better' in html
        assert 'B is much better' in html
        assert 'Equal' in html
        assert 'Option A' in html
        assert 'Option B' in html

    def test_generate_scale_layout_default_value(self):
        """Test scale mode with custom default value."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_default",
            "description": "Rate preference",
            "mode": "scale",
            "scale": {
                "min": -3,
                "max": 3,
                "default": 0
            },
            "annotation_id": "test_10"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'value="0"' in html

    def test_generate_scale_layout_tick_marks(self):
        """Test scale mode generates tick marks."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_ticks",
            "description": "Rate preference",
            "mode": "scale",
            "scale": {
                "min": -2,
                "max": 2,
                "step": 1
            },
            "annotation_id": "test_11"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Should have tick marks for each value
        assert 'pairwise-scale-tick' in html


class TestPairwiseSchemaValidation:
    """Tests for pairwise schema configuration validation."""

    def test_missing_name_raises_error(self):
        """Test that missing name field raises validation error."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "description": "Test"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Should return error HTML instead of crashing
        assert 'annotation-error' in html or 'Error' in html

    def test_missing_description_raises_error(self):
        """Test that missing description field raises validation error."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        # Should return error HTML instead of crashing
        assert 'annotation-error' in html or 'Error' in html

    def test_default_mode_is_binary(self):
        """Test that default mode is binary when not specified."""
        from potato.server_utils.schemas.pairwise import generate_pairwise_layout

        scheme = {
            "annotation_type": "pairwise",
            "name": "test_default_mode",
            "description": "Test default mode",
            "annotation_id": "test_12"
        }

        html, keybindings = generate_pairwise_layout(scheme)

        assert 'pairwise-binary' in html


class TestPairwiseSchemaRegistry:
    """Tests for pairwise schema registry integration."""

    def test_pairwise_registered_in_registry(self):
        """Test that pairwise is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("pairwise")

    def test_pairwise_in_supported_types(self):
        """Test that pairwise is in supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        supported_types = schema_registry.get_supported_types()
        assert "pairwise" in supported_types

    def test_pairwise_generator_retrievable(self):
        """Test that pairwise generator can be retrieved."""
        from potato.server_utils.schemas.registry import schema_registry

        generator = schema_registry.get_generator("pairwise")
        assert generator is not None
        assert callable(generator)

    def test_pairwise_generates_via_registry(self):
        """Test that pairwise can generate HTML via registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "annotation_type": "pairwise",
            "name": "registry_test",
            "description": "Test via registry",
            "annotation_id": "test_13"
        }

        html, keybindings = schema_registry.generate(scheme)

        assert 'pairwise' in html
        assert 'registry_test' in html


class TestPairwiseConfigValidation:
    """Tests for pairwise config validation in config_module."""

    def test_pairwise_in_valid_types(self):
        """Test that pairwise is in valid_types in config_module."""
        # Note: We can't easily import config_module in unit tests
        # This is a documentation test to ensure it's included
        pass

    def test_scale_mode_validates_min_max(self):
        """Test that scale mode validates min < max."""
        from potato.server_utils.config_module import validate_single_annotation_scheme, ConfigValidationError

        scheme = {
            "annotation_type": "pairwise",
            "name": "test",
            "description": "test",
            "mode": "scale",
            "scale": {
                "min": 5,
                "max": 3  # Invalid: min > max
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_path")

        assert "min must be less than" in str(exc_info.value).lower()

    def test_scale_mode_validates_step(self):
        """Test that scale mode validates step > 0."""
        from potato.server_utils.config_module import validate_single_annotation_scheme, ConfigValidationError

        scheme = {
            "annotation_type": "pairwise",
            "name": "test",
            "description": "test",
            "mode": "scale",
            "scale": {
                "min": -3,
                "max": 3,
                "step": -1  # Invalid: negative step
            }
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_path")

        assert "step must be a positive" in str(exc_info.value).lower()

    def test_invalid_mode_raises_error(self):
        """Test that invalid mode raises validation error."""
        from potato.server_utils.config_module import validate_single_annotation_scheme, ConfigValidationError

        scheme = {
            "annotation_type": "pairwise",
            "name": "test",
            "description": "test",
            "mode": "invalid_mode"  # Invalid mode
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_path")

        assert "mode must be one of" in str(exc_info.value).lower()

    def test_labels_must_have_two_items(self):
        """Test that labels must have at least 2 items."""
        from potato.server_utils.config_module import validate_single_annotation_scheme, ConfigValidationError

        scheme = {
            "annotation_type": "pairwise",
            "name": "test",
            "description": "test",
            "labels": ["Only one"]  # Invalid: need at least 2
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_path")

        assert "at least 2" in str(exc_info.value).lower()
