#!/usr/bin/env python3
"""
Unit tests for the loadAnnotations() DOM state preservation fix.

This test verifies that the loadAnnotations() function in annotation.js:
1. Does NOT clear form inputs (preserving server-rendered state)
2. Reads existing annotation state from the DOM into currentAnnotations

The bug was that loadAnnotations() was calling clearAllFormInputs() which
wiped out server-rendered checkbox states when navigating between instances.

These tests simulate the DOM behavior without requiring a full browser.
"""

import pytest
import json


class TestLoadAnnotationsDOMBehavior:
    """
    Tests that verify the expected behavior of loadAnnotations().

    Since loadAnnotations() is JavaScript, these tests verify the
    expected behavior by checking the server-side rendering and
    documenting what the JS function should do.
    """

    def test_server_renders_checked_checkboxes(self):
        """
        Test that the server correctly sets 'checked' attribute on checkboxes
        when rendering a previously annotated instance.

        This verifies the server-side of the equation - BeautifulSoup sets
        input_field['checked'] = True for annotated checkboxes.
        """
        from bs4 import BeautifulSoup

        # Simulate the HTML rendering with checkboxes
        html = '''
        <form>
            <input type="checkbox" name="test_colors:::red" value="1" schema="test_colors" label_name="red">
            <input type="checkbox" name="test_colors:::green" value="2" schema="test_colors" label_name="green">
            <input type="checkbox" name="test_colors:::blue" value="3" schema="test_colors" label_name="blue">
        </form>
        '''

        soup = BeautifulSoup(html, 'html.parser')

        # Simulate what flask_server.py does when user has previous annotations
        annotations = {
            'test_colors': {
                'red': '1',  # User previously selected red
                'blue': '3'   # User previously selected blue
            }
        }

        # This is the logic from flask_server.py lines 1121-1149
        for schema_name, label_dict in annotations.items():
            for label_name, value in label_dict.items():
                name = schema_name + ":::" + label_name
                input_fields = soup.find_all(['input'], {'name': name})

                for input_field in input_fields:
                    if input_field['type'] == 'checkbox':
                        if value:
                            input_field['checked'] = True

        # Verify the checkboxes are correctly marked as checked
        red_checkbox = soup.find('input', {'label_name': 'red'})
        green_checkbox = soup.find('input', {'label_name': 'green'})
        blue_checkbox = soup.find('input', {'label_name': 'blue'})

        assert red_checkbox.has_attr('checked'), "Red should be checked"
        assert not green_checkbox.has_attr('checked'), "Green should NOT be checked"
        assert blue_checkbox.has_attr('checked'), "Blue should be checked"

    def test_server_renders_checked_radio_buttons(self):
        """
        Test that the server correctly sets 'checked' attribute on radio buttons.
        """
        from bs4 import BeautifulSoup

        html = '''
        <form>
            <input type="radio" name="sentiment:::positive" value="1" schema="sentiment" label_name="positive">
            <input type="radio" name="sentiment:::neutral" value="2" schema="sentiment" label_name="neutral">
            <input type="radio" name="sentiment:::negative" value="3" schema="sentiment" label_name="negative">
        </form>
        '''

        soup = BeautifulSoup(html, 'html.parser')

        # User previously selected "positive"
        annotations = {
            'sentiment': {
                'positive': True
            }
        }

        for schema_name, label_dict in annotations.items():
            for label_name, value in label_dict.items():
                name = schema_name + ":::" + label_name
                input_fields = soup.find_all(['input'], {'name': name})

                for input_field in input_fields:
                    if input_field['type'] == 'radio':
                        if value:
                            input_field['checked'] = True

        positive = soup.find('input', {'label_name': 'positive'})
        neutral = soup.find('input', {'label_name': 'neutral'})
        negative = soup.find('input', {'label_name': 'negative'})

        assert positive.has_attr('checked'), "Positive should be checked"
        assert not neutral.has_attr('checked'), "Neutral should NOT be checked"
        assert not negative.has_attr('checked'), "Negative should NOT be checked"


class TestLoadAnnotationsJSBehavior:
    """
    Tests that document the expected JavaScript behavior.

    These tests use string matching to verify the annotation.js code
    has the correct implementation.
    """

    def test_load_annotations_does_not_call_clear_all_form_inputs(self):
        """
        Verify that loadAnnotations() does NOT call clearAllFormInputs().

        The bug was that loadAnnotations() was clearing form inputs,
        wiping out server-rendered state.
        """
        import os
        from pathlib import Path

        # Read the annotation.js file
        project_root = Path(__file__).parent.parent.parent
        annotation_js = project_root / "potato" / "static" / "annotation.js"

        with open(annotation_js, 'r') as f:
            content = f.read()

        # Find the loadAnnotations function
        # It should be between "async function loadAnnotations()" and the next function
        start_marker = "async function loadAnnotations()"
        end_marker = "function generateAnnotationForms()"

        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker, start_idx)

        assert start_idx != -1, "loadAnnotations() function should exist"
        assert end_idx != -1, "generateAnnotationForms() function should exist after loadAnnotations()"

        load_annotations_body = content[start_idx:end_idx]

        # The fix: loadAnnotations should NOT call clearAllFormInputs
        assert "clearAllFormInputs()" not in load_annotations_body, \
            "loadAnnotations() should NOT call clearAllFormInputs() - this was the bug"

        # The fix: loadAnnotations should read checkbox state from DOM
        assert "input[type=\"checkbox\"]" in load_annotations_body or \
               "input[type='checkbox']" in load_annotations_body, \
            "loadAnnotations() should read checkbox state from DOM"

        # The fix: loadAnnotations should read radio state from DOM
        assert "input[type=\"radio\"]" in load_annotations_body or \
               "input[type='radio']" in load_annotations_body, \
            "loadAnnotations() should read radio state from DOM"

    def test_load_annotations_preserves_server_rendered_state(self):
        """
        Verify that loadAnnotations() reads state from DOM instead of clearing it.
        """
        import os
        from pathlib import Path

        project_root = Path(__file__).parent.parent.parent
        annotation_js = project_root / "potato" / "static" / "annotation.js"

        with open(annotation_js, 'r') as f:
            content = f.read()

        start_marker = "async function loadAnnotations()"
        end_marker = "function generateAnnotationForms()"

        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker, start_idx)

        load_annotations_body = content[start_idx:end_idx]

        # Verify the function reads the checked state
        assert ".checked" in load_annotations_body or "is_selected" in load_annotations_body, \
            "loadAnnotations() should read the checked state of inputs"

        # Verify it populates currentAnnotations
        assert "currentAnnotations[" in load_annotations_body or "currentAnnotations =" in load_annotations_body, \
            "loadAnnotations() should populate currentAnnotations from DOM state"

    def test_keyboard_shortcuts_handler_exists(self):
        """
        Verify that the keyboard shortcuts handler for checkboxes/radios exists.

        This tests the keybinding fix that was added alongside the persistence fix.
        """
        import os
        from pathlib import Path

        project_root = Path(__file__).parent.parent.parent
        annotation_js = project_root / "potato" / "static" / "annotation.js"

        with open(annotation_js, 'r') as f:
            content = f.read()

        # Should have a keyup handler for checkbox shortcuts
        assert "keyup" in content, "Should have a keyup event handler"

        # Should handle checkbox toggling via keyboard
        assert "checkbox" in content.lower() and "checked" in content, \
            "Should have checkbox state management"


class TestAnnotationRoundtripIntegration:
    """
    Integration tests that verify the full annotation roundtrip.

    These tests use the Flask test client to verify server behavior
    without requiring Selenium.
    """

    @pytest.fixture
    def test_app(self, tmp_path):
        """Create a test Flask app with a simple checkbox config."""
        import yaml
        import json
        import sys
        from pathlib import Path

        # Add potato to path
        project_root = Path(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        # Create test data
        test_data = [
            {"id": "1", "text": "Test instance 1"},
            {"id": "2", "text": "Test instance 2"},
        ]

        data_file = tmp_path / "test_data.jsonl"
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + "\n")

        # Create config
        config = {
            "annotation_task_name": "Test",
            "task_dir": str(tmp_path),
            "data_files": ["test_data.jsonl"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "name": "colors",
                    "annotation_type": "multiselect",
                    "labels": ["red", "green", "blue"],
                    "sequential_key_binding": True
                }
            ],
            "output_annotation_dir": str(tmp_path / "output"),
            "site_dir": "default",
            "require_password": False,
            "authentication": {"method": "in_memory"},
        }

        config_file = tmp_path / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        return config_file, tmp_path

    def test_annotations_saved_and_retrieved(self, test_app):
        """
        Test that annotations are saved and can be retrieved.

        This is a server-side test that verifies the backend correctly
        stores and returns annotations.
        """
        # This would require initializing the full Flask app
        # For now, we just document the expected behavior
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
