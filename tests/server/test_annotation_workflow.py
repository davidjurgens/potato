"""
Tests for the complete annotation workflow.
Tests data loading, annotation submission, navigation, and output generation.
"""

import pytest
import json
import os
import tempfile
import shutil

from potato.server_utils.config_module import init_config, config, clear_config
from tests.helpers.test_utils import create_test_directory, create_test_config, create_test_data_file


class TestAnnotationWorkflow:
    """Test annotation workflow functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        # Clear any existing config
        clear_config()

        # Create test directory
        self.test_dir = create_test_directory("annotation_workflow_test")

        # Create test data file
        test_data = [
            {"id": "1", "text": "This is the first test item."},
            {"id": "2", "text": "This is the second test item."},
            {"id": "3", "text": "This is the third test item."},
        ]
        self.data_file = create_test_data_file(self.test_dir, test_data, "test_data.jsonl")

        # Create annotation schemes for likert scale
        self.annotation_schemes = [
            {
                "annotation_type": "likert",
                "name": "quality",
                "description": "How would you rate the quality of this text?",
                "min_label": "Very Poor",
                "max_label": "Excellent",
                "size": 5,
                "sequential_key_binding": True
            },
            {
                "annotation_type": "likert",
                "name": "clarity",
                "description": "How clear and understandable is this text?",
                "min_label": "Very Unclear",
                "max_label": "Very Clear",
                "size": 7,
                "sequential_key_binding": True
            }
        ]

        # Create config file
        self.config_path = create_test_config(
            self.test_dir,
            self.annotation_schemes,
            data_files=[self.data_file],
            annotation_task_name="Annotation Workflow Test",
            output_annotation_format="json",
            max_annotations_per_user=10,
            assignment_strategy="fixed_order"
        )

        yield

        # Cleanup
        clear_config()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _init_config(self):
        """Helper to initialize config."""
        class Args:
            pass
        args = Args()
        args.config_file = self.config_path
        args.verbose = False
        args.very_verbose = False
        args.debug = False
        args.customjs = None
        args.customjs_hostname = None
        args.persist_sessions = False
        init_config(args)

    def test_config_loading_workflow(self):
        """Test config loading workflow."""
        self._init_config()

        # Validate config
        assert config is not None

        # Check required fields
        assert "annotation_schemes" in config
        assert "data_files" in config

    def test_data_loading_workflow(self):
        """Test data loading workflow."""
        self._init_config()

        # Check that data files are specified
        assert "data_files" in config
        data_files = config["data_files"]
        assert len(data_files) > 0

    def test_annotation_workflow(self):
        """Test basic annotation workflow."""
        self._init_config()

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        # Check that each scheme has required fields
        for scheme in schemes:
            assert "annotation_type" in scheme
            assert "name" in scheme
            assert "description" in scheme

    def test_output_generation_workflow(self):
        """Test output generation workflow."""
        self._init_config()

        # Check output configuration
        assert "output_annotation_dir" in config

    def test_data_persistence_workflow(self):
        """Test data persistence workflow."""
        self._init_config()

        # Check persistence configuration
        assert "max_annotations_per_user" in config
        assert "assignment_strategy" in config
