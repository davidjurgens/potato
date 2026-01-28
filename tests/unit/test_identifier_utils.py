"""
Tests for identifier_utils.py - the core function that generates form element identifiers.

These tests verify that the generate_element_identifier function produces correct
name and id attributes for different element types, which is critical for proper
form behavior (radio mutual exclusivity, checkbox independence, etc.)
"""

import pytest
import sys
import os

# Add potato to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'potato'))

from server_utils.schemas.identifier_utils import (
    generate_element_identifier,
    escape_html_content,
    validate_schema_config,
    generate_validation_attribute,
)


class TestGenerateElementIdentifier:
    """Test the core identifier generation function."""

    def test_radio_element_uses_schema_name_only(self):
        """Radio elements should use schema name as name attr for mutual exclusivity.

        All radio buttons in a group share the same name, which makes them
        mutually exclusive - selecting one deselects others.
        """
        identifiers = generate_element_identifier("test_schema", "option1", "radio")

        # Name should be just the schema name (no label included)
        assert identifiers["name"] == "test_schema", \
            f"Radio name should be schema name only, got {identifiers['name']}"

        # ID should be unique (includes label)
        assert "option1" in identifiers["id"], \
            f"Radio ID should include label, got {identifiers['id']}"

    def test_radio_buttons_in_same_schema_share_name(self):
        """Multiple radio buttons in same schema should have identical names."""
        id1 = generate_element_identifier("sentiment", "positive", "radio")
        id2 = generate_element_identifier("sentiment", "negative", "radio")
        id3 = generate_element_identifier("sentiment", "neutral", "radio")

        # All should have same name
        assert id1["name"] == id2["name"] == id3["name"] == "sentiment", \
            f"Radio buttons should share name, got {id1['name']}, {id2['name']}, {id3['name']}"

        # But different IDs
        assert id1["id"] != id2["id"] != id3["id"], \
            "Radio buttons should have unique IDs"

    def test_checkbox_element_includes_label_in_name(self):
        """Checkbox elements should include label in name for independent selection.

        Unlike radio buttons, checkboxes should be independently selectable,
        which requires each to have a unique name.
        """
        identifiers = generate_element_identifier("colors", "red", "checkbox")

        # Name should include both schema and label
        assert "colors" in identifiers["name"], \
            f"Checkbox name should include schema, got {identifiers['name']}"
        assert "red" in identifiers["name"], \
            f"Checkbox name should include label, got {identifiers['name']}"

    def test_checkboxes_have_unique_names(self):
        """Multiple checkboxes in same schema should have different names."""
        id1 = generate_element_identifier("colors", "red", "checkbox")
        id2 = generate_element_identifier("colors", "blue", "checkbox")
        id3 = generate_element_identifier("colors", "green", "checkbox")

        # All should have different names
        names = {id1["name"], id2["name"], id3["name"]}
        assert len(names) == 3, \
            f"Checkboxes should have unique names, got {names}"

    def test_multirate_element_includes_item_in_name(self):
        """Multirate elements should include item name in name attr.

        Each row in multirate needs its own radio group, so the item/option
        must be part of the name to create independent groups.
        """
        identifiers = generate_element_identifier("ratings", "quality", "multirate")

        # Name should include both schema and item
        assert "ratings" in identifiers["name"], \
            f"Multirate name should include schema, got {identifiers['name']}"
        assert "quality" in identifiers["name"], \
            f"Multirate name should include item, got {identifiers['name']}"

    def test_multirate_rows_have_unique_names(self):
        """Different rows in multirate should have different radio group names."""
        id1 = generate_element_identifier("ratings", "quality", "multirate")
        id2 = generate_element_identifier("ratings", "speed", "multirate")
        id3 = generate_element_identifier("ratings", "value", "multirate")

        # All should have different names
        names = {id1["name"], id2["name"], id3["name"]}
        assert len(names) == 3, \
            f"Multirate rows should have unique names, got {names}"

    def test_default_element_type_includes_label(self):
        """Default element type should include label in name."""
        identifiers = generate_element_identifier("schema", "label", "default")

        assert "label" in identifiers["name"], \
            f"Default type should include label in name, got {identifiers['name']}"

    def test_identifier_returns_all_required_fields(self):
        """Identifier should return id, name, schema, and label_name."""
        identifiers = generate_element_identifier("test", "option", "radio")

        assert "id" in identifiers, "Missing 'id' field"
        assert "name" in identifiers, "Missing 'name' field"
        assert "schema" in identifiers, "Missing 'schema' field"
        assert "label_name" in identifiers, "Missing 'label_name' field"

    def test_special_characters_in_schema_name_are_escaped(self):
        """Schema names with special characters should be escaped."""
        identifiers = generate_element_identifier("test<script>", "option", "radio")

        # Should not contain raw < or > characters
        assert "<" not in identifiers["name"], "Name should escape special chars"
        assert ">" not in identifiers["name"], "Name should escape special chars"

    def test_special_characters_in_label_are_escaped(self):
        """Labels with special characters should be escaped."""
        identifiers = generate_element_identifier("schema", "opt<ion>", "checkbox")

        assert "<" not in identifiers["name"], "Name should escape special chars"
        assert ">" not in identifiers["name"], "Name should escape special chars"


class TestEscapeHtmlContent:
    """Test HTML escaping function."""

    def test_escapes_angle_brackets(self):
        """Angle brackets should be escaped."""
        result = escape_html_content("<script>alert('xss')</script>")
        assert "<" not in result
        assert ">" not in result
        assert "&lt;" in result
        assert "&gt;" in result

    def test_escapes_ampersand(self):
        """Ampersand should be escaped."""
        result = escape_html_content("a & b")
        assert "&amp;" in result

    def test_escapes_quotes(self):
        """Quotes should be escaped."""
        result = escape_html_content('test "quoted" text')
        assert '"' not in result or "&quot;" in result

    def test_empty_string_returns_empty(self):
        """Empty string should return empty string."""
        assert escape_html_content("") == ""

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert escape_html_content(None) == ""


class TestValidateSchemaConfig:
    """Test schema configuration validation."""

    def test_valid_schema_passes(self):
        """Valid schema should pass validation."""
        schema = {
            "name": "test",
            "description": "Test description",
            "labels": ["a", "b", "c"]
        }
        assert validate_schema_config(schema) is True

    def test_missing_name_raises(self):
        """Schema without name should raise error."""
        schema = {
            "description": "Test"
        }
        with pytest.raises(ValueError, match="name"):
            validate_schema_config(schema)

    def test_missing_description_raises(self):
        """Schema without description should raise error."""
        schema = {
            "name": "test"
        }
        with pytest.raises(ValueError, match="description"):
            validate_schema_config(schema)

    def test_empty_name_raises(self):
        """Schema with empty name should raise error."""
        schema = {
            "name": "",
            "description": "Test"
        }
        with pytest.raises(ValueError, match="empty"):
            validate_schema_config(schema)

    def test_duplicate_labels_raises(self):
        """Schema with duplicate labels should raise error."""
        schema = {
            "name": "test",
            "description": "Test",
            "labels": ["a", "b", "a"]  # Duplicate 'a'
        }
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            validate_schema_config(schema)

    def test_empty_label_raises(self):
        """Schema with empty label should raise error."""
        schema = {
            "name": "test",
            "description": "Test",
            "labels": ["a", "", "c"]  # Empty label
        }
        with pytest.raises(ValueError, match="empty"):
            validate_schema_config(schema)


class TestGenerateValidationAttribute:
    """Test validation attribute generation."""

    def test_required_returns_required(self):
        """Schema with required=True should return 'required'."""
        schema = {
            "name": "test",
            "description": "Test",
            "label_requirement": {"required": True}
        }
        assert generate_validation_attribute(schema) == "required"

    def test_no_requirement_returns_empty(self):
        """Schema without requirements should return empty string."""
        schema = {
            "name": "test",
            "description": "Test"
        }
        assert generate_validation_attribute(schema) == ""

    def test_required_false_returns_empty(self):
        """Schema with required=False should return empty string."""
        schema = {
            "name": "test",
            "description": "Test",
            "label_requirement": {"required": False}
        }
        assert generate_validation_attribute(schema) == ""
