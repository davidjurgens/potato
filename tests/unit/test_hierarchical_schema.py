"""
Unit tests for hierarchical_multiselect annotation schema.

Tests the hierarchical_multiselect schema generator functionality including:
- HTML generation
- Tree structure with checkboxes and toggles
- Taxonomy rendering (nested dicts and lists)
- Hidden input for selections
- Search box toggle
- Config validation
- Registry integration
"""

import pytest
import sys
import os

# Add the potato directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from potato.server_utils.schemas.hierarchical_multiselect import (
    generate_hierarchical_multiselect_layout,
)


class TestHierarchicalSchema:
    """Tests for hierarchical_multiselect schema generation."""

    def test_basic_generation(self):
        """Test basic schema generation with minimal config."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, keybindings = generate_hierarchical_multiselect_layout(scheme)

        assert html is not None
        assert isinstance(html, str)
        assert "test_hm" in html
        assert "Test" in html
        assert 'data-annotation-type="hierarchical_multiselect"' in html

    def test_checkboxes_present(self):
        """Test that hier-checkbox elements are present."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-checkbox" in html

    def test_toggles_present(self):
        """Test that hier-toggle elements are present for parent nodes."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-toggle" in html

    def test_tree_container_present(self):
        """Test that hier-tree container is present."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-tree" in html

    def test_hidden_selected_input_present(self):
        """Test that hier-selected-input hidden input is present."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-selected-input" in html
        assert 'type="hidden"' in html

    def test_taxonomy_labels_present(self):
        """Test that all taxonomy labels appear in the HTML."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "Science" in html
        assert "Physics" in html
        assert "QM" in html
        assert "Arts" in html
        assert "Music" in html

    def test_taxonomy_required(self):
        """Test that missing taxonomy produces an error."""
        scheme = {
            "name": "test_hm_no_tax",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "annotation-error" in html

    def test_search_box_shown_when_enabled(self):
        """Test that search box appears when show_search=True."""
        scheme = {
            "name": "test_hm_search",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
            "show_search": True,
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-search" in html

    def test_search_box_hidden_by_default(self):
        """Test that search box is not present when show_search is not set."""
        scheme = {
            "name": "test_hm_no_search",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "hier-search-input" not in html

    def test_no_keybindings(self):
        """Test that hierarchical_multiselect returns no keybindings."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
        }

        _, keybindings = generate_hierarchical_multiselect_layout(scheme)

        assert keybindings == []

    def test_annotation_input_class(self):
        """Test that the hidden input carries annotation-input class."""
        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "annotation-input" in html

    def test_flat_list_taxonomy(self):
        """Test that a flat list taxonomy renders correctly."""
        scheme = {
            "name": "test_hm_flat",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Category": ["Item1", "Item2", "Item3"]},
        }

        html, _ = generate_hierarchical_multiselect_layout(scheme)

        assert "Item1" in html
        assert "Item2" in html
        assert "Item3" in html


class TestHierarchicalSchemaValidation:
    """Tests for hierarchical_multiselect schema validation."""

    def test_missing_name_error(self):
        """Test error when name is missing."""
        scheme = {
            "description": "Missing name",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
        }

        html, keybindings = generate_hierarchical_multiselect_layout(scheme)
        assert "annotation-error" in html

    def test_missing_description_error(self):
        """Test error when description is missing."""
        scheme = {
            "name": "no_description",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"A": ["B"]},
        }

        html, keybindings = generate_hierarchical_multiselect_layout(scheme)
        assert "annotation-error" in html


class TestHierarchicalSchemaRegistry:
    """Tests for schema registry integration."""

    def test_registered(self):
        """Test that hierarchical_multiselect is registered in schema registry."""
        from potato.server_utils.schemas.registry import schema_registry

        assert schema_registry.is_registered("hierarchical_multiselect")

    def test_in_supported_types(self):
        """Test that hierarchical_multiselect is in the supported types list."""
        from potato.server_utils.schemas.registry import schema_registry

        assert "hierarchical_multiselect" in schema_registry.get_supported_types()

    def test_generate_via_registry(self):
        """Test generation through registry."""
        from potato.server_utils.schemas.registry import schema_registry

        scheme = {
            "name": "test_hm",
            "description": "Test",
            "annotation_type": "hierarchical_multiselect",
            "taxonomy": {"Science": {"Physics": ["QM"]}, "Arts": ["Music"]},
        }

        html, kb = schema_registry.generate(scheme)

        assert html is not None
        assert len(html) > 0


class TestHierarchicalConfigModuleValidation:
    """Tests for config module validation integration."""

    def test_type_in_valid_types(self):
        """Test that hierarchical_multiselect is accepted by config module validation."""
        from potato.server_utils.config_module import validate_single_annotation_scheme

        scheme = {
            "annotation_type": "hierarchical_multiselect",
            "name": "test",
            "description": "Test",
            "taxonomy": {"A": ["B"]},
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
