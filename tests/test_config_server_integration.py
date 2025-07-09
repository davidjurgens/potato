"""
Tests for config integration with Flask server.

This module tests how the Flask server uses configuration values, including:
- Config loading and validation in server context
- Server behavior with different config options
- Stress testing with various config scenarios
- Error handling for invalid configs
"""

import pytest
import json
import yaml
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from potato.flask_server import load_instance_data, load_annotation_schematic_data
from potato.server_utils.config_module import init_config, config


class TestConfigServerIntegration:
    """Test how the Flask server integrates with configuration files."""

    def test_config_loading_in_server_context(self, temp_project_dir):
        """Test that config loading works properly in server context."""
        # Use a real config file
        config_path = os.path.join(temp_project_dir, 'simple_examples/configs/simple-likert.yaml')

        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)

        # Test that all required server fields are present
        required_server_fields = [
            'annotation_task_name',
            'task_dir',
            'output_annotation_dir',
            'data_files',
            'item_properties',
            'annotation_schemes'
        ]

        for field in required_server_fields:
            assert field in config_data, f"Missing server-required field: {field}"

        # Test that item_properties has required keys for server
        item_props = config_data['item_properties']
        assert 'id_key' in item_props, "Server requires id_key in item_properties"
        assert 'text_key' in item_props, "Server requires text_key in item_properties"

        # Test that data files exist (server will try to load them)
        for data_file in config_data['data_files']:
            full_path = os.path.join(temp_project_dir, 'simple_examples', data_file)
            assert os.path.exists(full_path), f"Server cannot load non-existent data file: {full_path}"

    def test_server_data_loading_with_config(self, temp_project_dir):
        """Test that the server can load data using config values."""
        # Create a minimal valid config for testing
        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/toy-example.json"],
            "max_annotations_per_user": 10
        }

        # Create test data file
        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'toy-example.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        test_data = [
            {"id": "1", "text": "Test item 1"},
            {"id": "2", "text": "Test item 2"},
            {"id": "3", "text": "Test item 3"}
        ]

        with open(data_file, 'w') as f:
            json.dump(test_data, f)

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should not raise any exceptions
            try:
                load_instance_data(test_config)
                # Verify that items were added to the manager
                assert mock_manager.add_item.call_count == 3
            except Exception as e:
                pytest.fail(f"Server data loading failed: {e}")

    def test_server_annotation_scheme_loading(self, temp_project_dir):
        """Test that the server can process annotation schemes from config."""
        test_config = {
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "task_dir": "test/",
            "site_dir": "default",
            "annotation_task_name": "Test Task",
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "test_radio",
                    "description": "Test radio button",
                    "labels": ["option1", "option2"]
                },
                {
                    "annotation_type": "slider",
                    "name": "test_slider",
                    "description": "Test slider",
                    "min_value": 0,
                    "max_value": 10,
                    "starting_value": 5
                }
            ]
        }

        # Mock the front_end module
        with patch('potato.flask_server.generate_annotation_html_template') as mock_generate:
            mock_generate.return_value = "test_template.html"

            with patch('potato.flask_server.get_user_state_manager') as mock_usm:
                mock_manager = MagicMock()
                mock_usm.return_value = mock_manager

                # This should not raise any exceptions
                try:
                    load_annotation_schematic_data(test_config)
                    # Verify that the template generation was called
                    mock_generate.assert_called_once()
                    # Verify that the phase was added
                    mock_manager.add_phase.assert_called_once()
                except Exception as e:
                    pytest.fail(f"Server annotation scheme loading failed: {e}")

    def test_server_config_error_handling(self):
        """Test that the server handles config errors gracefully."""
        invalid_configs = [
            # Missing required fields
            {},
            {"item_properties": {}},
            {"data_files": []},

            # Invalid data types
            {"item_properties": {"id_key": 123, "text_key": "text"}},
            {"data_files": "not_a_list"},
            {"annotation_schemes": "not_a_list"},

            # Invalid annotation schemes
            {
                "annotation_schemes": [
                    {"annotation_type": "invalid_type", "name": "test", "description": "test"}
                ]
            }
        ]

        for invalid_config in invalid_configs:
            with pytest.raises((KeyError, TypeError, ValueError)):
                # Test data loading with invalid config
                if 'item_properties' in invalid_config and 'data_files' in invalid_config:
                    load_instance_data(invalid_config)

    def test_server_config_with_phases(self, temp_project_dir):
        """Test that the server handles configs with phases correctly."""
        # Create phase files
        phase_dir = os.path.join(temp_project_dir, 'simple_examples', 'configs', 'test-phases')
        os.makedirs(phase_dir, exist_ok=True)

        # Create consent phase file
        consent_file = os.path.join(phase_dir, 'consent.json')
        with open(consent_file, 'w') as f:
            json.dump([{"type": "consent", "text": "Do you consent?"}], f)

        test_config = {
            "phases": {
                "order": ["consent"],
                "consent": {
                    "type": "consent",
                    "file": "configs/test-phases/consent.json"
                }
            },
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "task_dir": "test/",
            "site_dir": "default"
        }

        # Mock the front_end module
        with patch('potato.flask_server.generate_html_from_schematic') as mock_generate:
            mock_generate.return_value = "test_phase_template.html"

            with patch('potato.flask_server.get_user_state_manager') as mock_usm:
                mock_manager = MagicMock()
                mock_usm.return_value = mock_manager

                # This should not raise any exceptions
                try:
                    from potato.flask_server import load_phase_data
                    load_phase_data(test_config)
                    # Verify that the phase was added
                    mock_manager.add_phase.assert_called_once()
                except Exception as e:
                    pytest.fail(f"Server phase loading failed: {e}")

    def test_server_config_with_custom_templates(self, temp_project_dir):
        """Test that the server handles custom template configurations."""
        # Create custom template files
        template_dir = os.path.join(temp_project_dir, 'simple_examples', 'templates')
        os.makedirs(template_dir, exist_ok=True)

        custom_template = os.path.join(template_dir, 'custom_template.html')
        with open(custom_template, 'w') as f:
            f.write("<html><body>Custom template</body></html>")

        test_config = {
            "base_html_template": custom_template,
            "header_file": custom_template,
            "html_layout": custom_template,
            "task_dir": "test/",
            "site_dir": template_dir,
            "annotation_task_name": "Custom Template Test",
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "test",
                    "description": "Test",
                    "labels": ["option1", "option2"]
                }
            ]
        }

        # Mock the front_end module
        with patch('potato.flask_server.generate_annotation_html_template') as mock_generate:
            mock_generate.return_value = "test_template.html"

            with patch('potato.flask_server.get_user_state_manager') as mock_usm:
                mock_manager = MagicMock()
                mock_usm.return_value = mock_manager

                # This should not raise any exceptions
                try:
                    load_annotation_schematic_data(test_config)
                    # Verify that the template generation was called with custom template
                    mock_generate.assert_called_once()
                except Exception as e:
                    pytest.fail(f"Server custom template loading failed: {e}")

    def test_server_config_with_large_datasets(self, temp_project_dir):
        """Test that the server handles large datasets efficiently."""
        # Create a large dataset
        large_data = []
        for i in range(1000):
            large_data.append({
                "id": str(i),
                "text": f"This is test item number {i} with some longer text content to make it more realistic."
            })

        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'large_dataset.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump(large_data, f)

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/large_dataset.json"],
            "max_annotations_per_user": 100
        }

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should not raise any exceptions and should handle large datasets
            try:
                load_instance_data(test_config)
                # Verify that all items were added
                assert mock_manager.add_item.call_count == 1000
            except Exception as e:
                pytest.fail(f"Server large dataset loading failed: {e}")

    def test_server_config_with_complex_annotation_schemes(self, temp_project_dir):
        """Test that the server handles complex annotation schemes correctly."""
        complex_config = {
            "base_html_template": "default",
            "header_file": "default",
            "html_layout": "default",
            "task_dir": "test/",
            "site_dir": "default",
            "annotation_task_name": "Complex Schemes Test",
            "annotation_schemes": [
                {
                    "annotation_type": "multirate",
                    "name": "complex_multirate",
                    "description": "Complex multirate scheme",
                    "display_config": {
                        "num_columns": 2,
                        "custom_styling": True
                    },
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "labels": ["Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree"],
                    "label_requirement": {"required": True},
                    "sequential_key_binding": True,
                    "option_randomization": True
                },
                {
                    "annotation_type": "highlight",
                    "name": "complex_highlight",
                    "description": "Complex highlight scheme",
                    "labels": [
                        {"text": "Positive sentiment", "name": "positive", "abbreviation": "pos"},
                        {"text": "Negative sentiment", "name": "negative", "abbreviation": "neg"},
                        {"text": "Neutral sentiment", "name": "neutral", "abbreviation": "neu"}
                    ],
                    "sequential_key_binding": True
                },
                {
                    "annotation_type": "text",
                    "name": "complex_text",
                    "description": "Complex text input",
                    "textarea": {
                        "on": True,
                        "rows": 5,
                        "cols": 80
                    }
                }
            ]
        }

        # Mock the front_end module
        with patch('potato.flask_server.generate_annotation_html_template') as mock_generate:
            mock_generate.return_value = "complex_template.html"

            with patch('potato.flask_server.get_user_state_manager') as mock_usm:
                mock_manager = MagicMock()
                mock_usm.return_value = mock_manager

                # This should not raise any exceptions
                try:
                    load_annotation_schematic_data(complex_config)
                    # Verify that the template generation was called
                    mock_generate.assert_called_once()
                    # Verify that the phase was added
                    mock_manager.add_phase.assert_called_once()
                except Exception as e:
                    pytest.fail(f"Server complex annotation schemes loading failed: {e}")

    def test_server_config_with_missing_files(self):
        """Test that the server handles missing files gracefully."""
        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/nonexistent.json"]
        }

        # This should raise a FileNotFoundError
        with pytest.raises(FileNotFoundError):
            load_instance_data(test_config)

    def test_server_config_with_duplicate_ids(self, temp_project_dir):
        """Test that the server detects duplicate IDs in data files."""
        # Create data with duplicate IDs
        duplicate_data = [
            {"id": "1", "text": "First item"},
            {"id": "2", "text": "Second item"},
            {"id": "1", "text": "Duplicate ID"}  # Duplicate ID
        ]

        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'duplicate_ids.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump(duplicate_data, f)

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/duplicate_ids.json"]
        }

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should raise a ValueError for duplicate IDs
            with pytest.raises(ValueError, match="Duplicate instance ID"):
                load_instance_data(test_config)

    def test_server_config_with_malformed_data(self, temp_project_dir):
        """Test that the server handles malformed data files gracefully."""
        # Create malformed JSON data
        malformed_data = '{"id": "1", "text": "Valid item"}\n{"id": "2", "text": "Invalid item",}\n'  # Extra comma

        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'malformed.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            f.write(malformed_data)

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/malformed.json"]
        }

        # This should raise a JSON decode error
        with pytest.raises(json.JSONDecodeError):
            load_instance_data(test_config)

    def test_server_config_with_empty_data_files(self, temp_project_dir):
        """Test that the server handles empty data files correctly."""
        # Create empty data file
        empty_data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'empty.json')
        os.makedirs(os.path.dirname(empty_data_file), exist_ok=True)

        with open(empty_data_file, 'w') as f:
            f.write('')

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/empty.json"]
        }

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should not raise an exception but should handle empty file
            try:
                load_instance_data(test_config)
                # Verify that no items were added
                assert mock_manager.add_item.call_count == 0
            except Exception as e:
                pytest.fail(f"Server empty data file handling failed: {e}")

    def test_server_config_with_missing_text_key(self, temp_project_dir):
        """Test that the server handles missing text_key in data gracefully."""
        # Create data without text_key
        data_without_text = [
            {"id": "1", "content": "Item without text_key"},
            {"id": "2", "content": "Another item without text_key"}
        ]

        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'no_text_key.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump(data_without_text, f)

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"  # text_key not in data
            },
            "data_files": ["data/no_text_key.json"]
        }

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should not raise an exception but should log warnings
            try:
                load_instance_data(test_config)
                # Verify that items were still added (with empty text)
                assert mock_manager.add_item.call_count == 2
            except Exception as e:
                pytest.fail(f"Server missing text_key handling failed: {e}")

    def test_server_config_with_custom_properties(self, temp_project_dir):
        """Test that the server handles custom properties in item_properties."""
        # Create data with custom properties
        data_with_custom_props = [
            {
                "id": "1",
                "text": "Item with custom props",
                "category": "test",
                "priority": "high",
                "metadata": {"source": "test", "version": "1.0"}
            }
        ]

        data_file = os.path.join(temp_project_dir, 'simple_examples', 'data', 'custom_props.json')
        os.makedirs(os.path.dirname(data_file), exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump(data_with_custom_props, f)

        test_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text",
                "kwargs": ["category", "priority", "metadata"]
            },
            "data_files": ["data/custom_props.json"]
        }

        # Mock the item state manager
        with patch('potato.flask_server.get_item_state_manager') as mock_ism:
            mock_manager = MagicMock()
            mock_ism.return_value = mock_manager
            mock_manager.has_item.return_value = False

            # This should not raise any exceptions
            try:
                load_instance_data(test_config)
                # Verify that the item was added with all properties
                mock_manager.add_item.assert_called_once()
                call_args = mock_manager.add_item.call_args
                item_data = call_args[0][1]  # Second argument is the item data
                assert "category" in item_data
                assert "priority" in item_data
                assert "metadata" in item_data
            except Exception as e:
                pytest.fail(f"Server custom properties handling failed: {e}")