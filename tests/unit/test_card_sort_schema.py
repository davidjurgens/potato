"""
Unit tests for Card Sort annotation schema.

Tests the card sort schema generator functionality including:
- HTML generation in closed mode with groups
- Groups appear in HTML
- Open mode shows new group input
- Items field data attribute
- Hidden input for data storage
- Closed mode without groups validation
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.card_sort import generate_card_sort_layout


class TestCardSortSchema:
    """Tests for card sort schema generation."""

    def test_basic_generation_closed(self):
        """Test basic schema generation in closed mode with groups."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["Group A", "Group B", "Group C"],
        }

        html, keybindings = generate_card_sort_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_sort" in html
        assert 'data-annotation-type="card_sort"' in html

    def test_groups_appear_in_html(self):
        """Test that group names appear in the HTML."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["Positive", "Negative", "Neutral"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "Positive" in html
        assert "Negative" in html
        assert "Neutral" in html

    def test_group_containers(self):
        """Test that each group has its own container."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A", "B"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-group" in html
        assert "card-sort-group-header" in html
        assert "card-sort-group-items" in html

    def test_open_mode_new_group_input(self):
        """Test that open mode shows the new group input."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "open",
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-new-group" in html
        assert "card-sort-new-group-input" in html
        assert "+ Add Group" in html

    def test_closed_mode_no_new_group_input(self):
        """Test that closed mode does not show the new group input."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-new-group-input" not in html

    def test_items_field_attribute(self):
        """Test that items_field data attribute is set."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
            "items_field": "my_items",
        }

        html, _ = generate_card_sort_layout(scheme)

        assert 'data-items-field="my_items"' in html

    def test_default_items_field(self):
        """Test that default items_field is 'items'."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert 'data-items-field="items"' in html

    def test_hidden_input_for_data(self):
        """Test that a hidden input is present for data storage."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert 'type="hidden"' in html
        assert "card-sort-data-input" in html

    def test_annotation_input_class(self):
        """Test that inputs carry annotation-input class."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "annotation-input" in html

    def test_no_keybindings(self):
        """Test that card sort returns no keybindings."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        _, keybindings = generate_card_sort_layout(scheme)

        assert keybindings == []

    def test_source_items_area(self):
        """Test that source items area is present."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-source" in html
        assert "Drag items into groups" in html

    def test_layout_structure(self):
        """Test that the card sort layout structure is present."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-layout" in html
        assert "card-sort-groups" in html

    def test_group_count_display(self):
        """Test that group count span is present."""
        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "card-sort-group-count" in html

    def test_description_in_legend(self):
        """Test that description appears in the HTML."""
        scheme = {
            "name": "test_sort",
            "description": "Sort these items into categories",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, _ = generate_card_sort_layout(scheme)

        assert "Sort these items into categories" in html


class TestCardSortSchemaValidation:
    """Tests for card sort schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, keybindings = generate_card_sort_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A"],
        }

        html, keybindings = generate_card_sort_layout(scheme)
        assert "annotation-error" in html

    def test_closed_mode_missing_groups_raises_error(self):
        """Test that closed mode without groups raises ValueError."""
        scheme = {
            "name": "test_sort",
            "description": "Test",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": [],
        }

        # Empty groups in closed mode should raise ValueError via safe_generate_layout
        html, _ = generate_card_sort_layout(scheme)
        assert "annotation-error" in html


class TestCardSortSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that card_sort is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("card_sort")

    def test_in_supported_types(self):
        """Test that card_sort is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "card_sort" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_sort",
            "description": "Test Sort",
            "annotation_type": "card_sort",
            "mode": "closed",
            "groups": ["A", "B"],
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestCardSortConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that card_sort is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "card_sort",
            "name": "test",
            "description": "Test",
            "mode": "closed",
            "groups": ["A", "B"],
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_open_mode_accepted(self):
        """Test that open mode without groups is accepted."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "card_sort",
            "name": "test",
            "description": "Test",
            "mode": "open",
        }

        # Should not raise
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_closed_mode_without_groups_rejected(self):
        """Test that closed mode without groups is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "card_sort",
            "name": "test",
            "description": "Test",
            "mode": "closed",
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_closed_mode_empty_groups_rejected(self):
        """Test that closed mode with empty groups list is rejected."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "card_sort",
            "name": "test",
            "description": "Test",
            "mode": "closed",
            "groups": [],
        }

        with pytest.raises(ConfigValidationError):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_mode_rejected(self):
        """Test that invalid mode is rejected by config module."""
        from potato.server_utils.config_module import (
            validate_single_annotation_scheme,
            ConfigValidationError,
        )

        scheme = {
            "annotation_type": "card_sort",
            "name": "test",
            "description": "Test",
            "mode": "invalid_mode",
        }

        with pytest.raises(ConfigValidationError):
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
