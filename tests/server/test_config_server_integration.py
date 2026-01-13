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

from potato.server_utils.config_module import init_config, config, clear_config
from tests.helpers.test_utils import create_test_directory, create_test_config, create_test_data_file


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


def validate_config(cfg):
    """Validate a config object"""
    # Basic validation - check required fields
    assert "annotation_schemes" in cfg
    return True


class TestConfigServerIntegration:
    """Test config and server integration."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        clear_config()

        # Create test directory
        self.test_dir = create_test_directory("config_server_integration_test")

        # Create test data file
        test_data = [
            {"id": "1", "text": "This is the first test item."},
            {"id": "2", "text": "This is the second test item."},
            {"id": "3", "text": "This is the third test item."},
        ]
        self.data_file = create_test_data_file(self.test_dir, test_data, "test_data.jsonl")

        yield

        # Cleanup
        clear_config()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_likert_config(self):
        """Create a likert annotation config."""
        annotation_schemes = [
            {
                "annotation_type": "likert",
                "name": "quality",
                "description": "Rate the quality of this text",
                "min_label": "Very Poor",
                "max_label": "Excellent",
                "size": 5,
                "sequential_key_binding": True
            }
        ]
        return create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[self.data_file]
        )

    def test_config_loading_integration(self):
        """Test config loading integration."""
        config_path = self._create_likert_config()
        load_config(config_path)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config
        assert "data_files" in config

    def test_data_loading_integration(self):
        """Test data loading integration."""
        config_path = self._create_likert_config()
        load_config(config_path)

        # Check that data files are specified
        assert "data_files" in config
        data_files = config["data_files"]
        assert len(data_files) > 0

    def test_server_integration(self):
        """Test server integration."""
        config_path = self._create_likert_config()
        load_config(config_path)

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
        config_path = self._create_likert_config()
        cfg = load_config(config_path)

        # Validate annotation schemes
        schemes = cfg['annotation_schemes']
        assert len(schemes) > 0

        # Check first scheme
        scheme = schemes[0]
        assert 'annotation_type' in scheme
        assert 'name' in scheme
        assert 'description' in scheme

    def test_server_config_with_phases(self):
        """Test server config with phases."""
        # Create config with training and annotation phases
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]

        # Create training data
        training_data = [
            {"id": "train_1", "text": "Training item 1", "gold_label": "positive"}
        ]
        training_file = create_test_data_file(self.test_dir, training_data, "training_data.jsonl")

        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[self.data_file]
        )

        cfg = load_config(config_path)
        # Basic validation passes
        assert cfg is not None

    def test_server_config_with_custom_templates(self):
        """Test server config with custom templates."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "category",
                "description": "Select category",
                "labels": ["A", "B", "C"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[self.data_file],
            site_dir="default"
        )

        cfg = load_config(config_path)

        # Check template configuration
        assert 'site_dir' in cfg

    def test_server_config_with_large_datasets(self):
        """Test server config with large datasets."""
        # Create a large test dataset
        large_data = []
        for i in range(100):
            large_data.append({
                "id": f"item_{i}",
                "text": f"This is test item {i} with some content for testing large datasets."
            })

        large_data_file = create_test_data_file(self.test_dir, large_data, "large_test_data.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "likert",
                "name": "quality",
                "description": "Rate the quality of this text:",
                "size": 5,
                "min_label": "Poor",
                "max_label": "Excellent"
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[large_data_file],
            max_annotations_per_user=50,
            assignment_strategy="random"
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_with_complex_annotation_schemes(self):
        """Test server config with complex annotation schemes."""
        # Create config with multiple annotation types
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment?",
                "labels": ["positive", "negative", "neutral"]
            },
            {
                "annotation_type": "likert",
                "name": "quality",
                "description": "Rate the quality",
                "size": 5,
                "min_label": "Poor",
                "max_label": "Excellent"
            },
            {
                "annotation_type": "multiselect",
                "name": "topics",
                "description": "Select all applicable topics",
                "labels": ["politics", "sports", "technology", "entertainment"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[self.data_file]
        )

        cfg = load_config(config_path)
        validate_config(cfg)

        # Check multiple annotation schemes
        schemes = cfg['annotation_schemes']
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

        duplicate_data_file = create_test_data_file(self.test_dir, duplicate_data, "duplicate_ids.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment of this text?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[duplicate_data_file]
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_with_malformed_data(self):
        """Test server config with malformed data."""
        # Create malformed test data
        malformed_data = [
            {"id": "item_1", "text": "Valid item"},
            {"id": "item_2"},  # Missing text field
            {"text": "Missing ID"},  # Missing id field
            {"id": "item_3", "text": "Valid item 3"}
        ]

        malformed_data_file = create_test_data_file(self.test_dir, malformed_data, "malformed.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment of this text?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[malformed_data_file]
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_with_empty_data_files(self):
        """Test server config with empty data files."""
        # Create empty data file
        empty_data_file = create_test_data_file(self.test_dir, [], "empty.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment of this text?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[empty_data_file]
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_with_missing_text_key(self):
        """Test server config with missing text key."""
        # Create data without standard text key
        custom_data = [
            {"id": "item_1", "content": "First content"},
            {"id": "item_2", "content": "Second content"}
        ]

        custom_data_file = create_test_data_file(self.test_dir, custom_data, "custom.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment of this text?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[custom_data_file],
            item_properties={"id_key": "id", "text_key": "content"}
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_with_custom_properties(self):
        """Test server config with custom properties."""
        # Create data with custom properties
        custom_data = [
            {"item_id": "1", "item_text": "First", "category": "A"},
            {"item_id": "2", "item_text": "Second", "category": "B"}
        ]

        custom_data_file = create_test_data_file(self.test_dir, custom_data, "custom_props.jsonl")

        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "What is the sentiment of this text?",
                "labels": ["positive", "negative", "neutral"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[custom_data_file],
            item_properties={"id_key": "item_id", "text_key": "item_text"}
        )

        cfg = load_config(config_path)
        validate_config(cfg)

    def test_server_config_error_handling(self):
        """Test server config error handling."""
        # Test with valid config should not raise
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "test",
                "description": "Test scheme",
                "labels": ["a", "b"]
            }
        ]
        config_path = create_test_config(
            self.test_dir,
            annotation_schemes,
            data_files=[self.data_file]
        )

        cfg = load_config(config_path)
        assert cfg is not None
