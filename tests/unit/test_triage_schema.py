"""
Unit tests for triage annotation schema.

Tests the triage schema generator functionality including:
- HTML generation
- Output format (accept/reject/skip values)
- Keyboard binding generation
- Custom label support
- Config validation
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.triage import (
    generate_triage_layout,
    DEFAULT_ACCEPT_LABEL,
    DEFAULT_REJECT_LABEL,
    DEFAULT_SKIP_LABEL,
    DEFAULT_KEYBINDINGS,
)


class TestTriageSchema:
    """Tests for triage schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_triage",
            "description": "Test triage annotation",
            "annotation_type": "triage",
        }

        html, keybindings = generate_triage_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_triage" in html
        assert "Test triage annotation" in html
        assert 'data-annotation-type="triage"' in html

    def test_contains_three_buttons(self):
        """Test that HTML contains accept, reject, and skip buttons."""
        scheme = {
            "name": "triage_buttons",
            "description": "Button test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        assert 'class="triage-btn triage-accept"' in html
        assert 'class="triage-btn triage-reject"' in html
        assert 'class="triage-btn triage-skip"' in html
        assert 'data-value="accept"' in html
        assert 'data-value="reject"' in html
        assert 'data-value="skip"' in html

    def test_default_labels(self):
        """Test default button labels are used."""
        scheme = {
            "name": "default_labels",
            "description": "Default labels test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        assert DEFAULT_ACCEPT_LABEL in html
        assert DEFAULT_REJECT_LABEL in html
        assert DEFAULT_SKIP_LABEL in html

    def test_custom_labels(self):
        """Test custom button labels."""
        scheme = {
            "name": "custom_labels",
            "description": "Custom labels test",
            "annotation_type": "triage",
            "accept_label": "Keep It",
            "reject_label": "Trash It",
            "skip_label": "Maybe Later",
        }

        html, _ = generate_triage_layout(scheme)

        assert "Keep It" in html
        assert "Trash It" in html
        assert "Maybe Later" in html

    def test_keybindings_generated(self):
        """Test keyboard bindings are generated."""
        scheme = {
            "name": "keybind_test",
            "description": "Keybinding test",
            "annotation_type": "triage",
        }

        html, keybindings = generate_triage_layout(scheme)

        assert len(keybindings) == 3
        keys = [k for k, _ in keybindings]
        assert DEFAULT_KEYBINDINGS["accept"] in keys
        assert DEFAULT_KEYBINDINGS["reject"] in keys
        assert DEFAULT_KEYBINDINGS["skip"] in keys

    def test_custom_keybindings(self):
        """Test custom keyboard bindings."""
        scheme = {
            "name": "custom_keys",
            "description": "Custom keys test",
            "annotation_type": "triage",
            "accept_key": "y",
            "reject_key": "n",
            "skip_key": "u",
        }

        html, keybindings = generate_triage_layout(scheme)

        keys = [k for k, _ in keybindings]
        assert "y" in keys
        assert "n" in keys
        assert "u" in keys
        # Check HTML has the custom keys
        assert 'data-key="y"' in html
        assert 'data-key="n"' in html
        assert 'data-key="u"' in html

    def test_hidden_input_present(self):
        """Test that hidden input for storing decision is present."""
        scheme = {
            "name": "input_test",
            "description": "Input test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        assert 'type="hidden"' in html
        assert 'name="input_test:::decision"' in html
        assert 'class="annotation-input triage-input"' in html

    def test_auto_advance_attribute(self):
        """Test auto-advance data attribute is set."""
        # Default (true)
        scheme = {
            "name": "auto_default",
            "description": "Auto advance default",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)
        assert 'data-auto-advance="true"' in html

        # Explicitly false
        scheme_no_auto = {
            "name": "no_auto",
            "description": "No auto advance",
            "annotation_type": "triage",
            "auto_advance": False,
        }

        html2, _ = generate_triage_layout(scheme_no_auto)
        assert 'data-auto-advance="false"' in html2

    def test_progress_indicator_present(self):
        """Test progress indicator is present by default."""
        scheme = {
            "name": "progress_test",
            "description": "Progress test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        assert 'class="triage-progress"' in html
        assert 'class="triage-progress-bar"' in html
        assert 'class="triage-progress-fill"' in html

    def test_progress_indicator_hidden(self):
        """Test progress indicator can be hidden."""
        scheme = {
            "name": "no_progress",
            "description": "No progress test",
            "annotation_type": "triage",
            "show_progress": False,
        }

        html, _ = generate_triage_layout(scheme)

        assert 'class="triage-progress"' not in html

    def test_button_icons_present(self):
        """Test button icons are present."""
        scheme = {
            "name": "icons_test",
            "description": "Icons test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        # Check for icon spans
        assert 'class="triage-btn-icon"' in html

    def test_schema_name_escaping(self):
        """Test that schema name is properly escaped."""
        scheme = {
            "name": "test<script>alert('xss')</script>",
            "description": "XSS test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "test" in html

    def test_output_format_structure(self):
        """Test the structure is suitable for storing accept/reject/skip values."""
        scheme = {
            "name": "output_format",
            "description": "Output format test",
            "annotation_type": "triage",
        }

        html, _ = generate_triage_layout(scheme)

        # The hidden input should accept simple string values
        assert 'name="output_format:::decision"' in html
        assert 'label_name="decision"' in html
        # Values should be simple strings that can be easily filtered
        assert 'data-value="accept"' in html
        assert 'data-value="reject"' in html
        assert 'data-value="skip"' in html


class TestTriageSchemaValidation:
    """Tests for triage schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "triage",
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_triage_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "triage",
        }

        # safe_generate_layout catches errors and returns error HTML
        html, keybindings = generate_triage_layout(scheme)
        assert "annotation-error" in html


class TestTriageSchemaRegistry:
    """Tests for schema registry integration."""

    def test_triage_registered(self):
        """Test that triage is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("triage")

    def test_triage_in_supported_types(self):
        """Test that triage is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        supported = schema_registry.get_supported_types()
        assert "triage" in supported

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "registry_test",
            "description": "Registry test",
            "annotation_type": "triage",
        }

        html, keybindings = schema_registry.generate(scheme)

        assert html is not None
        assert "registry_test" in html
        assert len(keybindings) == 3

    def test_schema_metadata(self):
        """Test schema metadata is correct."""
        from potato.server_utils.schemas.registry import schema_registry

        schema_def = schema_registry.get("triage")
        assert schema_def is not None
        assert schema_def.name == "triage"
        assert schema_def.supports_keybindings is True
        assert "name" in schema_def.required_fields
        assert "description" in schema_def.required_fields
        assert "accept_label" in schema_def.optional_fields
        assert "reject_label" in schema_def.optional_fields
        assert "skip_label" in schema_def.optional_fields


class TestTriageConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_triage_in_valid_types(self):
        """Test that triage is in the config module valid_types."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "name": "valid_triage",
            "description": "Valid triage config",
            "annotation_type": "triage",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_type_still_rejected(self):
        """Test that invalid types are still rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "name": "invalid_type",
            "description": "Invalid type config",
            "annotation_type": "not_a_real_type",
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")
        # Error message lists valid types including triage
        assert "triage" in str(exc_info.value)
        assert "annotation_type" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
