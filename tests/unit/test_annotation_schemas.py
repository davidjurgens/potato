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
            "labels": ["grammar", "clarity", "relevance"],
            "options": ["poor", "fair", "good", "excellent"]
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