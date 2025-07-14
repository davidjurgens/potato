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

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

from potato.flask_server import load_instance_data, load_annotation_schematic_data
from potato.server_utils.config_module import init_config, config

def load_config(config_path):
    """Load and validate a config file"""
    class Args:
        pass
    args = Args()
    args.config_file = config_path
    args.verbose = False
    args.very_verbose = False
    args.debug = False
    args.customjs = None
    args.customjs_hostname = None
    args.persist_sessions = False
    init_config(args)
    return config  # Return the global config object

def validate_config(config):
    """Validate a config object"""
    # Basic validation - check required fields
    assert "annotation_schemes" in config
    assert "data_files" in config
    return True


class TestConfigServerIntegration:
    """Test config and server integration."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        # Create temporary directory for test
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = os.path.join(self.temp_dir, 'test_project')
        os.makedirs(self.temp_project_dir, exist_ok=True)

        # Create output directory
        self.output_dir = os.path.join(self.temp_project_dir, 'output')
        os.makedirs(self.output_dir, exist_ok=True)

        yield

        # Cleanup
        shutil.rmtree(self.temp_dir)

    def test_config_loading_integration(self):
        """Test config loading integration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/likert-annotation.yaml')

        # Create args object for init_config
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config
        assert "data_files" in config

    def test_data_loading_integration(self):
        """Test data loading integration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/likert-annotation.yaml')

        # Create args object for init_config
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False

        # Initialize config
        init_config(args)

        # Check that data files are specified
        assert "data_files" in config
        data_files = config["data_files"]
        assert len(data_files) > 0

        # Check that data files exist
        for data_file in data_files:
            data_path = os.path.join(os.path.dirname(config_path), data_file)
            assert os.path.exists(data_path), f"Data file {data_path} does not exist"

    def test_server_integration(self):
        """Test server integration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/likert-annotation.yaml')

        # Create args object for init_config
        class Args:
            pass
        args = Args()
        args.config_file = config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False

        # Initialize config
        init_config(args)

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        # Check that each scheme has required fields
        for scheme in schemes:
            assert "annotation_type" in scheme
            assert "name" in scheme
            assert "description" in scheme

    def test_server_annotation_scheme_loading(self):
        """Test server annotation scheme loading."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/likert-annotation.yaml')
        config = load_config(config_path)

        # Validate annotation schemes
        schemes = config['annotation_schemes']
        assert len(schemes) > 0

        # Check first scheme
        scheme = schemes[0]
        assert 'annotation_type' in scheme
        assert 'name' in scheme
        assert 'description' in scheme

    def test_server_config_with_phases(self):
        """Test server config with phases."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/all-phases-example.yaml')
        config = load_config(config_path)

        # Check phases configuration
        assert 'phases' in config
        phases = config['phases']
        assert len(phases) > 0

    def test_server_config_with_custom_templates(self):
        """Test server config with custom templates."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/dedicated-layout-test.yaml')
        config = load_config(config_path)

        # Check template configuration
        assert 'site_dir' in config
        assert 'base_html_template' in config

    def test_server_config_with_large_datasets(self):
        """Test server config with large datasets."""
        # Create a large test dataset
        large_data = []
        for i in range(100):
            large_data.append({
                "id": f"item_{i}",
                "text": f"This is test item {i} with some content for testing large datasets."
            })

        large_data_file = os.path.join(self.temp_project_dir, 'large_test_data.json')
        with open(large_data_file, 'w') as f:
            json.dump(large_data, f)

        # Create config with large dataset
        config = {
            "annotation_task_name": "Large Dataset Test",
            "task_dir": "output/large-dataset-test",
            "output_annotation_dir": "output/large-dataset-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 50,
            "assignment_strategy": "random",
            "data_files": [large_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "likert",
                    "name": "quality",
                    "description": "Rate the quality of this text:",
                    "size": 5,
                    "labels": ["Poor", "Fair", "Good", "Very Good", "Excellent"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(large_data_file)
        with open(large_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 100

    def test_server_config_with_complex_annotation_schemes(self):
        """Test server config with complex annotation schemes."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/mixed-annotation.yaml')
        config = load_config(config_path)

        # Validate config
        validate_config(config)

        # Check multiple annotation schemes
        schemes = config['annotation_schemes']
        assert len(schemes) > 1

        # Check different annotation types
        annotation_types = [scheme['annotation_type'] for scheme in schemes]
        assert len(set(annotation_types)) > 1

    def test_server_config_with_duplicate_ids(self):
        """Test server config with duplicate IDs."""
        # Create test data with duplicate IDs
        duplicate_data = [
            {"id": "item_1", "text": "First item"},
            {"id": "item_1", "text": "Duplicate item"},
            {"id": "item_2", "text": "Second item"}
        ]

        duplicate_data_file = os.path.join(self.temp_project_dir, 'duplicate_ids.json')
        with open(duplicate_data_file, 'w') as f:
            json.dump(duplicate_data, f)

        # Create config with duplicate data
        config = {
            "annotation_task_name": "Duplicate IDs Test",
            "task_dir": "output/duplicate-ids-test",
            "output_annotation_dir": "output/duplicate-ids-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "data_files": [duplicate_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment of this text?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(duplicate_data_file)
        with open(duplicate_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 3

    def test_server_config_with_malformed_data(self):
        """Test server config with malformed data."""
        # Create malformed test data
        malformed_data = [
            {"id": "item_1", "text": "Valid item"},
            {"id": "item_2"},  # Missing text field
            {"text": "Missing ID"},  # Missing id field
            {"id": "item_3", "text": "Valid item 3"}
        ]

        malformed_data_file = os.path.join(self.temp_project_dir, 'malformed.json')
        with open(malformed_data_file, 'w') as f:
            json.dump(malformed_data, f)

        # Create config with malformed data
        config = {
            "annotation_task_name": "Malformed Data Test",
            "task_dir": "output/malformed-data-test",
            "output_annotation_dir": "output/malformed-data-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "data_files": [malformed_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment of this text?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(malformed_data_file)
        with open(malformed_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 4

    def test_server_config_with_empty_data_files(self):
        """Test server config with empty data files."""
        # Create empty test data
        empty_data = []

        empty_data_file = os.path.join(self.temp_project_dir, 'empty.json')
        with open(empty_data_file, 'w') as f:
            json.dump(empty_data, f)

        # Create config with empty data
        config = {
            "annotation_task_name": "Empty Data Test",
            "task_dir": "output/empty-data-test",
            "output_annotation_dir": "output/empty-data-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "data_files": [empty_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment of this text?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(empty_data_file)
        with open(empty_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 0

    def test_server_config_with_missing_text_key(self):
        """Test server config with missing text key."""
        # Create test data with different text key
        custom_data = [
            {"id": "item_1", "content": "First item content"},
            {"id": "item_2", "content": "Second item content"}
        ]

        custom_data_file = os.path.join(self.temp_project_dir, 'no_text_key.json')
        with open(custom_data_file, 'w') as f:
            json.dump(custom_data, f)

        # Create config with custom text key
        config = {
            "annotation_task_name": "Custom Text Key Test",
            "task_dir": "output/custom-text-key-test",
            "output_annotation_dir": "output/custom-text-key-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "data_files": [custom_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "content"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment of this text?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(custom_data_file)
        with open(custom_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 2
        assert 'content' in loaded_data[0]

    def test_server_config_with_custom_properties(self):
        """Test server config with custom properties."""
        # Create test data with custom properties
        custom_props_data = [
            {
                "id": "item_1",
                "text": "First item",
                "category": "news",
                "source": "reuters"
            },
            {
                "id": "item_2",
                "text": "Second item",
                "category": "opinion",
                "source": "nyt"
            }
        ]

        custom_props_data_file = os.path.join(self.temp_project_dir, 'custom_props.json')
        with open(custom_props_data_file, 'w') as f:
            json.dump(custom_props_data, f)

        # Create config with custom properties
        config = {
            "annotation_task_name": "Custom Properties Test",
            "task_dir": "output/custom-props-test",
            "output_annotation_dir": "output/custom-props-test",
            "output_annotation_format": "jsonl",
            "max_annotations_per_user": 10,
            "assignment_strategy": "fixed_order",
            "data_files": [custom_props_data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "alert_time_each_instance": 10000000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "What is the sentiment of this text?",
                    "labels": ["positive", "negative", "neutral"]
                }
            ],
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None
        }

        # Validate config
        validate_config(config)

        # Check data loading
        assert os.path.exists(custom_props_data_file)
        with open(custom_props_data_file, 'r') as f:
            loaded_data = json.load(f)
        assert len(loaded_data) == 2
        assert 'category' in loaded_data[0]
        assert 'source' in loaded_data[0]

    def test_server_config_error_handling(self):
        """Test server config error handling."""
        # Test with invalid config
        invalid_config = {
            "annotation_task_name": "Invalid Config Test",
            # Missing required fields
        }

        # The validation should catch missing required fields and raise AssertionError
        with pytest.raises(AssertionError) as exc_info:
            validate_config(invalid_config)

        # Should fail on missing annotation_schemes
        assert "annotation_schemes" in str(exc_info.value)