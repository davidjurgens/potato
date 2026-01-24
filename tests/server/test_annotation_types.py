"""
Tests for different annotation types using the simple examples configs.
Tests backend functionality for each annotation type.
"""

import pytest
import json
import os
import tempfile
import shutil
from unittest.mock import patch, Mock
import time
import threading
import subprocess
import requests
import sys

# Add potato to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

from potato.server_utils.config_module import init_config, config
from potato.server_utils.schemas import validate_schema_config
from tests.helpers.test_utils import copy_config_to_test_dir, cleanup_test_directory


class TestAnnotationTypes:
    """Test different annotation types and their configurations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.test_dirs = []
        # Save the original working directory
        self.original_cwd = os.getcwd()
        yield
        # Restore the original working directory before cleanup
        os.chdir(self.original_cwd)
        # Cleanup all test directories
        for test_dir in self.test_dirs:
            cleanup_test_directory(test_dir)

    def _create_args(self, config_path):
        """Create args object for init_config."""
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
        args.port = None  # Port can be specified via CLI or config file
        return args

    def _setup_config(self, original_config_name):
        """Copy config to test directory and return the new path."""
        # Ensure we're in the original working directory
        os.chdir(self.original_cwd)
        original_config_path = os.path.join(os.path.dirname(__file__), f'../configs/{original_config_name}')
        new_config_path, test_dir = copy_config_to_test_dir(original_config_path)
        self.test_dirs.append(test_dir)
        return new_config_path

    def test_likert_annotation_config(self):
        """Test likert annotation configuration."""
        config_path = self._setup_config('likert-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_checkbox_annotation_config(self):
        """Test checkbox annotation configuration."""
        config_path = self._setup_config('simple-check-box.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_slider_annotation_config(self):
        """Test slider annotation configuration."""
        config_path = self._setup_config('slider-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_span_annotation_config(self):
        """Test span annotation configuration."""
        config_path = self._setup_config('span-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_multirate_annotation_config(self):
        """Test multirate annotation configuration."""
        config_path = self._setup_config('multirate-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_text_annotation_config(self):
        """Test text annotation configuration."""
        config_path = self._setup_config('text-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Validate config
        assert config is not None
        assert "annotation_schemes" in config

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_data_loading(self):
        """Test that instance data can be loaded from config."""
        config_path = self._setup_config('likert-annotation.yaml')
        args = self._create_args(config_path)

        # Initialize config
        init_config(args)

        # Check that data files are specified
        assert "data_files" in config
        data_files = config["data_files"]
        assert len(data_files) > 0

        # Check that data files exist (relative to task_dir now)
        task_dir = config.get("task_dir", os.path.dirname(config_path))
        for data_file in data_files:
            data_path = os.path.join(task_dir, data_file)
            assert os.path.exists(data_path), f"Data file {data_path} does not exist"

    def test_all_config_files(self):
        """Test all configuration files in the configs directory."""
        config_dir = os.path.join(os.path.dirname(__file__), '../configs')
        config_files = [f for f in os.listdir(config_dir) if f.endswith('.yaml')]

        assert len(config_files) > 0, "No config files found"

        for config_file in config_files:
            # Skip known incomplete test configs and security test configs
            skip_configs = [
                'span-debug-test.yaml',
                'active-learning-test.yaml',
                'malicious-path-traversal.yaml',  # Security test config
                'malicious-invalid-structure.yaml',  # Security test config
                'training-test.yaml',  # Requires training data file
            ]
            if config_file in skip_configs:
                continue

            config_path = self._setup_config(config_file)
            args = self._create_args(config_path)

            try:
                # Initialize config
                init_config(args)

                # Validate config
                assert config is not None
                assert "annotation_schemes" in config

                # Validate annotation schemes
                schemes = config.get("annotation_schemes", [])
                assert len(schemes) > 0

                for scheme in schemes:
                    validate_schema_config(scheme)
            except Exception as e:
                pytest.fail(f"Failed to load config {config_file}: {e}")
