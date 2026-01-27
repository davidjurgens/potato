"""
Tests for the preview CLI functionality.

Tests verify that the preview CLI can:
- Load and validate configuration files
- Extract annotation schemes from configs
- Generate HTML, JSON, and text summary previews
- Output layout-only HTML snippets for prototyping
- Detect keybinding conflicts
"""

import pytest
import json
import os

from potato.preview_cli import (
    load_config,
    validate_config,
    get_annotation_schemes,
    detect_keybinding_conflicts,
    generate_preview_html,
    generate_preview_json,
    generate_preview_summary,
    generate_layout_html,
)


class TestConfigLoading:
    """Test config loading functionality."""

    def test_load_valid_config(self, tmp_path):
        """Test loading a valid YAML configuration file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
annotation_task_name: Test Task
task_dir: ./
output_annotation_dir: ./output
data_files:
  - data.json
item_properties:
  id_key: id
  text_key: text
annotation_schemes:
  - name: test_schema
    annotation_type: radio
    labels: [A, B, C]
    description: Test description
""")
        config = load_config(str(config_file))
        assert config['annotation_task_name'] == 'Test Task'
        assert len(config['annotation_schemes']) == 1
        assert config['annotation_schemes'][0]['name'] == 'test_schema'

    def test_load_missing_config(self):
        """Test that loading a non-existent config raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config.yaml")

    def test_load_invalid_yaml(self, tmp_path):
        """Test that loading invalid YAML raises an error."""
        import yaml
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content:")
        with pytest.raises(yaml.YAMLError):
            load_config(str(config_file))


class TestValidation:
    """Test config validation."""

    def test_valid_config_passes(self):
        """Test that a valid config passes validation."""
        config = {
            'annotation_task_name': 'Test',
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
            'task_dir': './',
            'output_annotation_dir': './',
            'data_files': ['data.json'],
            'annotation_schemes': [{'name': 'test', 'annotation_type': 'radio'}]
        }
        issues = validate_config(config)
        errors = [i for i in issues if i.startswith('ERROR')]
        assert len(errors) == 0

    def test_missing_required_fields(self):
        """Test that missing required fields are detected."""
        config = {}
        issues = validate_config(config)
        assert any('annotation_task_name' in i for i in issues)
        assert any('item_properties' in i for i in issues)
        assert any('task_dir' in i for i in issues)

    def test_missing_data_source(self):
        """Test that missing data_files and data_directory is detected."""
        config = {
            'annotation_task_name': 'Test',
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
            'task_dir': './',
            'output_annotation_dir': './',
            'data_files': [],
            'annotation_schemes': []
        }
        issues = validate_config(config)
        assert any('data_files' in i or 'data_directory' in i for i in issues)


class TestSchemaExtraction:
    """Test annotation scheme extraction."""

    def test_top_level_schemes(self):
        """Test extracting schemes from top-level annotation_schemes."""
        config = {
            'annotation_schemes': [
                {'name': 'schema1', 'annotation_type': 'radio'},
                {'name': 'schema2', 'annotation_type': 'multiselect'}
            ]
        }
        schemes = get_annotation_schemes(config)
        assert len(schemes) == 2
        assert schemes[0]['name'] == 'schema1'
        assert schemes[1]['name'] == 'schema2'

    def test_phase_schemes_list(self):
        """Test extracting schemes from phases (list format)."""
        config = {
            'phases': [
                {'name': 'phase1', 'annotation_schemes': [
                    {'name': 'phase1_schema', 'annotation_type': 'radio'}
                ]},
                {'name': 'phase2', 'annotation_schemes': [
                    {'name': 'phase2_schema', 'annotation_type': 'text'}
                ]}
            ]
        }
        schemes = get_annotation_schemes(config)
        assert len(schemes) == 2

    def test_phase_schemes_dict(self):
        """Test extracting schemes from phases (dict format)."""
        config = {
            'phases': {
                'phase1': {'annotation_schemes': [{'name': 'test'}]},
                'order': ['phase1']
            }
        }
        schemes = get_annotation_schemes(config)
        assert len(schemes) == 1

    def test_no_schemes(self):
        """Test handling configs with no annotation schemes."""
        config = {}
        schemes = get_annotation_schemes(config)
        assert len(schemes) == 0


class TestHTMLGeneration:
    """Test HTML generation functions."""

    def test_generate_preview_html_sets_annotation_id(self):
        """Test that generate_preview_html sets annotation_id on schemes."""
        schemes = [
            {'name': 'test', 'annotation_type': 'radio', 'labels': ['A', 'B'], 'description': 'Test'}
        ]
        html = generate_preview_html(schemes)

        # Should contain the full page wrapper
        assert '<!DOCTYPE html>' in html
        assert '<html>' in html

        # Should have annotation_id attribute
        assert 'data-annotation-id' in html

        # Should have the schema name
        assert 'test' in html

    def test_generate_preview_html_multiple_schemes(self):
        """Test HTML generation with multiple schemes."""
        schemes = [
            {'name': 'schema1', 'annotation_type': 'radio', 'labels': ['A', 'B'], 'description': 'First'},
            {'name': 'schema2', 'annotation_type': 'multiselect', 'labels': ['X', 'Y'], 'description': 'Second'}
        ]
        html = generate_preview_html(schemes)

        assert 'schema1' in html
        assert 'schema2' in html
        assert 'data-annotation-id="0"' in html
        assert 'data-annotation-id="1"' in html

    def test_generate_layout_html_no_wrapper(self):
        """Test that generate_layout_html outputs just the schema div."""
        schemes = [
            {'name': 'test', 'annotation_type': 'radio', 'labels': ['A', 'B'], 'description': 'Test'}
        ]
        html = generate_layout_html(schemes)

        # Should have annotation schema wrapper
        assert '<div class="annotation_schema">' in html
        assert '</div>' in html

        # Should NOT have full page wrapper
        assert '<!DOCTYPE' not in html
        assert '<html>' not in html
        assert '<head>' not in html
        assert '<body>' not in html

        # Should have annotation_id
        assert 'data-annotation-id' in html

    def test_generate_layout_html_handles_errors(self):
        """Test that errors during generation are captured as comments."""
        # Invalid scheme should cause an error
        schemes = [
            {'name': 'bad_schema', 'annotation_type': 'unknown_type'}
        ]
        html = generate_layout_html(schemes)

        # Should contain error comment but not crash
        assert '<div class="annotation_schema">' in html
        assert 'Error' in html or 'error' in html.lower()


class TestKeybindingConflicts:
    """Test keybinding conflict detection."""

    def test_no_conflicts(self):
        """Test that non-conflicting keybindings pass."""
        schemes = [
            {'name': 's1', 'labels': [{'name': 'A', 'key_value': '1'}]},
            {'name': 's2', 'labels': [{'name': 'B', 'key_value': '2'}]}
        ]
        conflicts = detect_keybinding_conflicts(schemes)
        assert len(conflicts) == 0

    def test_detects_cross_schema_conflict(self):
        """Test that conflicts across different schemas are detected."""
        schemes = [
            {'name': 's1', 'labels': [{'name': 'A', 'key_value': '1'}]},
            {'name': 's2', 'labels': [{'name': 'B', 'key_value': '1'}]}  # Same key!
        ]
        conflicts = detect_keybinding_conflicts(schemes)
        assert len(conflicts) > 0
        assert 's1' in conflicts[0]
        assert 's2' in conflicts[0]

    def test_same_schema_keys_not_conflict(self):
        """Test that same key in same schema is not a cross-schema conflict."""
        schemes = [
            {'name': 's1', 'labels': [
                {'name': 'A', 'key_value': '1'},
                {'name': 'B', 'key_value': '1'}  # Same schema, would conflict internally
            ]}
        ]
        conflicts = detect_keybinding_conflicts(schemes)
        # This function only detects cross-schema conflicts
        assert len(conflicts) == 0

    def test_sequential_keybinding_detection(self):
        """Test detection of sequential keybinding conflicts."""
        schemes = [
            {'name': 's1', 'sequential_key_binding': True, 'labels': ['A', 'B']},  # Gets keys 1, 2
            {'name': 's2', 'labels': [{'name': 'X', 'key_value': '1'}]}  # Conflicts with 1
        ]
        conflicts = detect_keybinding_conflicts(schemes)
        assert len(conflicts) > 0


class TestJSONGeneration:
    """Test JSON output generation."""

    def test_generate_preview_json_structure(self):
        """Test JSON output has correct structure."""
        config = {'annotation_task_name': 'Test Task'}
        schemes = [
            {'name': 'test', 'annotation_type': 'radio', 'labels': ['A', 'B'], 'description': 'Test'}
        ]
        result = generate_preview_json(config, schemes, [])
        data = json.loads(result)

        assert data['task_name'] == 'Test Task'
        assert data['schema_count'] == 1
        assert len(data['schemas']) == 1
        assert data['schemas'][0]['name'] == 'test'
        assert data['schemas'][0]['type'] == 'radio'

    def test_generate_preview_json_includes_labels(self):
        """Test that JSON output includes labels."""
        config = {'annotation_task_name': 'Test'}
        schemes = [
            {'name': 'test', 'annotation_type': 'radio',
             'labels': [{'name': 'LabelA'}, 'LabelB'], 'description': 'Test'}
        ]
        result = generate_preview_json(config, schemes, [])
        data = json.loads(result)

        assert data['schemas'][0]['labels'] == ['LabelA', 'LabelB']

    def test_generate_preview_json_includes_issues(self):
        """Test that validation issues are included in JSON."""
        config = {'annotation_task_name': 'Test'}
        issues = ['ERROR: Missing required field', 'WARNING: Something']
        schemes = []
        result = generate_preview_json(config, schemes, issues)
        data = json.loads(result)

        assert len(data['validation_issues']) == 2
        assert 'ERROR' in data['validation_issues'][0]


class TestSummaryGeneration:
    """Test text summary generation."""

    def test_generate_summary_basic(self):
        """Test basic summary generation."""
        config = {
            'annotation_task_name': 'My Task',
            'task_dir': '/path/to/task'
        }
        schemes = [
            {'name': 'test', 'annotation_type': 'radio', 'labels': ['A', 'B'], 'description': 'Test'}
        ]
        summary = generate_preview_summary(config, schemes, [], [])

        assert 'My Task' in summary
        assert 'ANNOTATION SCHEMAS' in summary
        assert '[radio]' in summary
        assert 'test' in summary

    def test_generate_summary_with_issues(self):
        """Test summary includes validation issues."""
        config = {'annotation_task_name': 'Test', 'task_dir': './'}
        issues = ['ERROR: Missing field']
        summary = generate_preview_summary(config, [], issues, [])

        assert 'VALIDATION ISSUES' in summary
        assert 'Missing field' in summary

    def test_generate_summary_with_conflicts(self):
        """Test summary includes keybinding conflicts."""
        config = {'annotation_task_name': 'Test', 'task_dir': './'}
        conflicts = ["WARNING: Key '1' used by both schemas"]
        summary = generate_preview_summary(config, [], [], conflicts)

        assert 'KEYBINDING CONFLICTS' in summary
        assert "Key '1'" in summary


class TestCLIIntegration:
    """Integration tests using actual config files."""

    def test_simple_checkbox_config(self):
        """Test with the simple checkbox example config."""
        config_path = 'project-hub/simple_examples/configs/simple-check-box.yaml'
        if os.path.exists(config_path):
            config = load_config(config_path)
            schemes = get_annotation_schemes(config)

            assert len(schemes) > 0

            # Generate all output formats without errors
            html = generate_preview_html(schemes)
            assert '<html>' in html

            layout = generate_layout_html(schemes)
            assert '<div class="annotation_schema">' in layout

            json_output = generate_preview_json(config, schemes, [])
            data = json.loads(json_output)
            assert 'schemas' in data

    def test_radio_button_config(self):
        """Test with the radio button example config."""
        config_path = 'project-hub/simple_examples/configs/simple-radio-buttons.yaml'
        if os.path.exists(config_path):
            config = load_config(config_path)
            schemes = get_annotation_schemes(config)

            # Should have at least one schema
            assert len(schemes) >= 1

            # Generate layout should work
            layout = generate_layout_html(schemes)
            assert 'data-annotation-id' in layout
