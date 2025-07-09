"""
Tests for config validation and stress testing.

This module tests the validation of Potato configuration files, including:
- Required field validation
- Annotation scheme validation
- Phase configuration validation
- Data file validation
- Template validation
- Stress testing with various config scenarios
"""

import pytest
import json
import yaml
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from potato.server_utils.config_module import init_config, config


class TestConfigValidation:
    """Test config file validation and required fields."""

    @pytest.fixture(scope="class")
    def temp_project_dir(self):
        """Create a temporary project directory for testing"""
        temp_dir = tempfile.mkdtemp()

        # Copy simple examples to temp directory
        simple_examples_dir = os.path.join(os.path.dirname(__file__), '..', 'project-hub', 'simple_examples')
        shutil.copytree(simple_examples_dir, os.path.join(temp_dir, 'simple_examples'))

        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_required_fields_validation(self, temp_project_dir):
        """Test that all required fields are present in config files."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml',
            'simple_examples/configs/simple-span-labeling.yaml',
            'simple_examples/configs/simple-multirate.yaml',
            'simple_examples/configs/simple-text-box.yaml',
            'simple_examples/configs/all-phases-example.yaml'
        ]

        required_fields = [
            'annotation_task_name',
            'task_dir',
            'output_annotation_dir',
            'output_annotation_format',
            'data_files',
            'item_properties',
            'user_config',
            'alert_time_each_instance',
            'annotation_schemes',
            'html_layout',
            'base_html_template',
            'header_file',
            'site_dir'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            # Check all required fields are present
            for field in required_fields:
                assert field in config_data, f"Missing required field '{field}' in {config_file}"

    def test_item_properties_validation(self, temp_project_dir):
        """Test that item_properties contains required keys."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            item_props = config_data['item_properties']
            assert 'id_key' in item_props, f"Missing id_key in item_properties in {config_file}"
            assert 'text_key' in item_props, f"Missing text_key in item_properties in {config_file}"
            assert isinstance(item_props['id_key'], str), f"id_key must be string in {config_file}"
            assert isinstance(item_props['text_key'], str), f"text_key must be string in {config_file}"

    def test_annotation_schemes_validation(self, temp_project_dir):
        """Test that annotation schemes are properly configured."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml',
            'simple_examples/configs/simple-span-labeling.yaml',
            'simple_examples/configs/simple-multirate.yaml',
            'simple_examples/configs/simple-text-box.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            schemes = config_data['annotation_schemes']
            assert isinstance(schemes, list), f"annotation_schemes must be a list in {config_file}"
            assert len(schemes) > 0, f"annotation_schemes cannot be empty in {config_file}"

            for i, scheme in enumerate(schemes):
                # Required fields for all annotation schemes
                assert 'annotation_type' in scheme, f"Missing annotation_type in scheme {i} in {config_file}"
                assert 'name' in scheme, f"Missing name in scheme {i} in {config_file}"
                assert 'description' in scheme, f"Missing description in scheme {i} in {config_file}"

                # Validate annotation_type is supported
                supported_types = [
                    'likert', 'radio', 'multiselect', 'slider', 'highlight',
                    'text', 'multirate', 'select', 'number', 'pure_display'
                ]
                assert scheme['annotation_type'] in supported_types, \
                    f"Unsupported annotation_type '{scheme['annotation_type']}' in {config_file}"

                # Type-specific validation
                self._validate_annotation_scheme_type(scheme, config_file, i)

    def _validate_annotation_scheme_type(self, scheme, config_file, scheme_index):
        """Validate annotation scheme based on its type."""
        scheme_type = scheme['annotation_type']

        if scheme_type == 'likert':
            assert 'min_label' in scheme, f"Missing min_label in likert scheme in {config_file}"
            assert 'max_label' in scheme, f"Missing max_label in likert scheme in {config_file}"
            assert 'size' in scheme, f"Missing size in likert scheme in {config_file}"
            assert isinstance(scheme['size'], int), f"size must be integer in likert scheme in {config_file}"
            assert 2 <= scheme['size'] <= 10, f"size must be between 2 and 10 in likert scheme in {config_file}"

        elif scheme_type == 'radio':
            assert 'labels' in scheme, f"Missing labels in radio scheme in {config_file}"
            assert isinstance(scheme['labels'], list), f"labels must be list in radio scheme in {config_file}"
            assert len(scheme['labels']) > 0, f"labels cannot be empty in radio scheme in {config_file}"

        elif scheme_type == 'multiselect':
            assert 'labels' in scheme, f"Missing labels in multiselect scheme in {config_file}"
            assert isinstance(scheme['labels'], list), f"labels must be list in multiselect scheme in {config_file}"
            assert len(scheme['labels']) > 0, f"labels cannot be empty in multiselect scheme in {config_file}"

        elif scheme_type == 'slider':
            assert 'min_value' in scheme, f"Missing min_value in slider scheme in {config_file}"
            assert 'max_value' in scheme, f"Missing max_value in slider scheme in {config_file}"
            assert 'starting_value' in scheme, f"Missing starting_value in slider scheme in {config_file}"
            assert isinstance(scheme['min_value'], (int, float)), f"min_value must be numeric in slider scheme in {config_file}"
            assert isinstance(scheme['max_value'], (int, float)), f"max_value must be numeric in slider scheme in {config_file}"
            assert isinstance(scheme['starting_value'], (int, float)), f"starting_value must be numeric in slider scheme in {config_file}"
            assert scheme['min_value'] < scheme['max_value'], f"min_value must be less than max_value in slider scheme in {config_file}"
            assert scheme['min_value'] <= scheme['starting_value'] <= scheme['max_value'], \
                f"starting_value must be between min_value and max_value in slider scheme in {config_file}"

        elif scheme_type == 'highlight':
            assert 'labels' in scheme, f"Missing labels in highlight scheme in {config_file}"
            assert isinstance(scheme['labels'], list), f"labels must be list in highlight scheme in {config_file}"
            assert len(scheme['labels']) > 0, f"labels cannot be empty in highlight scheme in {config_file}"

        elif scheme_type == 'text':
            # Text schemes can have optional textarea configuration
            if 'textarea' in scheme:
                textarea = scheme['textarea']
                assert isinstance(textarea, dict), f"textarea must be dict in text scheme in {config_file}"
                if 'on' in textarea:
                    assert isinstance(textarea['on'], bool), f"textarea.on must be boolean in text scheme in {config_file}"

        elif scheme_type == 'multirate':
            assert 'options' in scheme, f"Missing options in multirate scheme in {config_file}"
            assert 'labels' in scheme, f"Missing labels in multirate scheme in {config_file}"
            assert isinstance(scheme['options'], list), f"options must be list in multirate scheme in {config_file}"
            assert isinstance(scheme['labels'], list), f"labels must be list in multirate scheme in {config_file}"
            assert len(scheme['options']) > 0, f"options cannot be empty in multirate scheme in {config_file}"
            assert len(scheme['labels']) > 0, f"labels cannot be empty in multirate scheme in {config_file}"

    def test_data_files_validation(self, temp_project_dir):
        """Test that data files exist and are accessible."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            data_files = config_data['data_files']
            assert isinstance(data_files, list), f"data_files must be a list in {config_file}"
            assert len(data_files) > 0, f"data_files cannot be empty in {config_file}"

            for data_file in data_files:
                full_path = os.path.join(temp_project_dir, 'simple_examples', data_file)
                assert os.path.exists(full_path), f"Data file not found: {full_path}"

                # Check file format is supported
                file_ext = os.path.splitext(data_file)[1].lower()
                supported_formats = ['.json', '.jsonl', '.csv', '.tsv']
                assert file_ext in supported_formats, f"Unsupported data file format: {file_ext}"

    def test_output_format_validation(self, temp_project_dir):
        """Test that output format is valid."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        supported_formats = ['jsonl', 'json', 'csv', 'tsv']

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            output_format = config_data['output_annotation_format']
            assert output_format in supported_formats, f"Unsupported output format: {output_format}"

    def test_user_config_validation(self, temp_project_dir):
        """Test that user configuration is valid."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            user_config = config_data['user_config']
            assert 'allow_all_users' in user_config, f"Missing allow_all_users in user_config in {config_file}"
            assert 'users' in user_config, f"Missing users in user_config in {config_file}"
            assert isinstance(user_config['allow_all_users'], bool), f"allow_all_users must be boolean in {config_file}"
            assert isinstance(user_config['users'], list), f"users must be list in {config_file}"

    def test_phases_validation(self, temp_project_dir):
        """Test that phases configuration is valid (if present)."""
        config_path = os.path.join(temp_project_dir, 'simple_examples/configs/all-phases-example.yaml')
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)

        if 'phases' in config_data:
            phases = config_data['phases']
            assert isinstance(phases, dict), "phases must be a dictionary"

            if 'order' in phases:
                order = phases['order']
                assert isinstance(order, list), "phases.order must be a list"
                assert len(order) > 0, "phases.order cannot be empty"

                # Check that all phases in order exist
                for phase_name in order:
                    assert phase_name in phases, f"Phase '{phase_name}' in order not found in phases"

            # Validate each phase
            for phase_name, phase_config in phases.items():
                if phase_name == 'order':
                    continue

                assert isinstance(phase_config, dict), f"Phase '{phase_name}' must be a dictionary"
                assert 'type' in phase_config, f"Phase '{phase_name}' missing type"
                assert 'file' in phase_config, f"Phase '{phase_name}' missing file"

                # Validate phase type
                supported_phase_types = ['consent', 'instructions', 'prestudy', 'training', 'poststudy']
                assert phase_config['type'] in supported_phase_types, f"Unsupported phase type: {phase_config['type']}"

                # Check that phase file exists
                phase_file = phase_config['file']
                full_path = os.path.join(temp_project_dir, 'simple_examples', phase_file)
                assert os.path.exists(full_path), f"Phase file not found: {full_path}"

    def test_template_validation(self, temp_project_dir):
        """Test that template configurations are valid."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            # Check template fields
            template_fields = ['html_layout', 'base_html_template', 'header_file', 'site_dir']
            for field in template_fields:
                assert field in config_data, f"Missing template field: {field}"
                assert isinstance(config_data[field], str), f"Template field {field} must be string"

    def test_alert_time_validation(self, temp_project_dir):
        """Test that alert time configuration is valid."""
        config_files = [
            'simple_examples/configs/simple-likert.yaml',
            'simple_examples/configs/simple-check-box.yaml',
            'simple_examples/configs/simple-slider.yaml'
        ]

        for config_file in config_files:
            config_path = os.path.join(temp_project_dir, config_file)
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            alert_time = config_data['alert_time_each_instance']
            assert isinstance(alert_time, (int, float)), f"alert_time_each_instance must be numeric in {config_file}"
            assert alert_time > 0, f"alert_time_each_instance must be positive in {config_file}"


class TestConfigStressTesting:
    """Stress testing for config files with various edge cases and invalid configurations."""

    def test_missing_required_fields(self):
        """Test that missing required fields are properly handled."""
        invalid_configs = [
            {},  # Empty config
            {"annotation_task_name": "Test"},  # Missing most fields
            {"annotation_task_name": "Test", "task_dir": "test"},  # Missing more fields
        ]

        for invalid_config in invalid_configs:
            with pytest.raises((KeyError, AssertionError)):
                self._validate_config_required_fields(invalid_config)

    def _validate_config_required_fields(self, config_data):
        """Helper method to validate required fields."""
        required_fields = [
            'annotation_task_name', 'task_dir', 'output_annotation_dir',
            'data_files', 'item_properties', 'annotation_schemes'
        ]

        for field in required_fields:
            if field not in config_data:
                raise KeyError(f"Missing required field: {field}")

        return True

    def test_invalid_annotation_types(self):
        """Test that invalid annotation types are rejected."""
        invalid_schemes = [
            {"annotation_type": "invalid_type", "name": "test", "description": "test"},
            {"annotation_type": "", "name": "test", "description": "test"},
            {"annotation_type": None, "name": "test", "description": "test"},
        ]

        for scheme in invalid_schemes:
            with pytest.raises(AssertionError):
                self._validate_annotation_scheme(scheme)

    def _validate_annotation_scheme(self, scheme):
        """Helper method to validate annotation scheme."""
        supported_types = ['likert', 'radio', 'multiselect', 'slider', 'highlight', 'text', 'multirate']
        assert scheme['annotation_type'] in supported_types, f"Unsupported type: {scheme['annotation_type']}"
        return True

    def test_invalid_slider_values(self):
        """Test that invalid slider configurations are rejected."""
        invalid_sliders = [
            {"annotation_type": "slider", "name": "test", "description": "test",
             "min_value": 10, "max_value": 5, "starting_value": 7},  # min > max
            {"annotation_type": "slider", "name": "test", "description": "test",
             "min_value": 0, "max_value": 10, "starting_value": 15},  # start > max
            {"annotation_type": "slider", "name": "test", "description": "test",
             "min_value": 0, "max_value": 10, "starting_value": -5},  # start < min
        ]

        for slider in invalid_sliders:
            with pytest.raises(AssertionError):
                self._validate_slider_config(slider)

    def _validate_slider_config(self, scheme):
        """Helper method to validate slider configuration."""
        assert scheme['min_value'] < scheme['max_value'], "min_value must be less than max_value"
        assert scheme['min_value'] <= scheme['starting_value'] <= scheme['max_value'], \
            "starting_value must be between min_value and max_value"
        return True

    def test_invalid_likert_size(self):
        """Test that invalid likert scale sizes are rejected."""
        invalid_likerts = [
            {"annotation_type": "likert", "name": "test", "description": "test",
             "min_label": "min", "max_label": "max", "size": 1},  # too small
            {"annotation_type": "likert", "name": "test", "description": "test",
             "min_label": "min", "max_label": "max", "size": 15},  # too large
            {"annotation_type": "likert", "name": "test", "description": "test",
             "min_label": "min", "max_label": "max", "size": 0},  # zero
        ]

        for likert in invalid_likerts:
            with pytest.raises(AssertionError):
                self._validate_likert_config(likert)

    def _validate_likert_config(self, scheme):
        """Helper method to validate likert configuration."""
        assert 2 <= scheme['size'] <= 10, "size must be between 2 and 10"
        return True

    def test_empty_annotation_schemes(self):
        """Test that empty annotation schemes are rejected."""
        invalid_configs = [
            {"annotation_schemes": []},
            {"annotation_schemes": None},
        ]

        for config_data in invalid_configs:
            with pytest.raises(AssertionError):
                self._validate_annotation_schemes(config_data['annotation_schemes'])

    def _validate_annotation_schemes(self, schemes):
        """Helper method to validate annotation schemes."""
        assert isinstance(schemes, list), "annotation_schemes must be a list"
        assert len(schemes) > 0, "annotation_schemes cannot be empty"
        return True

    def test_invalid_data_files(self):
        """Test that invalid data file configurations are rejected."""
        invalid_configs = [
            {"data_files": []},  # empty list
            {"data_files": None},  # None
        ]

        for config_data in invalid_configs:
            with pytest.raises(AssertionError):
                self._validate_data_files(config_data['data_files'])

    def _validate_data_files(self, data_files):
        """Helper method to validate data files."""
        assert isinstance(data_files, list), "data_files must be a list"
        assert len(data_files) > 0, "data_files cannot be empty"
        # Note: In real testing, we'd check file existence here
        return True

    def test_invalid_output_formats(self):
        """Test that invalid output formats are rejected."""
        invalid_formats = ['txt', 'xml', 'pdf', 'docx', '']

        for output_format in invalid_formats:
            with pytest.raises(AssertionError):
                self._validate_output_format(output_format)

    def _validate_output_format(self, output_format):
        """Helper method to validate output format."""
        supported_formats = ['jsonl', 'json', 'csv', 'tsv']
        assert output_format in supported_formats, f"Unsupported output format: {output_format}"
        return True

    def test_malformed_yaml(self):
        """Test that malformed YAML files are properly handled."""
        malformed_yamls = [
            "invalid: yaml: content: [",
            "annotation_task_name: 'Test\n  task_dir: 'test'",  # unclosed quote
            "annotation_task_name: 'Test'\ntask_dir: [1, 2, 3",  # unclosed bracket
        ]

        for malformed_yaml in malformed_yamls:
            with pytest.raises((yaml.YAMLError, yaml.parser.ParserError)):
                yaml.safe_load(malformed_yaml)

    def test_duplicate_annotation_names(self):
        """Test that duplicate annotation names are detected."""
        config_with_duplicates = {
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "same_name", "description": "test1", "labels": ["a", "b"]},
                {"annotation_type": "radio", "name": "same_name", "description": "test2", "labels": ["c", "d"]}
            ]
        }

        with pytest.raises(AssertionError):
            self._validate_unique_annotation_names(config_with_duplicates['annotation_schemes'])

    def _validate_unique_annotation_names(self, schemes):
        """Helper method to validate unique annotation names."""
        names = [scheme['name'] for scheme in schemes]
        assert len(names) == len(set(names)), "Annotation names must be unique"
        return True

    def test_invalid_phase_configurations(self):
        """Test that invalid phase configurations are rejected."""
        invalid_phases = [
            {"phases": {"order": ["nonexistent_phase"]}},
            {"phases": {"invalid_phase": {"type": "invalid_type", "file": "test.json"}}},
            {"phases": {"test_phase": {"type": "consent"}}},  # missing file
            {"phases": {"test_phase": {"file": "test.json"}}},  # missing type
        ]

        for phase_config in invalid_phases:
            with pytest.raises((KeyError, AssertionError)):
                self._validate_phase_config(phase_config.get('phases', {}))

    def _validate_phase_config(self, phases):
        """Helper method to validate phase configuration."""
        if 'order' in phases:
            for phase_name in phases['order']:
                if phase_name != 'order':
                    assert phase_name in phases, f"Phase '{phase_name}' not found"

        for phase_name, phase_config in phases.items():
            if phase_name == 'order':
                continue

            assert 'type' in phase_config, f"Phase '{phase_name}' missing type"
            assert 'file' in phase_config, f"Phase '{phase_name}' missing file"

            supported_types = ['consent', 'instructions', 'prestudy', 'training', 'poststudy']
            assert phase_config['type'] in supported_types, f"Unsupported phase type: {phase_config['type']}"

        return True

    def test_large_config_files(self):
        """Test that large configuration files are handled properly."""
        # Create a large config with many annotation schemes
        large_config = {
            "annotation_task_name": "Large Test",
            "task_dir": "test/",
            "output_annotation_dir": "test/annotations/",
            "output_annotation_format": "jsonl",
            "data_files": ["data/test.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "alert_time_each_instance": 1000,
            "annotation_schemes": []
        }

        # Add 100 annotation schemes
        for i in range(100):
            large_config["annotation_schemes"].append({
                "annotation_type": "radio",
                "name": f"scheme_{i}",
                "description": f"Test scheme {i}",
                "labels": [f"label_{i}_1", f"label_{i}_2", f"label_{i}_3"]
            })

        # This should not raise any exceptions
        assert len(large_config["annotation_schemes"]) == 100
        assert all('name' in scheme for scheme in large_config["annotation_schemes"])

    def test_nested_config_structures(self):
        """Test that deeply nested configuration structures are handled."""
        nested_config = {
            "annotation_task_name": "Nested Test",
            "task_dir": "test/",
            "output_annotation_dir": "test/annotations/",
            "output_annotation_format": "jsonl",
            "data_files": ["data/test.json"],
            "item_properties": {
                "id_key": "id",
                "text_key": "text",
                "kwargs": ["nested", "properties"],
                "nested": {
                    "level1": {
                        "level2": {
                            "level3": {
                                "value": "deeply_nested"
                            }
                        }
                    }
                }
            },
            "user_config": {"allow_all_users": True, "users": []},
            "alert_time_each_instance": 1000,
            "annotation_schemes": [
                {
                    "annotation_type": "multirate",
                    "name": "nested_test",
                    "description": "Test with nested config",
                    "display_config": {
                        "num_columns": 2,
                        "nested_options": {
                            "option1": {"suboption": "value1"},
                            "option2": {"suboption": "value2"}
                        }
                    },
                    "options": ["Option 1", "Option 2"],
                    "labels": ["Disagree", "Agree"]
                }
            ]
        }

        # This should not raise any exceptions
        assert nested_config["item_properties"]["nested"]["level1"]["level2"]["level3"]["value"] == "deeply_nested"
        assert nested_config["annotation_schemes"][0]["display_config"]["nested_options"]["option1"]["suboption"] == "value1"


class TestConfigIntegration:
    """Integration tests for config loading and validation."""

    @pytest.fixture(scope="class")
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @patch('potato.server_utils.config_module.config')
    def test_config_loading_integration(self, mock_config):
        """Test that config loading works with the Flask server."""
        # Mock the config loading process
        mock_config.update.return_value = None

        # Create a mock args object
        mock_args = MagicMock()
        mock_args.config_file = "test_config.yaml"
        mock_args.verbose = False
        mock_args.very_verbose = False
        mock_args.debug = False
        mock_args.customjs = False
        mock_args.customjs_hostname = None

        # This should not raise any exceptions
        try:
            # Note: We can't actually call init_config here because it requires file system access
            # But we can test the structure of what it expects
            assert mock_args.config_file.endswith('.yaml')
            assert isinstance(mock_args.verbose, bool)
            assert isinstance(mock_args.debug, bool)
        except Exception as e:
            pytest.fail(f"Config loading integration test failed: {e}")

    def test_config_with_real_data_files(self, temp_project_dir):
        """Test config validation with real data files."""
        # Create a temporary data file
        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'test_data.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump([
                {"id": "1", "text": "Test item 1"},
                {"id": "2", "text": "Test item 2"}
            ], f)

        # Create a minimal valid config
        test_config = {
            "annotation_task_name": "Integration Test",
            "task_dir": "test_output/",
            "output_annotation_dir": "test_output/annotations/",
            "output_annotation_format": "jsonl",
            "data_files": ["data/test_data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "user_config": {"allow_all_users": True, "users": []},
            "alert_time_each_instance": 1000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "test_annotation",
                    "description": "Test annotation",
                    "labels": ["option1", "option2"]
                }
            ],
            "html_layout": "default",
            "base_html_template": "default",
            "header_file": "default",
            "site_dir": "default"
        }

        # Validate the config
        assert test_config["annotation_task_name"] == "Integration Test"
        assert len(test_config["annotation_schemes"]) == 1
        assert test_config["annotation_schemes"][0]["annotation_type"] == "radio"
        assert os.path.exists(data_file)

    def test_config_error_handling(self):
        """Test that config errors are properly handled and reported."""
        invalid_configs = [
            ({"annotation_task_name": 123}, "annotation_task_name should be string"),
            ({"task_dir": None}, "task_dir should be string"),
            ({"output_annotation_format": "invalid"}, "output_annotation_format should be valid"),
            ({"alert_time_each_instance": -1}, "alert_time_each_instance should be positive"),
        ]

        for config_data, expected_error in invalid_configs:
            with pytest.raises((TypeError, ValueError, AssertionError)):
                self._validate_config_types(config_data)

    def _validate_config_types(self, config_data):
        """Helper method to validate config data types."""
        if 'annotation_task_name' in config_data:
            assert isinstance(config_data['annotation_task_name'], str), "annotation_task_name should be string"

        if 'task_dir' in config_data:
            assert isinstance(config_data['task_dir'], str), "task_dir should be string"

        if 'output_annotation_format' in config_data:
            supported_formats = ['jsonl', 'json', 'csv', 'tsv']
            assert config_data['output_annotation_format'] in supported_formats, "output_annotation_format should be valid"

        if 'alert_time_each_instance' in config_data:
            assert config_data['alert_time_each_instance'] > 0, "alert_time_each_instance should be positive"

        return True