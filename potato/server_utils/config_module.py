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

config = {}

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


def validate_yaml_structure(config_data: Dict[str, Any]) -> None:
    """
    Validate the structure and content of the YAML configuration.

    Args:
        config_data: The parsed YAML configuration

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

    # Validate data_files
    data_files = config_data.get('data_files', [])
    if not isinstance(data_files, list):
        raise ConfigValidationError("data_files must be a list")
    if not data_files:
        raise ConfigValidationError("data_files cannot be empty")

    # Validate annotation schemes
    validate_annotation_schemes(config_data)

    # Validate database configuration if present
    if 'database' in config_data:
        validate_database_config(config_data['database'])


def validate_annotation_schemes(config_data: Dict[str, Any]) -> None:
    """
    Validate annotation schemes configuration.

    Args:
        config_data: The configuration data

    Raises:
        ConfigValidationError: If annotation schemes are invalid
    """
    # Check for annotation schemes in different formats
    if 'annotation_schemes' in config_data:
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
    valid_types = ['radio', 'multiselect', 'likert', 'text', 'slider', 'span', 'select', 'number']
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
        required_likert_fields = ['min_label', 'max_label', 'size']
        missing_likert_fields = [field for field in required_likert_fields if field not in scheme]
        if missing_likert_fields:
            raise ConfigValidationError(f"{path} missing required fields for likert: {', '.join(missing_likert_fields)}")

        if not isinstance(scheme['size'], int) or scheme['size'] < 2:
            raise ConfigValidationError(f"{path}.size must be an integer >= 2")

    elif annotation_type == 'slider':
        required_slider_fields = ['min', 'max']
        missing_slider_fields = [field for field in required_slider_fields if field not in scheme]
        if missing_slider_fields:
            raise ConfigValidationError(f"{path} missing required fields for slider: {', '.join(missing_slider_fields)}")

        if not isinstance(scheme['min'], (int, float)) or not isinstance(scheme['max'], (int, float)):
            raise ConfigValidationError(f"{path}.min and max must be numbers")
        if scheme['min'] >= scheme['max']:
            raise ConfigValidationError(f"{path}.min must be less than max")

    elif annotation_type == 'span':
        if 'labels' not in scheme:
            raise ConfigValidationError(f"{path} missing 'labels' field for span annotation type")
        if not isinstance(scheme['labels'], list):
            raise ConfigValidationError(f"{path}.labels must be a list")
        if not scheme['labels']:
            raise ConfigValidationError(f"{path}.labels cannot be empty")


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
    # Use config file directory if provided, otherwise use project directory
    base_dir = config_file_dir if config_file_dir else project_dir

    # Validate data files
    data_files = config_data.get('data_files', [])
    for i, data_file in enumerate(data_files):
        try:
            validated_path = validate_path_security(data_file, base_dir, project_dir)
            if not os.path.exists(validated_path):
                raise ConfigValidationError(f"Data file not found: {data_file} (resolved to: {validated_path})")
        except ConfigSecurityError as e:
            raise ConfigSecurityError(f"Data file {i}: {str(e)}")

    # Validate task_dir and output_annotation_dir
    for field in ['task_dir', 'output_annotation_dir']:
        if field in config_data:
            try:
                validate_path_security(config_data[field], project_dir)
            except ConfigSecurityError as e:
                raise ConfigSecurityError(f"{field}: {str(e)}")


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

    # Validate the configuration structure
    validate_yaml_structure(config_data)

    # Get the directory containing the config file for relative path resolution
    config_file_dir = os.path.dirname(validated_config_path)

    # Validate file paths
    validate_file_paths(config_data, project_dir, config_file_dir)

    return config_data


def init_config(args):
    global config

    project_dir = os.getcwd() #get the current working dir as the default project_dir
    config_file = None

    try:
        # if the .yaml config file is given, directly use it
        if args.config_file[-5:] == '.yaml':
            if os.path.exists(args.config_file):
                print("INFO: when you run the server directly from a .yaml file, please make sure your config file is put in the annotation project folder")
                config_file = args.config_file
                path_sep = os.path.sep
                split_path = os.path.abspath(config_file).split(path_sep)
                if split_path[-2] == "configs":
                    project_dir = path_sep.join(split_path[:-2])
                else:
                    project_dir = path_sep.join(split_path[:-1])
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

            # if multiple yaml files found, ask the user to choose which one to use
            else:
                while True:
                    print("multiple config files found, please select the one you want to use (number 0-%d)"%len(yamlfiles))
                    for i,it in enumerate(yamlfiles):
                        print("[%d] %s"%(i, it))
                    input_id = input("number: ")
                    try:
                        config_file = os.path.join(config_folder, yamlfiles[int(input_id)])
                        break
                    except Exception:
                        print("wrong input, please reselect")

        if not config_file:
            raise ConfigValidationError(f"Configuration file not found under {config_folder}, please make sure .yaml file exists in the given directory, or please directly give the path of the .yaml file")

        # Load and validate the configuration
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