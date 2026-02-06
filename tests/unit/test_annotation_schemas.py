"""
Tests for specific annotation schema types and their rendering functionality.
Tests the front-end generation for each annotation type.
"""

import pytest
import json
import os
import tempfile
import shutil
from unittest.mock import patch, Mock

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

from server_utils.front_end import generate_schematic
from server_utils.schemas import (
    generate_multiselect_layout,
    generate_multirate_layout,
    generate_radio_layout,
    generate_span_layout,
    generate_likert_layout,
    generate_textbox_layout,
    generate_number_layout,
    generate_pure_display_layout,
    generate_select_layout,
    generate_slider_layout,
)

class TestAnnotationSchemas:
    """Test different annotation schema types and their HTML generation"""

    def test_likert_schema_generation(self):
        """Test likert scale schema HTML generation"""
        schema = {
            "annotation_type": "likert",
            "annotation_id": 0,
            "name": "awesomeness",
            "description": "How awesome is this?",
            "min_label": "Not Awesome",
            "max_label": "Completely Awesome",
            "size": 5,
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "awesomeness" in html_layout
        assert "How awesome is this?" in html_layout
        assert "Not Awesome" in html_layout
        assert "Completely Awesome" in html_layout

        # Check for radio buttons (likert uses radio buttons)
        assert "input" in html_layout
        assert "type=\"radio\"" in html_layout

        # Check keybindings
        assert len(keybindings) >= 5  # Should have keybindings for each scale point

    def test_multiselect_schema_generation(self):
        """Test multiselect (checkbox) schema HTML generation"""
        schema = {
            "annotation_type": "multiselect",
            "annotation_id": 0,
            "name": "favorite_color",
            "description": "What colors are mentioned in the text?",
            "labels": ["blue", "maize", "green", "white"],
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "favorite_color" in html_layout
        assert "What colors are mentioned in the text?" in html_layout
        assert "blue" in html_layout
        assert "maize" in html_layout
        assert "green" in html_layout
        assert "white" in html_layout

        # Check for checkboxes
        assert "input" in html_layout
        assert "type=\"checkbox\"" in html_layout

        # Check keybindings
        assert len(keybindings) >= 4  # Should have keybindings for each label

    def test_slider_schema_generation(self):
        """Test slider schema HTML generation"""
        schema = {
            "annotation_type": "slider",
            "annotation_id": 0,
            "name": "awesomeness",
            "description": "How awesome is this?",
            "min_value": 0,
            "max_value": 100,
            "starting_value": 50
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "awesomeness" in html_layout
        assert "How awesome is this?" in html_layout

        # Check for slider input
        assert "input" in html_layout
        assert "type=\"range\"" in html_layout
        assert "min=\"0\"" in html_layout
        assert "max=\"100\"" in html_layout
        assert "value=\"50\"" in html_layout

    def test_span_schema_generation(self):
        """Test span annotation schema HTML generation"""
        schema = {
            "annotation_type": "span",
            "annotation_id": 0,
            "name": "certainty",
            "description": "Highlight which phrases make the sentence more or less certain",
            "labels": ["certain", "uncertain"],
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "certainty" in html_layout
        assert "Highlight which phrases" in html_layout
        assert "certain" in html_layout
        assert "uncertain" in html_layout

        # Check for span annotation elements
        assert "span" in html_layout

        # Check keybindings
        assert len(keybindings) >= 2  # Should have keybindings for each label

    def test_radio_schema_generation(self):
        """Test radio button schema HTML generation"""
        schema = {
            "annotation_type": "radio",
            "annotation_id": 0,
            "name": "sentiment",
            "description": "What is the sentiment of this text?",
            "labels": ["positive", "negative", "neutral"],
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "sentiment" in html_layout
        assert "What is the sentiment of this text?" in html_layout
        assert "positive" in html_layout
        assert "negative" in html_layout
        assert "neutral" in html_layout

        # Check for radio buttons
        assert "input" in html_layout
        assert "type=\"radio\"" in html_layout

        # Check keybindings
        assert len(keybindings) >= 3  # Should have keybindings for each label

    def test_textbox_schema_generation(self):
        """Test text input schema HTML generation"""
        schema = {
            "annotation_type": "text",
            "annotation_id": 0,
            "name": "explanation",
            "description": "Please explain your reasoning"
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "explanation" in html_layout
        assert "Please explain your reasoning" in html_layout

        # Check for text input
        assert "input" in html_layout or "textarea" in html_layout
        assert "type=\"text\"" in html_layout or "textarea" in html_layout

    def test_multirate_schema_generation(self):
        """Test multirate schema HTML generation"""
        schema = {
            "annotation_type": "multirate",
            "annotation_id": 0,
            "name": "quality_ratings",
            "description": "Rate the quality of different aspects",
            "options": ["grammar", "clarity", "relevance"],  # Items to rate (rows)
            "labels": ["poor", "fair", "good", "excellent"]  # Rating scale (columns)
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "quality_ratings" in html_layout
        assert "Rate the quality of different aspects" in html_layout
        assert "grammar" in html_layout
        assert "clarity" in html_layout
        assert "relevance" in html_layout

        # Check for table structure (multirate uses tables)
        assert "table" in html_layout or "tr" in html_layout

    def test_multirate_unique_radio_groups(self):
        """Test that multirate generates unique radio group names for each option.

        This is critical: each row (option) must have its own radio group so that
        selecting a rating for one option doesn't deselect ratings for other options.
        Without unique names, all radio buttons would be mutually exclusive across
        the entire table, making it impossible to rate multiple items.
        """
        import re

        schema = {
            "annotation_type": "multirate",
            "annotation_id": 0,
            "name": "test_ratings",
            "description": "Test multirate radio groups",
            "options": ["item_a", "item_b", "item_c"],
            "labels": ["low", "medium", "high"]
        }

        html_layout, keybindings = generate_schematic(schema)

        # Extract all name attributes from radio inputs
        name_pattern = r'name="([^"]+)"'
        names = re.findall(name_pattern, html_layout)

        # Filter to only radio input names (should contain the schema name)
        radio_names = [n for n in names if "test_ratings" in n]

        # Each option should have its own unique name
        # With 3 options and 3 labels, we should have 9 radio buttons
        # but only 3 unique names (one per option/row)
        unique_names = set(radio_names)

        # Verify we have exactly 3 unique radio group names (one per option)
        assert len(unique_names) == 3, \
            f"Expected 3 unique radio group names (one per option), got {len(unique_names)}: {unique_names}"

        # Verify each option has its own name that includes the option identifier
        assert any("item_a" in name for name in unique_names), \
            "item_a should have its own radio group name"
        assert any("item_b" in name for name in unique_names), \
            "item_b should have its own radio group name"
        assert any("item_c" in name for name in unique_names), \
            "item_c should have its own radio group name"

        # Verify the names are NOT all the same (this was the original bug)
        assert len(unique_names) > 1, \
            "All radio buttons have the same name - this would make only one selection possible across the entire table!"

    def test_select_schema_generation(self):
        """Test select dropdown schema HTML generation"""
        schema = {
            "annotation_type": "select",
            "annotation_id": 0,
            "name": "category",
            "description": "Select the category",
            "labels": ["news", "opinion", "review", "other"]
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "category" in html_layout
        assert "Select the category" in html_layout
        assert "news" in html_layout
        assert "opinion" in html_layout
        assert "review" in html_layout
        assert "other" in html_layout

        # Check for select element
        assert "select" in html_layout or "option" in html_layout

    def test_number_schema_generation(self):
        """Test number input schema HTML generation"""
        schema = {
            "annotation_type": "number",
            "annotation_id": 0,
            "name": "score",
            "description": "Rate from 1-10",
            "min_value": 1,
            "max_value": 10
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "score" in html_layout
        assert "Rate from 1-10" in html_layout

        # Check for number input
        assert "input" in html_layout
        assert "type=\"number\"" in html_layout
        assert "min=\"1\"" in html_layout
        assert "max=\"10\"" in html_layout

    def test_pure_display_schema_generation(self):
        """Test pure display schema HTML generation"""
        schema = {
            "annotation_type": "pure_display",
            "annotation_id": 0,
            "name": "information",
            "description": "This is informational text only"
        }

        html_layout, keybindings = generate_schematic(schema)

        # Check that HTML contains expected elements
        assert "information" in html_layout
        assert "This is informational text only" in html_layout

        # Pure display should not have input elements
        assert "input" not in html_layout or "readonly" in html_layout

    def test_schema_validation(self):
        """Test that invalid schema types raise appropriate errors"""
        invalid_schema = {
            "annotation_type": "invalid_type",
            "name": "test",
            "description": "Test description"
        }

        with pytest.raises(Exception):
            generate_schematic(invalid_schema)

    def test_missing_required_fields(self):
        """Test that schemas with missing required fields are handled properly"""
        # Test schema missing name
        incomplete_schema = {
            "annotation_type": "likert",
            "annotation_id": 0,
            "description": "Test description"
        }

        # This should either raise an error or handle gracefully
        try:
            html_layout, keybindings = generate_schematic(incomplete_schema)
            # If it doesn't raise an error, check that it handles missing fields gracefully
            assert html_layout is not None
        except Exception as e:
            # It's also acceptable for it to raise an error for missing required fields
            assert "name" in str(e).lower() or "required" in str(e).lower()

    def test_keybinding_generation(self):
        """Test that keybindings are generated correctly for different schema types"""
        # Test likert with sequential key binding
        likert_schema = {
            "annotation_type": "likert",
            "annotation_id": 0,
            "name": "test",
            "description": "Test",
            "size": 5,
            "min_label": "Strongly Disagree",
            "max_label": "Strongly Agree",
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(likert_schema)

        # Should have keybindings for each scale point
        assert len(keybindings) >= 5

        # Test multiselect with sequential key binding
        multiselect_schema = {
            "annotation_type": "multiselect",
            "annotation_id": 0,
            "name": "test",
            "description": "Test",
            "labels": ["a", "b", "c"],
            "sequential_key_binding": True
        }

        html_layout, keybindings = generate_schematic(multiselect_schema)

        # Should have keybindings for each label
        assert len(keybindings) >= 3


class TestFormAttributeCorrectness:
    """Tests to verify form element attributes are correct for proper form behavior.

    These tests catch bugs like the multirate issue where all radio buttons
    shared one name attribute, breaking independent row selections.
    """

    def test_radio_shared_name_for_mutual_exclusivity(self):
        """All radio buttons in a radio schema must share same name for mutual exclusivity.

        Radio buttons with the same 'name' attribute are mutually exclusive -
        selecting one deselects others. This is the intended behavior for single-choice.
        """
        import re

        schema = {
            "annotation_type": "radio",
            "annotation_id": 0,
            "name": "sentiment",
            "description": "What is the sentiment?",
            "labels": ["positive", "negative", "neutral"]
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all standalone name attributes (not data-schema-name, label_name, etc.)
        # Use positive lookbehind for whitespace to match only standalone 'name' attributes
        names = re.findall(r'(?<=\s)name="([^"]+)"', html_layout)
        radio_names = [n for n in names if "sentiment" in n]

        # All radio buttons should have the SAME name for mutual exclusivity
        unique_names = set(radio_names)
        assert len(unique_names) == 1, \
            f"All radio buttons should share one name for mutual exclusivity, got {len(unique_names)}: {unique_names}"

        # Verify we have 3 radio buttons (one per option)
        assert len(radio_names) == 3, \
            f"Should have 3 radio buttons, got {len(radio_names)}"

    def test_multiselect_unique_names_for_independence(self):
        """Each checkbox in multiselect must have unique name for independent selection.

        Unlike radio buttons, checkboxes should be independently selectable.
        Each checkbox needs a unique 'name' attribute to achieve this.
        """
        import re

        schema = {
            "annotation_type": "multiselect",
            "annotation_id": 0,
            "name": "colors",
            "description": "Select colors",
            "labels": ["red", "blue", "green", "yellow"]
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all standalone name attributes (not data-schema-name, label_name, etc.)
        # Use positive lookbehind for whitespace to match only standalone 'name' attributes
        names = re.findall(r'(?<=\s)name="([^"]+)"', html_layout)
        checkbox_names = [n for n in names if "colors" in n]

        # Each checkbox should have a UNIQUE name
        unique_names = set(checkbox_names)
        assert len(unique_names) == 4, \
            f"Each checkbox should have unique name, got {len(unique_names)} unique names for 4 checkboxes: {unique_names}"

        # Verify each label is represented in a name
        for label in ["red", "blue", "green", "yellow"]:
            assert any(label in name for name in unique_names), \
                f"Label '{label}' should be included in a checkbox name"

    def test_likert_shared_name_for_mutual_exclusivity(self):
        """All likert scale points must share same name (like radio buttons).

        Likert scales use radio buttons internally, so all scale points
        should share the same name for mutual exclusivity.
        """
        import re

        schema = {
            "annotation_type": "likert",
            "annotation_id": 0,
            "name": "quality",
            "description": "Rate quality",
            "size": 5,
            "min_label": "Poor",
            "max_label": "Excellent"
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all standalone name attributes (not data-schema-name, label_name, etc.)
        # Use positive lookbehind for whitespace to match only standalone 'name' attributes
        names = re.findall(r'(?<=\s)name="([^"]+)"', html_layout)
        likert_names = [n for n in names if "quality" in n]

        # All scale points should have the SAME name
        unique_names = set(likert_names)
        assert len(unique_names) == 1, \
            f"All likert scale points should share one name, got {len(unique_names)}: {unique_names}"

        # Verify we have 5 radio buttons (one per scale point)
        assert len(likert_names) == 5, \
            f"Should have 5 scale points, got {len(likert_names)}"

    def test_select_has_name_attribute(self):
        """Select dropdown must have a name attribute for form submission."""
        import re

        schema = {
            "annotation_type": "select",
            "annotation_id": 0,
            "name": "category",
            "description": "Select category",
            "labels": ["A", "B", "C"]
        }

        html_layout, _ = generate_schematic(schema)

        # The select element should have a name attribute
        # Check for name attribute on select element
        assert 'name=' in html_layout, "Select element should have a name attribute"

        # Extract names and verify the schema name is used
        names = re.findall(r'name="([^"]+)"', html_layout)
        assert any("category" in n for n in names), \
            f"Select should have name containing 'category', got {names}"

    def test_slider_has_name_attribute(self):
        """Slider input must have a name attribute for form submission."""
        import re

        schema = {
            "annotation_type": "slider",
            "annotation_id": 0,
            "name": "rating",
            "description": "Rate this",
            "min_value": 0,
            "max_value": 100,
            "starting_value": 50
        }

        html_layout, _ = generate_schematic(schema)

        # The slider input should have a name attribute
        names = re.findall(r'name="([^"]+)"', html_layout)
        assert any("rating" in n for n in names), \
            f"Slider should have name containing 'rating', got {names}"

    def test_form_element_ids_are_unique(self):
        """All form elements with id must have unique values within a schema."""
        import re

        # Test with multiselect (has multiple elements)
        schema = {
            "annotation_type": "multiselect",
            "annotation_id": 0,
            "name": "items",
            "description": "Select items",
            "labels": ["apple", "banana", "cherry", "date"]
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all id attributes
        ids = re.findall(r'id="([^"]+)"', html_layout)

        # Filter to form-related ids (containing schema name)
        form_ids = [i for i in ids if "items" in i]

        # All IDs should be unique
        assert len(form_ids) == len(set(form_ids)), \
            f"Duplicate IDs found: {[i for i in form_ids if form_ids.count(i) > 1]}"

    def test_radio_values_are_distinct(self):
        """Radio button values must be distinct for proper selection tracking."""
        import re

        schema = {
            "annotation_type": "radio",
            "annotation_id": 0,
            "name": "choice",
            "description": "Choose one",
            "labels": ["option_a", "option_b", "option_c"]
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all value attributes from radio inputs
        values = re.findall(r'value="([^"]+)"', html_layout)

        # Filter to non-empty values that are likely radio values
        radio_values = [v for v in values if v and v != ""]

        # Values should be distinct
        assert len(radio_values) >= 3, f"Should have at least 3 values, got {radio_values}"
        # Check that we have distinct values (at least for the main options)
        unique_values = set(radio_values)
        assert len(unique_values) >= 3, \
            f"Radio values should be distinct, got {unique_values}"

    def test_multiple_radio_schemas_dont_interfere(self):
        """Radio groups from different schemas must have different names."""
        import re

        schema_a = {
            "annotation_type": "radio",
            "annotation_id": 0,
            "name": "sentiment",
            "description": "Sentiment",
            "labels": ["positive", "negative"]
        }

        schema_b = {
            "annotation_type": "radio",
            "annotation_id": 1,
            "name": "emotion",
            "description": "Emotion",
            "labels": ["happy", "sad"]
        }

        html_a, _ = generate_schematic(schema_a)
        html_b, _ = generate_schematic(schema_b)

        # Extract names from each schema
        names_a = set(re.findall(r'name="([^"]+)"', html_a))
        names_b = set(re.findall(r'name="([^"]+)"', html_b))

        # Names should not overlap (no intersection)
        overlap = names_a & names_b
        assert len(overlap) == 0, \
            f"Different schemas should not share names, but found overlap: {overlap}"

    def test_multirate_values_are_rating_labels(self):
        """Multirate radio values should be the rating labels for proper data capture."""
        import re

        schema = {
            "annotation_type": "multirate",
            "annotation_id": 0,
            "name": "ratings",
            "description": "Rate items",
            "options": ["quality", "speed"],
            "labels": ["poor", "fair", "good"]
        }

        html_layout, _ = generate_schematic(schema)

        # Extract all value attributes
        values = re.findall(r'value="([^"]+)"', html_layout)

        # Values should include the rating labels
        for label in ["poor", "fair", "good"]:
            assert label in values, \
                f"Rating label '{label}' should be a value attribute, got {values}"