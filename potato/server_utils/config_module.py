"""
Config module with enhanced security validation and error handling.
"""

import yaml
import os
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
import json

config = {}


def clear_config():
    """Clear the global config dictionary. Used for testing to ensure clean state."""
    global config
    config.clear()


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig()


class ConfigValidationError(Exception):
    """Custom exception for configuration validation errors."""
    pass


class ConfigSecurityError(Exception):
    """Custom exception for configuration security violations."""
    pass


def validate_path_security(path: str, base_dir: str, project_dir: str = None) -> str:
    """
    Validate that a path is secure and contained within the base directory.

    Args:
        path: The path to validate
        base_dir: The base directory that should contain the path
        project_dir: The project directory for final security check (if different from base_dir)

    Returns:
        The normalized absolute path if valid

    Raises:
        ConfigSecurityError: If the path is not secure
    """
    # Check for encoded traversal patterns before normalization
    if '....' in path or '..%2F' in path or '..%5C' in path:
        raise ConfigSecurityError(f"Encoded path traversal detected in '{path}'. Encoded traversal patterns are not allowed for security reasons.")

    # Normalize the path
    normalized_path = os.path.normpath(path)

    # Check for malicious path traversal attempts
    # Allow legitimate relative paths like "../data/file.json" but block excessive traversal
    path_parts = normalized_path.split(os.sep)
    if path_parts.count('..') > 2:  # Allow up to 2 levels of ".." for legitimate relative paths
        raise ConfigSecurityError(f"Excessive path traversal detected in '{path}'. Too many '..' components for security reasons.")

    # Check for absolute paths that might escape the project directory
    if os.path.isabs(normalized_path):
        # Only allow absolute paths that are within the base directory
        try:
            real_path = os.path.realpath(normalized_path)
            real_base = os.path.realpath(base_dir)
            if not real_path.startswith(real_base):
                raise ConfigSecurityError(f"Path '{path}' resolves to '{real_path}' which is outside the project directory '{real_base}'")
        except (OSError, ValueError) as e:
            raise ConfigSecurityError(f"Invalid path '{path}': {str(e)}")

    # Resolve relative paths against base directory
    if not os.path.isabs(normalized_path):
        resolved_path = os.path.join(base_dir, normalized_path)
        normalized_path = os.path.normpath(resolved_path)

    # Final security check - ensure the resolved path is within the project directory
    try:
        real_path = os.path.realpath(normalized_path)
        # Use project_dir for final check if provided, otherwise use base_dir
        check_dir = project_dir if project_dir else base_dir
        real_check_dir = os.path.realpath(check_dir)
        if not real_path.startswith(real_check_dir):
            raise ConfigSecurityError(f"Path '{path}' resolves to '{real_path}' which is outside the project directory '{real_check_dir}'")
    except (OSError, ValueError) as e:
        raise ConfigSecurityError(f"Invalid path '{path}': {str(e)}")

    return normalized_path


def validate_yaml_structure(config_data: Dict[str, Any], project_dir: str = None, config_file_dir: str = None) -> None:
    """
    Validate the structure and content of the YAML configuration.

    Args:
        config_data: The parsed YAML configuration
        project_dir: The project directory
        config_file_dir: The directory containing the config file

    Raises:
        ConfigValidationError: If the configuration is invalid
    """
    if not isinstance(config_data, dict):
        raise ConfigValidationError("Configuration must be a YAML object (dictionary)")

    # Required fields validation
    required_fields = [
        'item_properties',
        'data_files',
        'task_dir',
        'output_annotation_dir',
        'annotation_task_name',
        'alert_time_each_instance'
    ]

    missing_fields = [field for field in required_fields if field not in config_data]
    if missing_fields:
        raise ConfigValidationError(f"Missing required configuration fields: {', '.join(missing_fields)}")

    # Validate item_properties
    item_properties = config_data.get('item_properties', {})
    if not isinstance(item_properties, dict):
        raise ConfigValidationError("item_properties must be a dictionary")

    required_item_props = ['id_key', 'text_key']
    missing_item_props = [prop for prop in required_item_props if prop not in item_properties]
    if missing_item_props:
        raise ConfigValidationError(f"Missing required item_properties: {', '.join(missing_item_props)}")

    # Validate data_files (required unless data_directory is provided)
    data_files = config_data.get('data_files', [])
    data_directory = config_data.get('data_directory')

    if not isinstance(data_files, list):
        raise ConfigValidationError("data_files must be a list")

    # data_files can be empty if data_directory is configured
    if not data_files and not data_directory:
        raise ConfigValidationError("Either data_files or data_directory must be configured")

    # Validate data_directory config if present
    validate_data_directory_config(config_data)

    # Validate annotation schemes
    validate_annotation_schemes(config_data)

    # Validate training configuration if present
    validate_training_config(config_data, project_dir, config_file_dir)

    # Validate database configuration if present
    if 'database' in config_data:
        validate_database_config(config_data['database'])

    # Validate active learning configuration if present
    validate_active_learning_config(config_data)

    # Validate AI support configuration if present
    validate_ai_support_config(config_data)


def validate_annotation_schemes(config_data: Dict[str, Any]) -> None:
    """
    Validate annotation schemes configuration.

    Args:
        config_data: The configuration data

    Raises:
        ConfigValidationError: If annotation schemes are invalid
    """
    has_top_level = 'annotation_schemes' in config_data
    has_phases = 'phases' in config_data and config_data['phases']

    # Check for conflicting annotation_schemes locations
    if has_top_level and has_phases:
        # Check if any phase also has annotation_schemes
        phases = config_data['phases']
        phases_with_schemes = []
        if isinstance(phases, list):
            phases_with_schemes = [
                phase.get('name', f'phase[{i}]')
                for i, phase in enumerate(phases)
                if 'annotation_schemes' in phase
            ]
        elif isinstance(phases, dict):
            phases_with_schemes = [
                name for name, phase in phases.items()
                if name != 'order' and isinstance(phase, dict) and 'annotation_schemes' in phase
            ]

        if phases_with_schemes:
            raise ConfigValidationError(
                f"Configuration has both top-level 'annotation_schemes' and phase-level "
                f"'annotation_schemes' in: {', '.join(phases_with_schemes)}. "
                f"Use only one location to avoid confusion."
            )

    # Check for annotation schemes in different formats
    if has_top_level:
        schemes = config_data['annotation_schemes']
        if not isinstance(schemes, list):
            raise ConfigValidationError("annotation_schemes must be a list")
        if not schemes:
            raise ConfigValidationError("annotation_schemes cannot be empty")

        for i, scheme in enumerate(schemes):
            validate_single_annotation_scheme(scheme, f"annotation_schemes[{i}]")

    elif 'phases' in config_data and config_data['phases']:
        phases = config_data['phases']
        if isinstance(phases, list):
            for i, phase in enumerate(phases):
                if 'annotation_schemes' not in phase:
                    raise ConfigValidationError(f"Phase {phase.get('name', f'[{i}]')} missing annotation_schemes")
                schemes = phase['annotation_schemes']
                if not isinstance(schemes, list):
                    raise ConfigValidationError(f"Phase {phase.get('name', f'[{i}]')} annotation_schemes must be a list")
                if not schemes:
                    raise ConfigValidationError(f"Phase {phase.get('name', f'[{i}]')} annotation_schemes cannot be empty")

                for j, scheme in enumerate(schemes):
                    validate_single_annotation_scheme(scheme, f"phases[{i}].annotation_schemes[{j}]")
        else:
            # Dictionary format
            for phase_name, phase in phases.items():
                if phase_name == 'order':
                    continue
                if 'annotation_schemes' not in phase:
                    raise ConfigValidationError(f"Phase {phase_name} missing annotation_schemes")
                schemes = phase['annotation_schemes']
                if not isinstance(schemes, list):
                    raise ConfigValidationError(f"Phase {phase_name} annotation_schemes must be a list")
                if not schemes:
                    raise ConfigValidationError(f"Phase {phase_name} annotation_schemes cannot be empty")

                for j, scheme in enumerate(schemes):
                    validate_single_annotation_scheme(scheme, f"phases.{phase_name}.annotation_schemes[{j}]")
    else:
        raise ConfigValidationError("Config must have either 'annotation_schemes' (top-level) or 'phases' with annotation_schemes")


def validate_single_annotation_scheme(scheme: Dict[str, Any], path: str) -> None:
    """
    Validate a single annotation scheme.

    Args:
        scheme: The annotation scheme to validate
        path: The path in the config for error reporting

    Raises:
        ConfigValidationError: If the scheme is invalid
    """
    if not isinstance(scheme, dict):
        raise ConfigValidationError(f"{path} must be a dictionary")

    required_fields = ['annotation_type', 'name', 'description']
    missing_fields = [field for field in required_fields if field not in scheme]
    if missing_fields:
        raise ConfigValidationError(f"{path} missing required fields: {', '.join(missing_fields)}")

    # Validate annotation_type
    # Note: Keep in sync with potato.server_utils.schemas.registry
    valid_types = ['radio', 'multiselect', 'likert', 'text', 'slider', 'span', 'select', 'number', 'multirate', 'pure_display', 'video', 'image_annotation', 'audio_annotation']
    if scheme['annotation_type'] not in valid_types:
        raise ConfigValidationError(f"{path}.annotation_type must be one of: {', '.join(valid_types)}")

    # Type-specific validation
    annotation_type = scheme['annotation_type']
    if annotation_type in ['radio', 'multiselect', 'select']:
        if 'labels' not in scheme:
            raise ConfigValidationError(f"{path} missing 'labels' field for {annotation_type} annotation type")
        if not isinstance(scheme['labels'], list):
            raise ConfigValidationError(f"{path}.labels must be a list")
        if not scheme['labels']:
            raise ConfigValidationError(f"{path}.labels cannot be empty")

    elif annotation_type == 'likert':
        # Likert can use labels (falls back to radio) or min_label/max_label/size
        if 'labels' not in scheme:
            required_likert_fields = ['min_label', 'max_label', 'size']
            missing_likert_fields = [field for field in required_likert_fields if field not in scheme]
            if missing_likert_fields:
                raise ConfigValidationError(f"{path} missing required fields for likert: {', '.join(missing_likert_fields)}")

            if not isinstance(scheme['size'], int) or scheme['size'] < 2:
                raise ConfigValidationError(f"{path}.size must be an integer >= 2")

    elif annotation_type == 'slider':
        # Slider can use labels (falls back to radio) or min_value/max_value
        if 'labels' not in scheme:
            required_slider_fields = ['min_value', 'max_value', 'starting_value']
            missing_slider_fields = [field for field in required_slider_fields if field not in scheme]
            if missing_slider_fields:
                raise ConfigValidationError(f"{path} missing required fields for slider: {', '.join(missing_slider_fields)}")

            if not isinstance(scheme['min_value'], (int, float)) or not isinstance(scheme['max_value'], (int, float)):
                raise ConfigValidationError(f"{path}.min_value and max_value must be numbers")
            if scheme['min_value'] >= scheme['max_value']:
                raise ConfigValidationError(f"{path}.min_value must be less than max_value")

    elif annotation_type == 'span':
        if 'labels' not in scheme:
            raise ConfigValidationError(f"{path} missing 'labels' field for span annotation type")
        if not isinstance(scheme['labels'], list):
            raise ConfigValidationError(f"{path}.labels must be a list")
        if not scheme['labels']:
            raise ConfigValidationError(f"{path}.labels cannot be empty")

    elif annotation_type == 'multirate':
        required_multirate_fields = ['options', 'labels']
        missing_multirate_fields = [field for field in required_multirate_fields if field not in scheme]
        if missing_multirate_fields:
            raise ConfigValidationError(f"{path} missing required fields for multirate: {', '.join(missing_multirate_fields)}")

        if not isinstance(scheme['options'], list):
            raise ConfigValidationError(f"{path}.options must be a list")
        if not scheme['options']:
            raise ConfigValidationError(f"{path}.options cannot be empty")

        if not isinstance(scheme['labels'], list):
            raise ConfigValidationError(f"{path}.labels must be a list")
        if not scheme['labels']:
            raise ConfigValidationError(f"{path}.labels cannot be empty")

    elif annotation_type == 'image_annotation':
        # Image annotation requires tools and labels
        if 'tools' not in scheme:
            raise ConfigValidationError(f"{path} missing 'tools' field for image_annotation type")
        if not isinstance(scheme['tools'], list):
            raise ConfigValidationError(f"{path}.tools must be a list")
        if not scheme['tools']:
            raise ConfigValidationError(f"{path}.tools cannot be empty")

        # Validate tools
        valid_tools = ['bbox', 'polygon', 'freeform', 'landmark']
        invalid_tools = [t for t in scheme['tools'] if t not in valid_tools]
        if invalid_tools:
            raise ConfigValidationError(f"{path}.tools contains invalid values: {invalid_tools}. Valid tools are: {valid_tools}")

        if 'labels' not in scheme:
            raise ConfigValidationError(f"{path} missing 'labels' field for image_annotation type")
        if not isinstance(scheme['labels'], list):
            raise ConfigValidationError(f"{path}.labels must be a list")
        if not scheme['labels']:
            raise ConfigValidationError(f"{path}.labels cannot be empty")

        # Validate optional numeric fields
        if 'min_annotations' in scheme:
            if not isinstance(scheme['min_annotations'], int) or scheme['min_annotations'] < 0:
                raise ConfigValidationError(f"{path}.min_annotations must be a non-negative integer")

        if 'max_annotations' in scheme and scheme['max_annotations'] is not None:
            if not isinstance(scheme['max_annotations'], int) or scheme['max_annotations'] < 1:
                raise ConfigValidationError(f"{path}.max_annotations must be a positive integer or null")

    elif annotation_type == 'audio_annotation':
        # Validate mode
        valid_modes = ['label', 'questions', 'both']
        mode = scheme.get('mode', 'label')
        if mode not in valid_modes:
            raise ConfigValidationError(f"{path}.mode must be one of: {valid_modes}")

        # Validate labels for label/both modes
        if mode in ['label', 'both']:
            if 'labels' not in scheme:
                raise ConfigValidationError(f"{path} missing 'labels' field for audio_annotation mode '{mode}'")
            if not isinstance(scheme['labels'], list):
                raise ConfigValidationError(f"{path}.labels must be a list")
            if not scheme['labels']:
                raise ConfigValidationError(f"{path}.labels cannot be empty for mode '{mode}'")

        # Validate segment_schemes for questions/both modes
        if mode in ['questions', 'both']:
            if 'segment_schemes' not in scheme:
                raise ConfigValidationError(f"{path} missing 'segment_schemes' field for audio_annotation mode '{mode}'")
            if not isinstance(scheme['segment_schemes'], list):
                raise ConfigValidationError(f"{path}.segment_schemes must be a list")
            if not scheme['segment_schemes']:
                raise ConfigValidationError(f"{path}.segment_schemes cannot be empty for mode '{mode}'")

        # Validate optional numeric fields
        if 'min_segments' in scheme:
            if not isinstance(scheme['min_segments'], int) or scheme['min_segments'] < 0:
                raise ConfigValidationError(f"{path}.min_segments must be a non-negative integer")

        if 'max_segments' in scheme and scheme['max_segments'] is not None:
            if not isinstance(scheme['max_segments'], int) or scheme['max_segments'] < 1:
                raise ConfigValidationError(f"{path}.max_segments must be a positive integer or null")


def validate_data_directory_config(config_data: Dict[str, Any]) -> None:
    """
    Validate data_directory configuration.

    This function validates the directory watching configuration options:
    - data_directory: Path to the directory containing data files
    - watch_data_directory: Whether to watch for changes (default: False)
    - watch_poll_interval: Seconds between scans (default: 5.0)

    Args:
        config_data: The configuration data

    Raises:
        ConfigValidationError: If the configuration is invalid
    """
    if "data_directory" not in config_data:
        return  # data_directory is optional

    data_directory = config_data["data_directory"]

    # Validate data_directory is a string
    if not isinstance(data_directory, str):
        raise ConfigValidationError("data_directory must be a string path")

    if not data_directory.strip():
        raise ConfigValidationError("data_directory cannot be empty")

    # Validate watch_data_directory if present
    if "watch_data_directory" in config_data:
        watch_enabled = config_data["watch_data_directory"]
        if not isinstance(watch_enabled, bool):
            raise ConfigValidationError("watch_data_directory must be a boolean (true/false)")

    # Validate watch_poll_interval if present
    if "watch_poll_interval" in config_data:
        interval = config_data["watch_poll_interval"]
        if not isinstance(interval, (int, float)):
            raise ConfigValidationError("watch_poll_interval must be a number")
        if interval < 1.0:
            raise ConfigValidationError("watch_poll_interval must be at least 1.0 seconds")
        if interval > 3600:
            raise ConfigValidationError("watch_poll_interval cannot exceed 3600 seconds (1 hour)")


def validate_database_config(db_config: Dict[str, Any]) -> None:
    """
    Validate database configuration.

    Args:
        db_config: The database configuration

    Raises:
        ConfigValidationError: If the database configuration is invalid
    """
    if not isinstance(db_config, dict):
        raise ConfigValidationError("database configuration must be a dictionary")

    required_fields = ['type', 'host', 'database', 'username']
    missing_fields = [field for field in required_fields if field not in db_config]
    if missing_fields:
        raise ConfigValidationError(f"Missing required database fields: {', '.join(missing_fields)}")

    valid_types = ['mysql', 'file']
    if db_config['type'] not in valid_types:
        raise ConfigValidationError(f"Unsupported database type: {db_config['type']}. Must be one of: {', '.join(valid_types)}")

    # Validate MySQL-specific fields
    if db_config['type'] == 'mysql':
        if 'password' not in db_config:
            raise ConfigValidationError("MySQL database requires password")

        # Validate port if specified
        if 'port' in db_config:
            try:
                port = int(db_config['port'])
                if port < 1 or port > 65535:
                    raise ConfigValidationError("Database port must be between 1 and 65535")
            except (ValueError, TypeError):
                raise ConfigValidationError("Database port must be a valid integer")


def validate_file_paths(config_data: Dict[str, Any], project_dir: str, config_file_dir: str = None) -> None:
    """
    Validate that all file paths in the configuration are secure and exist.

    Args:
        config_data: The configuration data
        project_dir: The project directory
        config_file_dir: The directory containing the config file (for relative path resolution)

    Raises:
        ConfigSecurityError: If any file paths are not secure
        ConfigValidationError: If required files don't exist
    """
    # Get the task_dir from config
    task_dir = config_data.get('task_dir')
    if not task_dir:
        raise ConfigValidationError("task_dir is required in configuration")

    # Validate task_dir exists and is secure
    try:
        validated_task_dir = validate_path_security(task_dir, project_dir)
        # Don't require task_dir to exist - it's often an output directory that will be created
        # Only validate that it's a valid path
    except ConfigSecurityError as e:
        raise ConfigSecurityError(f"task_dir: {str(e)}")

    # Use task_dir as the base for resolving relative paths in the config
    base_dir = validated_task_dir

    # Validate data files
    data_files = config_data.get('data_files', [])
    for i, data_file in enumerate(data_files):
        # Skip validation for special values
        if data_file in [None, "null", "default"]:
            continue

        try:
            validated_path = validate_path_security(data_file, base_dir, project_dir)
            if not os.path.exists(validated_path):
                raise ConfigValidationError(f"Data file not found: {data_file} (resolved to: {validated_path})")
        except ConfigSecurityError as e:
            raise ConfigSecurityError(f"Data file {i}: {str(e)}")

    # Validate data_directory if configured
    if 'data_directory' in config_data:
        data_directory = config_data['data_directory']
        # Skip validation for special values
        if data_directory not in [None, "null", "default"]:
            try:
                validated_dir = validate_path_security(data_directory, base_dir, project_dir)
                if not os.path.exists(validated_dir):
                    raise ConfigValidationError(f"data_directory not found: {data_directory} (resolved to: {validated_dir})")
                if not os.path.isdir(validated_dir):
                    raise ConfigValidationError(f"data_directory is not a directory: {data_directory} (resolved to: {validated_dir})")
            except ConfigSecurityError as e:
                raise ConfigSecurityError(f"data_directory: {str(e)}")

    # Validate output_annotation_dir
    if 'output_annotation_dir' in config_data:
        output_dir = config_data['output_annotation_dir']
        # Skip validation for special values
        if output_dir not in [None, "null", "default"]:
            try:
                validate_path_security(output_dir, project_dir)
            except ConfigSecurityError as e:
                raise ConfigSecurityError(f"output_annotation_dir: {str(e)}")

    # Validate site_dir
    if 'site_dir' in config_data:
        site_dir = config_data['site_dir']
        # Skip validation for special values
        if site_dir not in [None, "null", "default"]:
            try:
                validate_path_security(site_dir, base_dir, project_dir)
            except ConfigSecurityError as e:
                raise ConfigSecurityError(f"site_dir: {str(e)}")

    # Validate custom_ds
    if 'custom_ds' in config_data:
        custom_ds = config_data['custom_ds']
        # Skip validation for special values
        if custom_ds not in [None, "null", "default"]:
            try:
                validate_path_security(custom_ds, base_dir, project_dir)
            except ConfigSecurityError as e:
                raise ConfigSecurityError(f"custom_ds: {str(e)}")


def validate_training_config(config_data: Dict[str, Any], project_dir: str, config_file_dir: str = None) -> None:
    """
    Validate training configuration.

    Args:
        config_data: The configuration data
        project_dir: The project directory
        config_file_dir: The directory containing the config file

    Raises:
        ConfigValidationError: If training configuration is invalid
        ConfigSecurityError: If training data file path is not secure
    """
    if 'training' not in config_data:
        return  # Training is optional

    training_config = config_data['training']
    if not isinstance(training_config, dict):
        raise ConfigValidationError("training configuration must be a dictionary")

    # Validate enabled flag
    if 'enabled' in training_config:
        if not isinstance(training_config['enabled'], bool):
            raise ConfigValidationError("training.enabled must be a boolean")

    # If training is disabled or not specified, skip further validation
    if not training_config.get('enabled', False):
        return

    # Validate training data file
    if 'data_file' not in training_config:
        raise ConfigValidationError("training.data_file is required when training is enabled")

    data_file = training_config['data_file']
    if not isinstance(data_file, str):
        raise ConfigValidationError("training.data_file must be a string")

    # Validate training data file path security and existence
    try:
        base_dir = config_file_dir if config_file_dir else project_dir
        validated_path = validate_path_security(data_file, base_dir, project_dir)
        if not os.path.exists(validated_path):
            raise ConfigValidationError(f"Training data file not found: {data_file} (resolved to: {validated_path})")
    except ConfigSecurityError as e:
        raise ConfigSecurityError(f"training.data_file: {str(e)}")

    # Validate annotation schemes
    if 'annotation_schemes' in training_config:
        schemes = training_config['annotation_schemes']
        if not isinstance(schemes, list):
            raise ConfigValidationError("training.annotation_schemes must be a list")
        if not schemes:
            raise ConfigValidationError("training.annotation_schemes cannot be empty")

        for i, scheme in enumerate(schemes):
            if isinstance(scheme, str):
                # String reference to existing scheme - validate it's a valid string
                if not scheme.strip():
                    raise ConfigValidationError(f"training.annotation_schemes[{i}] cannot be empty")
            elif isinstance(scheme, dict):
                # Full scheme dictionary - validate it
                validate_single_annotation_scheme(scheme, f"training.annotation_schemes[{i}]")
            else:
                raise ConfigValidationError(f"training.annotation_schemes[{i}] must be a string or dictionary")

    # Validate passing criteria
    if 'passing_criteria' in training_config:
        criteria = training_config['passing_criteria']
        if not isinstance(criteria, dict):
            raise ConfigValidationError("training.passing_criteria must be a dictionary")

        # Validate min_correct
        if 'min_correct' in criteria:
            min_correct = criteria['min_correct']
            if not isinstance(min_correct, int) or min_correct < 1:
                raise ConfigValidationError("training.passing_criteria.min_correct must be a positive integer")

        # Validate max_attempts
        if 'max_attempts' in criteria:
            max_attempts = criteria['max_attempts']
            if not isinstance(max_attempts, int) or max_attempts < 1:
                raise ConfigValidationError("training.passing_criteria.max_attempts must be a positive integer")

        # Validate require_all_correct
        if 'require_all_correct' in criteria:
            if not isinstance(criteria['require_all_correct'], bool):
                raise ConfigValidationError("training.passing_criteria.require_all_correct must be a boolean")

    # Validate feedback settings
    if 'feedback' in training_config:
        feedback = training_config['feedback']
        if not isinstance(feedback, dict):
            raise ConfigValidationError("training.feedback must be a dictionary")

        # Validate show_explanations
        if 'show_explanations' in feedback:
            if not isinstance(feedback['show_explanations'], bool):
                raise ConfigValidationError("training.feedback.show_explanations must be a boolean")

        # Validate allow_retry
        if 'allow_retry' in feedback:
            if not isinstance(feedback['allow_retry'], bool):
                raise ConfigValidationError("training.feedback.allow_retry must be a boolean")

    # Validate failure action
    if 'failure_action' in training_config:
        failure_action = training_config['failure_action']
        valid_actions = ['move_to_done', 'repeat_training']
        if failure_action not in valid_actions:
            raise ConfigValidationError(f"training.failure_action must be one of: {', '.join(valid_actions)}")


def validate_training_data_file(data_file_path: str, annotation_schemes: List[Dict[str, Any]]) -> None:
    """
    Validate training data file format and consistency.

    Args:
        data_file_path: Path to the training data file
        annotation_schemes: List of annotation schemes to validate against

    Raises:
        ConfigValidationError: If training data is invalid
    """
    try:
        with open(data_file_path, 'r', encoding='utf-8') as f:
            training_data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ConfigValidationError(f"Training data file is not valid JSON: {str(e)}")
    except FileNotFoundError:
        raise ConfigValidationError(f"Training data file not found: {data_file_path}")

    if not isinstance(training_data, dict):
        raise ConfigValidationError("Training data must be a JSON object")

    if 'training_instances' not in training_data:
        raise ConfigValidationError("Training data must contain 'training_instances' field")

    training_instances = training_data['training_instances']
    if not isinstance(training_instances, list):
        raise ConfigValidationError("training_instances must be a list")

    if not training_instances:
        raise ConfigValidationError("training_instances cannot be empty")

    # Create a mapping of scheme names for validation
    scheme_names = {scheme['name'] for scheme in annotation_schemes}

    for i, instance in enumerate(training_instances):
        if not isinstance(instance, dict):
            raise ConfigValidationError(f"Training instance {i} must be a dictionary")

        # Validate required fields
        required_fields = ['id', 'text', 'correct_answers']
        missing_fields = [field for field in required_fields if field not in instance]
        if missing_fields:
            raise ConfigValidationError(f"Training instance {i} missing required fields: {', '.join(missing_fields)}")

        # Validate id
        if not isinstance(instance['id'], str):
            raise ConfigValidationError(f"Training instance {i}.id must be a string")

        # Validate text
        if not isinstance(instance['text'], str):
            raise ConfigValidationError(f"Training instance {i}.text must be a string")

        # Validate correct_answers
        correct_answers = instance['correct_answers']
        if not isinstance(correct_answers, dict):
            raise ConfigValidationError(f"Training instance {i}.correct_answers must be a dictionary")

        # Validate that all correct_answers correspond to annotation schemes
        for scheme_name, answer in correct_answers.items():
            if scheme_name not in scheme_names:
                raise ConfigValidationError(f"Training instance {i}.correct_answers contains unknown scheme: {scheme_name}")

        # Validate explanation if present
        if 'explanation' in instance:
            if not isinstance(instance['explanation'], str):
                raise ConfigValidationError(f"Training instance {i}.explanation must be a string")


def load_and_validate_config(config_file: str, project_dir: str) -> Dict[str, Any]:
    """
    Load and validate a YAML configuration file with security checks.

    Args:
        config_file: Path to the configuration file
        project_dir: The project directory

    Returns:
        The validated configuration dictionary

    Raises:
        ConfigSecurityError: If the configuration file is not secure
        ConfigValidationError: If the configuration is invalid
        FileNotFoundError: If the configuration file doesn't exist
    """
    # Validate the config file path itself
    try:
        validated_config_path = validate_path_security(config_file, project_dir)
    except ConfigSecurityError as e:
        raise ConfigSecurityError(f"Configuration file path: {str(e)}")

    if not os.path.exists(validated_config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    # Load and parse YAML
    try:
        with open(validated_config_path, 'r', encoding='utf-8') as file_p:
            config_data = yaml.safe_load(file_p)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML format in {config_file}: {str(e)}")
    except UnicodeDecodeError as e:
        raise ConfigValidationError(f"Invalid file encoding in {config_file}: {str(e)}")
    except Exception as e:
        raise ConfigValidationError(f"Error reading configuration file {config_file}: {str(e)}")

    # Get the directory containing the config file for relative path resolution
    config_file_dir = os.path.dirname(validated_config_path)

    # Validate the configuration structure
    validate_yaml_structure(config_data, project_dir, config_file_dir)

    # Validate file paths
    validate_file_paths(config_data, project_dir, config_file_dir)

    return config_data


def init_config(args):
    global config

    project_dir = os.getcwd() #get the current working dir as the default project_dir
    config_file = None
    config_file_dir = None

    try:
        # if the .yaml config file is given, directly use it
        if args.config_file[-5:] == '.yaml':
            if os.path.exists(args.config_file):
                print("INFO: when you run the server directly from a .yaml file, please make sure your config file is put in the annotation project folder")
                config_file = args.config_file
                # For direct YAML file usage, we'll determine the project_dir from the config file content
                # after loading it, not from the file path structure
            else:
                raise FileNotFoundError(f"Configuration file not found: {args.config_file}")

        # if the user gives a directory, check if config.yaml or configs/config.yaml exists
        elif os.path.isdir(args.config_file):
            project_dir = args.config_file if os.path.isabs(args.config_file) else os.path.join(project_dir, args.config_file)
            config_folder = os.path.join(args.config_file, 'configs')
            if not os.path.isdir(config_folder):
                raise ConfigValidationError(".yaml file must be put in the configs/ folder under the main project directory when you try to start the project with the project directory, otherwise please directly give the path of the .yaml file")

            #get all the config files
            yamlfiles = [it for it in os.listdir(config_folder) if it[-5:] == '.yaml']

            # if no yaml files found, quit the program
            if len(yamlfiles) == 0:
                raise ConfigValidationError(f"Configuration file not found under {config_folder}, please make sure .yaml file exists in the given directory, or please directly give the path of the .yaml file")
            # if only one yaml file found, directly use it
            elif len(yamlfiles) == 1:
                config_file = os.path.join(config_folder, yamlfiles[0])
                config_file_dir = config_folder

            # if multiple yaml files found, ask the user to choose which one to use
            else:
                while True:
                    print("multiple config files found, please select the one you want to use (number 0-%d)"%len(yamlfiles))
                    for i,it in enumerate(yamlfiles):
                        print("[%d] %s"%(i, it))
                    input_id = input("number: ")
                    try:
                        config_file = os.path.join(config_folder, yamlfiles[int(input_id)])
                        config_file_dir = config_folder
                        break
                    except Exception:
                        print("wrong input, please reselect")

        if not config_file:
            raise ConfigValidationError(f"Configuration file not found under {config_folder}, please make sure .yaml file exists in the given directory, or please directly give the path of the .yaml file")

        # Load and validate the configuration
        # For direct config file usage, use current working directory as base for config file path resolution
        if args.config_file[-5:] == '.yaml':
            # First, load the config without full validation to get the task_dir
            try:
                validated_config_path = validate_path_security(config_file, os.getcwd())
                with open(validated_config_path, 'r', encoding='utf-8') as file_p:
                    temp_config_data = yaml.safe_load(file_p)
            except Exception as e:
                raise ConfigValidationError(f"Error loading configuration file: {str(e)}")

            # Validate that config file is in task_dir (skip in test mode)
            skip_path_validation = os.environ.get('POTATO_SKIP_CONFIG_PATH_VALIDATION', '').lower() in ('1', 'true')
            if 'task_dir' in temp_config_data and not skip_path_validation:
                task_dir = temp_config_data['task_dir']
                config_file_abs = os.path.abspath(config_file)
                task_dir_abs = os.path.abspath(task_dir)
                if not config_file_abs.startswith(task_dir_abs):
                    raise ConfigValidationError(f"Configuration file must be in the task_dir. Config file is at '{config_file_abs}' but task_dir is '{task_dir_abs}'")
                project_dir = task_dir

            # Now load and validate with the correct project_dir
            config_data = load_and_validate_config(config_file, os.getcwd())
        else:
            config_data = load_and_validate_config(config_file, project_dir)

        config.update(config_data)

        # Only override config settings if command line arguments are explicitly provided
        config_updates = {
            "verbose": args.verbose,
            "very_verbose": args.very_verbose,
            "__config_file__": args.config_file,
            "customjs": args.customjs,
            "customjs_hostname": args.customjs_hostname,
            "persist_sessions": args.persist_sessions,
        }

        # Only override debug if explicitly set to True via command line
        # or if config file doesn't have a debug setting
        if args.debug or "debug" not in config:
            config_updates["debug"] = args.debug

        config.update(config_updates)

        # update the current working dir for the server
        os.chdir(project_dir)

    except (ConfigSecurityError, ConfigValidationError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {str(e)}")
        print(f"❌ Configuration error: {str(e)}")
        print("Please check your configuration file and try again.")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during configuration initialization: {str(e)}")
        print(f"❌ Unexpected error: {str(e)}")
        raise


def validate_active_learning_config(config_data: Dict[str, Any]) -> None:
    """
    Validate active learning configuration.

    Args:
        config_data: The configuration data containing active_learning section

    Raises:
        ConfigValidationError: If the active learning configuration is invalid
    """
    if "active_learning" not in config_data:
        return  # Active learning is optional

    al_config = config_data["active_learning"]

    # Validate enabled flag
    if not isinstance(al_config.get("enabled", False), bool):
        raise ConfigValidationError("active_learning.enabled must be a boolean")

    if not al_config.get("enabled", False):
        return  # Skip validation if not enabled

    # Validate classifier configuration
    if "classifier" in al_config:
        classifier_config = al_config["classifier"]
        if not isinstance(classifier_config, dict):
            raise ConfigValidationError("active_learning.classifier must be a dictionary")

        if "name" not in classifier_config:
            raise ConfigValidationError("active_learning.classifier.name is required")

        if not isinstance(classifier_config["name"], str):
            raise ConfigValidationError("active_learning.classifier.name must be a string")

        # Validate hyperparameters if present
        if "hyperparameters" in classifier_config:
            if not isinstance(classifier_config["hyperparameters"], dict):
                raise ConfigValidationError("active_learning.classifier.hyperparameters must be a dictionary")

    # Validate vectorizer configuration
    if "vectorizer" in al_config:
        vectorizer_config = al_config["vectorizer"]
        if not isinstance(vectorizer_config, dict):
            raise ConfigValidationError("active_learning.vectorizer must be a dictionary")

        if "name" not in vectorizer_config:
            raise ConfigValidationError("active_learning.vectorizer.name is required")

        if not isinstance(vectorizer_config["name"], str):
            raise ConfigValidationError("active_learning.vectorizer.name must be a string")

        # Validate hyperparameters if present
        if "hyperparameters" in vectorizer_config:
            if not isinstance(vectorizer_config["hyperparameters"], dict):
                raise ConfigValidationError("active_learning.vectorizer.hyperparameters must be a dictionary")

    # Validate training parameters
    if "min_annotations_per_instance" in al_config:
        min_ann = al_config["min_annotations_per_instance"]
        if not isinstance(min_ann, int) or min_ann < 1:
            raise ConfigValidationError("active_learning.min_annotations_per_instance must be a positive integer")

    if "min_instances_for_training" in al_config:
        min_inst = al_config["min_instances_for_training"]
        if not isinstance(min_inst, int) or min_inst < 2:
            raise ConfigValidationError("active_learning.min_instances_for_training must be an integer >= 2")

    if "max_instances_to_reorder" in al_config:
        max_inst = al_config["max_instances_to_reorder"]
        if not isinstance(max_inst, int) or max_inst < 1:
            raise ConfigValidationError("active_learning.max_instances_to_reorder must be a positive integer")

    if "update_frequency" in al_config:
        update_freq = al_config["update_frequency"]
        if not isinstance(update_freq, int) or update_freq < 1:
            raise ConfigValidationError("active_learning.update_frequency must be a positive integer")

    # Validate resolution strategy
    if "resolution_strategy" in al_config:
        strategy = al_config["resolution_strategy"]
        valid_strategies = ["majority_vote", "random", "consensus", "weighted_average"]
        if strategy not in valid_strategies:
            raise ConfigValidationError(f"active_learning.resolution_strategy must be one of: {', '.join(valid_strategies)}")

    # Validate random sample percent
    if "random_sample_percent" in al_config:
        random_pct = al_config["random_sample_percent"]
        if not isinstance(random_pct, (int, float)) or random_pct < 0 or random_pct > 1:
            raise ConfigValidationError("active_learning.random_sample_percent must be between 0 and 1")

    # Validate schema names
    if "schema_names" in al_config:
        schema_names = al_config["schema_names"]
        if not isinstance(schema_names, list):
            raise ConfigValidationError("active_learning.schema_names must be a list")

        for schema in schema_names:
            if not isinstance(schema, str):
                raise ConfigValidationError("active_learning.schema_names must contain only strings")

            # Check for unsupported schema types
            if schema in ["text", "span"]:
                raise ConfigValidationError(f"Text and span annotation schemes are not supported for active learning: {schema}")

    # Validate database configuration
    if "database" in al_config:
        db_config = al_config["database"]
        if not isinstance(db_config, dict):
            raise ConfigValidationError("active_learning.database must be a dictionary")

        if "enabled" in db_config and not isinstance(db_config["enabled"], bool):
            raise ConfigValidationError("active_learning.database.enabled must be a boolean")

    # Validate model persistence configuration
    if "model_persistence" in al_config:
        model_config = al_config["model_persistence"]
        if not isinstance(model_config, dict):
            raise ConfigValidationError("active_learning.model_persistence must be a dictionary")

        if "enabled" in model_config and not isinstance(model_config["enabled"], bool):
            raise ConfigValidationError("active_learning.model_persistence.enabled must be a boolean")

        if "retention_count" in model_config:
            retention = model_config["retention_count"]
            if not isinstance(retention, int) or retention < 1:
                raise ConfigValidationError("active_learning.model_persistence.retention_count must be a positive integer")

    # Validate LLM configuration
    if "llm" in al_config:
        llm_config = al_config["llm"]
        if not isinstance(llm_config, dict):
            raise ConfigValidationError("active_learning.llm must be a dictionary")

        if "enabled" in llm_config and not isinstance(llm_config["enabled"], bool):
            raise ConfigValidationError("active_learning.llm.enabled must be a boolean")

        if "endpoint_url" in llm_config and not isinstance(llm_config["endpoint_url"], str):
            raise ConfigValidationError("active_learning.llm.endpoint_url must be a string")

        if "model_name" in llm_config and not isinstance(llm_config["model_name"], str):
            raise ConfigValidationError("active_learning.llm.model_name must be a string")


def validate_ai_support_config(config_data: Dict[str, Any]) -> None:
    """
    Validate AI support configuration.

    Args:
        config_data: The configuration data containing ai_support section

    Raises:
        ConfigValidationError: If the AI support configuration is invalid
    """
    if "ai_support" not in config_data:
        return  # AI support is optional

    ai_config = config_data["ai_support"]

    # Validate enabled flag
    if not isinstance(ai_config.get("enabled", False), bool):
        raise ConfigValidationError("ai_support.enabled must be a boolean")

    if not ai_config.get("enabled", False):
        return  # Skip validation if not enabled

    # Validate endpoint type
    if "endpoint_type" not in ai_config:
        raise ConfigValidationError("ai_support.endpoint_type is required when ai_support is enabled")

    endpoint_type = ai_config["endpoint_type"]
    if not isinstance(endpoint_type, str):
        raise ConfigValidationError("ai_support.endpoint_type must be a string")

    valid_endpoint_types = ["openai", "anthropic", "huggingface", "ollama", "gemini", "vllm"]
    if endpoint_type not in valid_endpoint_types:
        raise ConfigValidationError(f"ai_support.endpoint_type must be one of: {', '.join(valid_endpoint_types)}")

    # Validate ai_config section
    if "ai_config" in ai_config:
        ai_endpoint_config = ai_config["ai_config"]
        if not isinstance(ai_endpoint_config, dict):
            raise ConfigValidationError("ai_support.ai_config must be a dictionary")

        # Validate model name
        if "model" in ai_endpoint_config:
            model = ai_endpoint_config["model"]
            if not isinstance(model, str) or not model.strip():
                raise ConfigValidationError("ai_support.ai_config.model must be a non-empty string")

        # Validate API key for cloud-based endpoints
        if endpoint_type in ["openai", "anthropic", "huggingface", "gemini"]:
            api_key = ai_endpoint_config.get("api_key", "")
            if not api_key or not isinstance(api_key, str):
                raise ConfigValidationError(f"ai_support.ai_config.api_key is required for {endpoint_type} endpoint")

        # Validate base_url for VLLM
        if endpoint_type == "vllm":
            base_url = ai_endpoint_config.get("base_url", "")
            if base_url and not isinstance(base_url, str):
                raise ConfigValidationError("ai_support.ai_config.base_url must be a string")

        # Validate temperature
        if "temperature" in ai_endpoint_config:
            temperature = ai_endpoint_config["temperature"]
            if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
                raise ConfigValidationError("ai_support.ai_config.temperature must be between 0 and 2")

        # Validate max_tokens
        if "max_tokens" in ai_endpoint_config:
            max_tokens = ai_endpoint_config["max_tokens"]
            if not isinstance(max_tokens, int) or max_tokens < 1:
                raise ConfigValidationError("ai_support.ai_config.max_tokens must be a positive integer")

        # Validate custom prompts
        for prompt_key in ["hint_prompt", "keyword_prompt"]:
            if prompt_key in ai_endpoint_config:
                prompt = ai_endpoint_config[prompt_key]
                if not isinstance(prompt, str):
                    raise ConfigValidationError(f"ai_support.ai_config.{prompt_key} must be a string")
                if not prompt.strip():
                    raise ConfigValidationError(f"ai_support.ai_config.{prompt_key} cannot be empty")


def parse_active_learning_config(config_data: Dict[str, Any]) -> 'ActiveLearningConfig':
    """
    Parse active learning configuration from YAML data.

    Args:
        config_data: The configuration data containing active_learning section

    Returns:
        ActiveLearningConfig: Parsed active learning configuration

    Raises:
        ConfigValidationError: If the configuration is invalid
    """
    from potato.active_learning_manager import ActiveLearningConfig, ResolutionStrategy

    if "active_learning" not in config_data:
        return ActiveLearningConfig()  # Return default config

    al_config = config_data["active_learning"]

    # Parse classifier configuration
    classifier_name = "sklearn.linear_model.LogisticRegression"
    classifier_kwargs = {}
    if "classifier" in al_config:
        classifier_config = al_config["classifier"]
        classifier_name = classifier_config.get("name", classifier_name)
        classifier_kwargs = classifier_config.get("hyperparameters", {})

    # Parse vectorizer configuration
    vectorizer_name = "sklearn.feature_extraction.text.CountVectorizer"
    vectorizer_kwargs = {}
    if "vectorizer" in al_config:
        vectorizer_config = al_config["vectorizer"]
        vectorizer_name = vectorizer_config.get("name", vectorizer_name)
        vectorizer_kwargs = vectorizer_config.get("hyperparameters", {})

    # Parse resolution strategy
    resolution_strategy = ResolutionStrategy.MAJORITY_VOTE
    if "resolution_strategy" in al_config:
        strategy_str = al_config["resolution_strategy"]
        if strategy_str == "majority_vote":
            resolution_strategy = ResolutionStrategy.MAJORITY_VOTE
        elif strategy_str == "random":
            resolution_strategy = ResolutionStrategy.RANDOM
        elif strategy_str == "consensus":
            resolution_strategy = ResolutionStrategy.CONSENSUS
        elif strategy_str == "weighted_average":
            resolution_strategy = ResolutionStrategy.WEIGHTED_AVERAGE

    # Parse other parameters
    min_annotations_per_instance = al_config.get("min_annotations_per_instance", 1)
    min_instances_for_training = al_config.get("min_instances_for_training", 10)
    max_instances_to_reorder = al_config.get("max_instances_to_reorder")
    random_sample_percent = al_config.get("random_sample_percent", 0.2)
    update_frequency = al_config.get("update_frequency", 5)
    schema_names = al_config.get("schema_names", [])

    # Parse database configuration
    database_enabled = False
    database_config = {}
    if "database" in al_config:
        db_config = al_config["database"]
        database_enabled = db_config.get("enabled", False)
        database_config = {k: v for k, v in db_config.items() if k != "enabled"}

    # Parse model persistence configuration
    model_persistence_enabled = False
    model_save_directory = None
    model_retention_count = 2
    if "model_persistence" in al_config:
        model_config = al_config["model_persistence"]
        model_persistence_enabled = model_config.get("enabled", False)
        model_save_directory = model_config.get("save_directory")
        model_retention_count = model_config.get("retention_count", 2)

    # Parse LLM configuration
    llm_enabled = False
    llm_config = {}
    if "llm" in al_config:
        llm_config = al_config["llm"]
        llm_enabled = llm_config.get("enabled", False)

    return ActiveLearningConfig(
        enabled=al_config.get("enabled", False),
        classifier_name=classifier_name,
        classifier_kwargs=classifier_kwargs,
        vectorizer_name=vectorizer_name,
        vectorizer_kwargs=vectorizer_kwargs,
        min_annotations_per_instance=min_annotations_per_instance,
        min_instances_for_training=min_instances_for_training,
        max_instances_to_reorder=max_instances_to_reorder,
        resolution_strategy=resolution_strategy,
        random_sample_percent=random_sample_percent,
        update_frequency=update_frequency,
        schema_names=schema_names,
        database_enabled=database_enabled,
        database_config=database_config,
        model_persistence_enabled=model_persistence_enabled,
        model_save_directory=model_save_directory,
        model_retention_count=model_retention_count,
        llm_enabled=llm_enabled,
        llm_config=llm_config
    )