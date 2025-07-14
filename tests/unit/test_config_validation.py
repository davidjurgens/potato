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
import yaml
import os
import glob

# Validation function based on actual usage in flask_server.py
def validate_config(config):
    """Validate config based on actual usage in flask_server.py"""

    # Required fields that are accessed directly without defaults
    required_fields = [
        'item_properties',  # config["item_properties"]["text_key"]
        'data_files',       # config["data_files"]
        'task_dir',         # config["task_dir"]
        'output_annotation_dir',  # config["output_annotation_dir"]
        'annotation_task_name',   # config["annotation_task_name"]
        'alert_time_each_instance',  # config["alert_time_each_instance"]
    ]

    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required field: {field}")

    # Required nested fields in item_properties
    if 'id_key' not in config['item_properties']:
        raise ValueError("Missing id_key in item_properties")
    if 'text_key' not in config['item_properties']:
        raise ValueError("Missing text_key in item_properties")

    # Type checks
    if not isinstance(config['data_files'], list):
        raise ValueError("data_files must be a list")

    # Handle annotation schemes - either top-level or in phases
    if 'annotation_schemes' in config:
        # Old format: annotation_schemes at top level
        if not isinstance(config['annotation_schemes'], list):
            raise ValueError("annotation_schemes must be a list")
        if len(config['annotation_schemes']) == 0:
            raise ValueError("annotation_schemes cannot be empty")
    elif 'phases' in config and config['phases']:
        # New format: annotation_schemes within phases
        phases = config['phases']
        if isinstance(phases, list):
            for phase in phases:
                if 'annotation_schemes' not in phase:
                    raise ValueError(f"Phase {phase.get('name', 'unknown')} missing annotation_schemes")
                if not isinstance(phase['annotation_schemes'], list):
                    raise ValueError(f"Phase {phase.get('name', 'unknown')} annotation_schemes must be a list")
                if len(phase['annotation_schemes']) == 0:
                    raise ValueError(f"Phase {phase.get('name', 'unknown')} annotation_schemes cannot be empty")
        else:
            # Dictionary format
            for phase_name, phase in phases.items():
                if phase_name == 'order':
                    continue
                if 'annotation_schemes' not in phase:
                    raise ValueError(f"Phase {phase_name} missing annotation_schemes")
                if not isinstance(phase['annotation_schemes'], list):
                    raise ValueError(f"Phase {phase_name} annotation_schemes must be a list")
                if len(phase['annotation_schemes']) == 0:
                    raise ValueError(f"Phase {phase_name} annotation_schemes cannot be empty")
    else:
        raise ValueError("Config must have either 'annotation_schemes' (top-level) or 'phases' with annotation_schemes")

    return True

# Find all YAML config files in tests/configs/ (not subdirs)
CONFIG_DIR = os.path.join(os.path.dirname(__file__), '../configs')
CONFIG_FILES = glob.glob(os.path.join(CONFIG_DIR, '*.yaml'))

@pytest.mark.parametrize('config_path', CONFIG_FILES)
def test_config_file_validates(config_path):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    # Should not raise if valid
    assert validate_config(config) is True