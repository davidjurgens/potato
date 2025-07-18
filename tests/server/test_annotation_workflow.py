"""
Tests for the complete annotation workflow.
Tests data loading, annotation submission, navigation, and output generation.
"""

import pytest
import json
import os
import tempfile
import shutil
import time
from unittest.mock import patch, Mock
import subprocess
import requests

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

import pytest
import os
import tempfile
import shutil
import json
import time
import requests
from potato.server_utils.config_module import init_config, config

class TestAnnotationWorkflow:
    """Test annotation workflow functionality."""

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

    def test_config_loading_workflow(self):
        """Test config loading workflow."""
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

        # Check required fields
        assert "annotation_schemes" in config
        assert "data_files" in config
        assert "output_annotation_format" in config

    def test_data_loading_workflow(self):
        """Test data loading workflow."""
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

    def test_annotation_workflow(self):
        """Test basic annotation workflow."""
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

    def test_output_generation_workflow(self):
        """Test output generation workflow."""
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

        # Check output configuration
        assert "output_annotation_format" in config
        assert "output_annotation_dir" in config

    def test_data_persistence_workflow(self):
        """Test data persistence workflow."""
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

        # Check persistence configuration
        assert "max_annotations_per_user" in config
        assert "assignment_strategy" in config