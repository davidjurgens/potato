"""
Unit tests for ranking annotation schema.

Tests the ranking schema generator functionality including:
- HTML generation
- Ranking item elements
- Hidden input for storing order
- data-modified attribute
- Initial order as comma-separated labels
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.ranking import generate_ranking_layout


class TestRankingSchema:
    """Tests for ranking schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, keybindings = generate_ranking_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_rank" in html
        assert "Test" in html
        assert 'data-annotation-type="ranking"' in html

    def test_three_ranking_items(self):
        """Test that three labels produce three ranking-item divs."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert html.count('class="ranking-item"') == 3

    def test_ranking_order_input(self):
        """Test that a ranking-order-input hidden input is present."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert "ranking-order-input" in html

    def test_data_modified_true(self):
        """Test that the hidden input has data-modified='true'."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert 'data-modified="true"' in html

    def test_hidden_input_present(self):
        """Test that a hidden input element is present for storing order."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert 'type="hidden"' in html

    def test_initial_order_is_comma_separated_labels(self):
        """Test that the hidden input value is the comma-joined label list."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert 'value="A,B,C"' in html

    def test_all_labels_present(self):
        """Test that all label names appear in the HTML."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["Alpha", "Beta", "Gamma"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert "Alpha" in html
        assert "Beta" in html
        assert "Gamma" in html

    def test_labels_required(self):
        """Test that missing labels produces an error."""
        scheme = {
            "name": "test_rank_no_labels",
            "description": "Test",
            "annotation_type": "ranking",
        }

        html, _ = generate_ranking_layout(scheme)

        assert "annotation-error" in html

    def test_no_keybindings(self):
        """Test that ranking returns no keybindings."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        _, keybindings = generate_ranking_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that the hidden input carries annotation-input class."""
        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B"],
        }

        html, _ = generate_ranking_layout(scheme)

        assert "annotation-input" in html

    def test_dict_label_format(self):
        """Test that labels can be provided as dicts with a 'name' key."""
        scheme = {
            "name": "test_rank_dict",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": [{"name": "Item1"}, {"name": "Item2"}],
        }

        html, _ = generate_ranking_layout(scheme)

        assert "Item1" in html
        assert "Item2" in html


class TestRankingSchemaValidation:
    """Tests for ranking schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "ranking",
            "labels": ["A", "B"],
        }

        html, keybindings = generate_ranking_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "ranking",
            "labels": ["A", "B"],
        }

        html, keybindings = generate_ranking_layout(scheme)
        assert "annotation-error" in html


class TestRankingSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that ranking is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("ranking")

    def test_in_supported_types(self):
        """Test that ranking is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "ranking" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_rank",
            "description": "Test",
            "annotation_type": "ranking",
            "labels": ["A", "B", "C"],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestRankingConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that ranking is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "ranking",
            "name": "test",
            "description": "Test",
            "labels": ["A", "B"],
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
