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

# Add potato to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'potato'))

import pytest
import os
import tempfile
import shutil
import json
from potato.server_utils.config_module import init_config, config
from potato.server_utils.schemas import validate_schema_config

class TestAnnotationTypes:
    """Test different annotation types and their configurations."""

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

    def test_likert_annotation_config(self):
        """Test likert annotation configuration."""
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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_checkbox_annotation_config(self):
        """Test checkbox annotation configuration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/simple-check-box.yaml')

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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_slider_annotation_config(self):
        """Test slider annotation configuration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/slider-annotation.yaml')

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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_span_annotation_config(self):
        """Test span annotation configuration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/span-annotation.yaml')

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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_multirate_annotation_config(self):
        """Test multirate annotation configuration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/multirate-annotation.yaml')

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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_text_annotation_config(self):
        """Test text annotation configuration."""
        config_path = os.path.join(os.path.dirname(__file__), '../configs/text-annotation.yaml')

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

        # Validate annotation schemes
        schemes = config.get("annotation_schemes", [])
        assert len(schemes) > 0

        for scheme in schemes:
            validate_schema_config(scheme)

    def test_data_loading(self):
        """Test that instance data can be loaded from config."""
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

    def test_all_config_files(self):
        """Test all configuration files in the configs directory."""
        config_dir = os.path.join(os.path.dirname(__file__), '../configs')
        config_files = [f for f in os.listdir(config_dir) if f.endswith('.yaml')]

        assert len(config_files) > 0, "No config files found"

        for config_file in config_files:
            config_path = os.path.join(config_dir, config_file)

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

            # Validate annotation schemes
            schemes = config.get("annotation_schemes", [])
            assert len(schemes) > 0

            for scheme in schemes:
                validate_schema_config(scheme)
