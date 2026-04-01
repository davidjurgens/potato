"""
Unit tests for Extractive QA annotation schema.

Tests the extractive QA schema generator functionality including:
- HTML generation
- Question/passage field data attributes
- Unanswerable button toggle
- Custom highlight color
- Hidden input for data storage
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.extractive_qa import (
    generate_extractive_qa_layout,
    DEFAULT_HIGHLIGHT_COLOR,
    DEFAULT_ALLOW_UNANSWERABLE,
)


class TestExtractiveQaSchema:
    """Tests for extractive QA schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, keybindings = generate_extractive_qa_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_eqa" in html
        assert 'data-annotation-type="extractive_qa"' in html

    def test_question_field_attribute(self):
        """Test that question_field data attribute is set."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
            "question_field": "my_question",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert 'data-question-field="my_question"' in html

    def test_passage_field_attribute(self):
        """Test that passage_field data attribute is set."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
            "passage_field": "my_passage",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert 'data-passage-field="my_passage"' in html

    def test_default_question_field(self):
        """Test that default question_field is 'question'."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert 'data-question-field="question"' in html

    def test_allow_unanswerable_default(self):
        """Test that unanswerable button is shown by default."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert "Unanswerable" in html
        assert "eqa-unanswerable-btn" in html

    def test_allow_unanswerable_false(self):
        """Test that unanswerable button is hidden when disabled."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
            "allow_unanswerable": False,
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert "eqa-unanswerable-btn" not in html

    def test_custom_highlight_color(self):
        """Test that custom highlight color is rendered."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
            "highlight_color": "#FF0000",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert 'data-highlight-color="#FF0000"' in html

    def test_default_highlight_color(self):
        """Test that default highlight color is used."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert f'data-highlight-color="{DEFAULT_HIGHLIGHT_COLOR}"' in html

    def test_hidden_input_for_data(self):
        """Test that a hidden input is present for data storage."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert 'type="hidden"' in html
        assert "eqa-data-input" in html

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that extractive QA returns no keybindings."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        _, keybindings = generate_extractive_qa_layout(scheme)

        assert keybindings == []

    def test_answer_display_element(self):
        """Test that answer display area is present."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert "eqa-answer-display" in html
        assert "eqa-answer-text" in html

    def test_clear_button_present(self):
        """Test that clear selection button is present."""
        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, _ = generate_extractive_qa_layout(scheme)

        assert "Clear Selection" in html
        assert "eqa-clear-btn" in html

    def test_default_constants(self):
        """Test that default constants have expected values."""
        assert DEFAULT_HIGHLIGHT_COLOR == "#FFEB3B"
        assert DEFAULT_ALLOW_UNANSWERABLE is True


class TestExtractiveQaSchemaValidation:
    """Tests for extractive QA schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "extractive_qa",
        }

        html, keybindings = generate_extractive_qa_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "extractive_qa",
        }

        html, keybindings = generate_extractive_qa_layout(scheme)
        assert "annotation-error" in html


class TestExtractiveQaSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that extractive_qa is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("extractive_qa")

    def test_in_supported_types(self):
        """Test that extractive_qa is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "extractive_qa" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_eqa",
            "description": "Test QA",
            "annotation_type": "extractive_qa",
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestExtractiveQaConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that extractive_qa is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "extractive_qa",
            "name": "test",
            "description": "Test",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_type_rejected(self):
        """Test that invalid types are still rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "nonexistent_type",
            "name": "test",
            "description": "Test",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
