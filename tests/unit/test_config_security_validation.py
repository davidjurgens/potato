"""
Tests for config security validation and enhanced error handling.

This module tests the security features of the Potato configuration system, including:
- Path traversal protection
- File path validation
- YAML structure validation
- Security error handling
- Enhanced error messages
"""

import pytest
import yaml
import os
import tempfile
import shutil
from pathlib import Path

# Import the validation functions
from potato.server_utils.config_module import (
    validate_path_security,
    validate_yaml_structure,
    validate_annotation_schemes,
    validate_single_annotation_scheme,
    validate_database_config,
    validate_file_paths,
    load_and_validate_config,
    ConfigValidationError,
    ConfigSecurityError
)


class TestPathSecurityValidation:
    """Test path security validation functions."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_valid_relative_path(self, temp_dir):
        """Test that valid relative paths are accepted."""
        # Create a subdirectory
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        # Test relative path
        result = validate_path_security("subdir", temp_dir)
        assert result == subdir

    def test_valid_absolute_path(self, temp_dir):
        """Test that valid absolute paths within the base directory are accepted."""
        # Create a subdirectory
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        # Test absolute path within base directory
        result = validate_path_security(subdir, temp_dir)
        assert result == subdir

    def test_path_traversal_detection(self, temp_dir):
        """Test that path traversal attempts are detected and blocked."""
        # Test various path traversal patterns that should be blocked
        traversal_paths = [
            "../../../file.txt",  # 3 levels of .. - should be blocked
            "subdir/../../../../file.txt",  # 4 levels of .. - should be blocked
            "subdir/../../../..",  # 4 levels of .. - should be blocked
        ]

        for path in traversal_paths:
            with pytest.raises(ConfigSecurityError, match="Excessive path traversal detected"):
                validate_path_security(path, temp_dir)

        # Test encoded traversal patterns
        encoded_paths = [
            "....//file.txt",  # Encoded traversal
            "subdir/....//file.txt",  # Encoded traversal
            "data/..%2F..%2Fetc%2Fpasswd",  # URL encoded
            "data/..%5C..%5Cwindows%5Csystem32%5Cconfig%5Csam"  # Windows encoded
        ]

        for path in encoded_paths:
            with pytest.raises(ConfigSecurityError, match="Encoded path traversal detected"):
                validate_path_security(path, temp_dir)

    def test_legitimate_relative_paths(self, temp_dir):
        """Test that legitimate relative paths are allowed."""
        # Create a subdirectory structure
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        # Test legitimate relative paths
        legitimate_paths = [
            "../file.txt",  # 1 level of .. - should be allowed
            "subdir/../file.txt",  # 1 level of .. - should be allowed
            "subdir/../../file.txt",  # 2 levels of .. - should be allowed
        ]

        for path in legitimate_paths:
            # These should not raise exceptions, but may resolve outside the base directory
            # which is acceptable for legitimate relative paths
            try:
                validate_path_security(path, temp_dir)
            except ConfigSecurityError as e:
                # It's okay if it resolves outside the base directory for legitimate paths
                assert "outside the project directory" in str(e)

    def test_path_outside_base_directory(self, temp_dir):
        """Test that paths outside the base directory are blocked."""
        # Create a directory outside the temp directory
        outside_dir = tempfile.mkdtemp()
        try:
            with pytest.raises(ConfigSecurityError, match="outside the project directory"):
                validate_path_security(outside_dir, temp_dir)
        finally:
            shutil.rmtree(outside_dir)

    def test_symlink_traversal_protection(self, temp_dir):
        """Test protection against symlink-based traversal."""
        # Create a symlink that points outside the base directory
        outside_dir = tempfile.mkdtemp()
        symlink_path = os.path.join(temp_dir, "symlink")

        try:
            os.symlink(outside_dir, symlink_path)

            with pytest.raises(ConfigSecurityError, match="outside the project directory"):
                validate_path_security("symlink", temp_dir)
        finally:
            shutil.rmtree(outside_dir)
            if os.path.exists(symlink_path):
                os.unlink(symlink_path)

    def test_normalized_path_handling(self, temp_dir):
        """Test that path normalization works correctly."""
        # Create a subdirectory with extra slashes
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        # Test paths with extra slashes and dots
        test_paths = [
            "./subdir",
            "subdir/.",
            "subdir//",
            "subdir/./",
            "subdir/../subdir"
        ]

        for path in test_paths:
            result = validate_path_security(path, temp_dir)
            assert result == subdir


class TestYAMLStructureValidation:
    """Test YAML structure validation functions."""

    def test_valid_config_structure(self):
        """Test that valid configuration structure is accepted."""
        valid_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data.json"],
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Test description",
                    "labels": ["positive", "negative"]
                }
            ]
        }

        # Should not raise any exceptions
        validate_yaml_structure(valid_config)

    def test_missing_required_fields(self):
        """Test that missing required fields are detected."""
        invalid_config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data.json"]
            # Missing other required fields
        }

        with pytest.raises(ConfigValidationError, match="Missing required configuration fields"):
            validate_yaml_structure(invalid_config)

    def test_invalid_item_properties(self):
        """Test validation of item_properties structure."""
        config = {
            "item_properties": "not_a_dict",  # Should be a dict
            "data_files": ["data.json"],
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": []
        }

        with pytest.raises(ConfigValidationError, match="item_properties must be a dictionary"):
            validate_yaml_structure(config)

    def test_missing_item_property_keys(self):
        """Test that missing item property keys are detected."""
        config = {
            "item_properties": {
                "id_key": "id"
                # Missing text_key
            },
            "data_files": ["data.json"],
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": []
        }

        with pytest.raises(ConfigValidationError, match="Missing required item_properties"):
            validate_yaml_structure(config)

    def test_invalid_data_files_type(self):
        """Test that data_files must be a list."""
        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": "not_a_list",  # Should be a list
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": []
        }

        with pytest.raises(ConfigValidationError, match="data_files must be a list"):
            validate_yaml_structure(config)

    def test_empty_data_files_without_data_directory(self):
        """Test that empty data_files is rejected when data_directory is not set."""
        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [],  # Empty list
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": []
        }

        with pytest.raises(ConfigValidationError, match="Either data_files or data_directory must be configured"):
            validate_yaml_structure(config)

    def test_empty_data_files_with_data_directory(self):
        """Test that empty data_files is allowed when data_directory is set."""
        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [],  # Empty list - allowed because data_directory is set
            "data_directory": "./data",
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "test", "description": "Test", "labels": ["a", "b"]}
            ]
        }

        # Should not raise - data_directory provides the data source
        validate_yaml_structure(config)


class TestAnnotationSchemeValidation:
    """Test annotation scheme validation functions."""

    def test_valid_radio_scheme(self):
        """Test validation of valid radio annotation scheme."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Choose sentiment",
            "labels": ["positive", "negative", "neutral"]
        }

        # Should not raise any exceptions
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_valid_likert_scheme(self):
        """Test validation of valid likert annotation scheme."""
        scheme = {
            "annotation_type": "likert",
            "name": "quality",
            "description": "Rate quality",
            "min_label": "Poor",
            "max_label": "Excellent",
            "size": 5
        }

        # Should not raise any exceptions
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_valid_slider_scheme(self):
        """Test validation of valid slider annotation scheme."""
        scheme = {
            "annotation_type": "slider",
            "name": "confidence",
            "description": "Rate confidence",
            "min_value": 0,
            "max_value": 10,
            "starting_value": 5
        }

        # Should not raise any exceptions
        validate_single_annotation_scheme(scheme, "test_scheme")

    def test_missing_required_scheme_fields(self):
        """Test that missing required scheme fields are detected."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment"
            # Missing description
        }

        with pytest.raises(ConfigValidationError, match="missing required fields"):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_invalid_annotation_type(self):
        """Test that invalid annotation types are rejected."""
        scheme = {
            "annotation_type": "invalid_type",
            "name": "test",
            "description": "test"
        }

        with pytest.raises(ConfigValidationError, match="must be one of"):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_radio_scheme_missing_labels(self):
        """Test that radio schemes require labels."""
        scheme = {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "Choose sentiment"
            # Missing labels
        }

        with pytest.raises(ConfigValidationError, match="missing 'labels' field"):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_likert_scheme_invalid_size(self):
        """Test that likert schemes require valid size."""
        scheme = {
            "annotation_type": "likert",
            "name": "quality",
            "description": "Rate quality",
            "min_label": "Poor",
            "max_label": "Excellent",
            "size": 1  # Too small
        }

        with pytest.raises(ConfigValidationError, match="must be an integer >= 2"):
            validate_single_annotation_scheme(scheme, "test_scheme")

    def test_slider_scheme_invalid_range(self):
        """Test that slider schemes require valid min/max values."""
        scheme = {
            "annotation_type": "slider",
            "name": "confidence",
            "description": "Rate confidence",
            "min_value": 10,
            "max_value": 5,  # min >= max
            "starting_value": 7
        }

        with pytest.raises(ConfigValidationError, match="min_value must be less than max_value"):
            validate_single_annotation_scheme(scheme, "test_scheme")


class TestDatabaseConfigValidation:
    """Test database configuration validation."""

    def test_valid_mysql_config(self):
        """Test validation of valid MySQL configuration."""
        db_config = {
            "type": "mysql",
            "host": "localhost",
            "database": "test_db",
            "username": "test_user",
            "password": "test_pass"
        }

        # Should not raise any exceptions
        validate_database_config(db_config)

    def test_valid_file_config(self):
        """Test validation of valid file-based configuration."""
        db_config = {
            "type": "file",
            "host": "localhost",
            "database": "test_db",
            "username": "test_user"
        }

        # Should not raise any exceptions
        validate_database_config(db_config)

    def test_missing_required_fields(self):
        """Test that missing required database fields are detected."""
        db_config = {
            "type": "mysql",
            "host": "localhost"
            # Missing database, username, password
        }

        with pytest.raises(ConfigValidationError, match="Missing required database fields"):
            validate_database_config(db_config)

    def test_invalid_database_type(self):
        """Test that invalid database types are rejected."""
        db_config = {
            "type": "invalid_type",
            "host": "localhost",
            "database": "test_db",
            "username": "test_user"
        }

        with pytest.raises(ConfigValidationError, match="Unsupported database type"):
            validate_database_config(db_config)

    def test_mysql_missing_password(self):
        """Test that MySQL configurations require password."""
        db_config = {
            "type": "mysql",
            "host": "localhost",
            "database": "test_db",
            "username": "test_user"
            # Missing password
        }

        with pytest.raises(ConfigValidationError, match="MySQL database requires password"):
            validate_database_config(db_config)

    def test_invalid_port_number(self):
        """Test that invalid port numbers are rejected."""
        db_config = {
            "type": "mysql",
            "host": "localhost",
            "database": "test_db",
            "username": "test_user",
            "password": "test_pass",
            "port": 70000  # Invalid port
        }

        with pytest.raises(ConfigValidationError, match="Database port must be between 1 and 65535"):
            validate_database_config(db_config)


class TestFilePathValidation:
    """Test file path validation functions."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory with test files."""
        temp_dir = tempfile.mkdtemp()

        # Create project structure
        os.makedirs(os.path.join(temp_dir, "output", "data"))

        # Create test data file (in output/data/ because validate_file_paths
        # resolves paths relative to task_dir which is "output")
        data_file = os.path.join(temp_dir, "output", "data", "test.json")
        with open(data_file, 'w') as f:
            f.write('{"test": "data"}')

        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_valid_file_paths(self, temp_project):
        """Test that valid file paths are accepted."""
        config_data = {
            "data_files": ["data/test.json"],
            "task_dir": "output",
            "output_annotation_dir": "output"
        }

        # Should not raise any exceptions
        validate_file_paths(config_data, temp_project)

    def test_missing_data_file(self, temp_project):
        """Test that missing data files are detected."""
        config_data = {
            "data_files": ["data/missing.json"],
            "task_dir": "output",
            "output_annotation_dir": "output"
        }

        with pytest.raises(ConfigValidationError, match="Data file not found"):
            validate_file_paths(config_data, temp_project)

    def test_path_traversal_in_data_files(self, temp_project):
        """Test that path traversal in data files is blocked."""
        config_data = {
            "data_files": ["../../../etc/passwd"],  # Excessive path traversal
            "task_dir": "output",
            "output_annotation_dir": "output"
        }

        with pytest.raises(ConfigSecurityError, match="Excessive path traversal detected"):
            validate_file_paths(config_data, temp_project)


class TestLoadAndValidateConfig:
    """Test the complete load_and_validate_config function."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory with test files."""
        temp_dir = tempfile.mkdtemp()

        # Create project structure
        os.makedirs(os.path.join(temp_dir, "configs"))
        os.makedirs(os.path.join(temp_dir, "data"))
        os.makedirs(os.path.join(temp_dir, "output"))

        # Create test data file
        data_file = os.path.join(temp_dir, "data", "test.json")
        with open(data_file, 'w') as f:
            f.write('{"test": "data"}')

        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_valid_config_file(self, temp_project):
        """Test loading a valid configuration file."""
        config_file = os.path.join(temp_project, "configs", "test.yaml")

        config_content = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["../data/test.json"],
            "task_dir": "output",
            "output_annotation_dir": "output",
            "annotation_task_name": "Test Task",
            "alert_time_each_instance": 1000,
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "sentiment",
                    "description": "Choose sentiment",
                    "labels": ["positive", "negative"]
                }
            ]
        }

        with open(config_file, 'w') as f:
            yaml.dump(config_content, f)

        # Should not raise any exceptions
        result = load_and_validate_config(config_file, temp_project)
        assert result["annotation_task_name"] == "Test Task"

    def test_invalid_yaml_format(self, temp_project):
        """Test handling of invalid YAML format."""
        config_file = os.path.join(temp_project, "configs", "invalid.yaml")

        with open(config_file, 'w') as f:
            f.write("invalid: yaml: content: [")

        with pytest.raises(ConfigValidationError, match="Invalid YAML format"):
            load_and_validate_config(config_file, temp_project)

    def test_missing_config_file(self, temp_project):
        """Test handling of missing configuration file."""
        config_file = os.path.join(temp_project, "configs", "missing.yaml")

        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_and_validate_config(config_file, temp_project)

    def test_path_traversal_in_config_path(self, temp_project):
        """Test that path traversal in config file path is blocked."""
        # Create a config file outside the project directory
        outside_dir = tempfile.mkdtemp()
        config_file = os.path.join(outside_dir, "test.yaml")

        try:
            config_content = {
                "item_properties": {"id_key": "id", "text_key": "text"},
                "data_files": ["data/test.json"],
                "task_dir": "output",
                "output_annotation_dir": "output",
                "annotation_task_name": "Test Task",
                "alert_time_each_instance": 1000,
                "annotation_schemes": []
            }

            with open(config_file, 'w') as f:
                yaml.dump(config_content, f)

            # Try to access it with a path traversal
            traversal_path = os.path.join(temp_project, "configs", "..", "..", os.path.basename(outside_dir), "test.yaml")

            with pytest.raises(ConfigSecurityError, match="outside the project directory"):
                load_and_validate_config(traversal_path, temp_project)
        finally:
            shutil.rmtree(outside_dir)

    def test_malicious_path_traversal_config(self, temp_project):
        """Test that config with path traversal attempts is rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-path-traversal.yaml")

        # Copy the malicious config file
        source_file = os.path.join(os.path.dirname(__file__), "../configs/malicious-path-traversal.yaml")
        shutil.copy2(source_file, config_file)

        # Should raise ConfigSecurityError due to excessive path traversal
        with pytest.raises(ConfigSecurityError, match="Excessive path traversal detected"):
            load_and_validate_config(config_file, temp_project)


class TestErrorMessages:
    """Test that error messages are helpful and informative."""

    def test_missing_fields_error_message(self):
        """Test that missing fields error message is helpful."""
        config = {
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_files": ["data.json"]
            # Missing other required fields
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config)

        error_msg = str(exc_info.value)
        assert "Missing required configuration fields" in error_msg
        assert "task_dir" in error_msg
        assert "output_annotation_dir" in error_msg
        assert "annotation_task_name" in error_msg

    def test_path_traversal_error_message(self):
        """Test that path traversal error message is helpful."""
        with pytest.raises(ConfigSecurityError) as exc_info:
            validate_path_security("../../../etc/passwd", "/tmp/test")

        error_msg = str(exc_info.value)
        assert "Excessive path traversal detected" in error_msg
        assert "Too many '..' components for security reasons" in error_msg
        assert "../../../etc/passwd" in error_msg

    def test_annotation_scheme_error_message(self):
        """Test that annotation scheme error messages are helpful."""
        scheme = {
            "annotation_type": "radio",
            "name": "test"
            # Missing description and labels
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_single_annotation_scheme(scheme, "test_scheme")

        error_msg = str(exc_info.value)
        assert "missing required fields" in error_msg
        assert "description" in error_msg


class TestServerConfigValidation:
    """Test server configuration validation."""

    def test_valid_server_config(self):
        """Test that valid server configuration is accepted."""
        from potato.server_utils.config_module import validate_server_config

        config = {
            "server": {
                "port": 8000,
                "host": "0.0.0.0",
                "debug": False
            }
        }

        # Should not raise any exceptions
        validate_server_config(config)

    def test_valid_server_config_partial(self):
        """Test that partial server configuration is accepted."""
        from potato.server_utils.config_module import validate_server_config

        # Only port specified
        config = {"server": {"port": 9000}}
        validate_server_config(config)

        # Only host specified
        config = {"server": {"host": "localhost"}}
        validate_server_config(config)

        # Only debug specified
        config = {"server": {"debug": True}}
        validate_server_config(config)

    def test_no_server_config(self):
        """Test that missing server config is fine (optional)."""
        from potato.server_utils.config_module import validate_server_config

        config = {"annotation_task_name": "Test Task"}
        validate_server_config(config)

    def test_invalid_server_config_not_dict(self):
        """Test that non-dict server config is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": "invalid"}

        with pytest.raises(ConfigValidationError, match="server configuration must be a dictionary"):
            validate_server_config(config)

    def test_invalid_port_type(self):
        """Test that non-integer port is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"port": "8000"}}

        with pytest.raises(ConfigValidationError, match="server.port must be an integer"):
            validate_server_config(config)

    def test_invalid_port_range_low(self):
        """Test that port below 1 is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"port": 0}}

        with pytest.raises(ConfigValidationError, match="server.port must be between 1 and 65535"):
            validate_server_config(config)

    def test_invalid_port_range_high(self):
        """Test that port above 65535 is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"port": 70000}}

        with pytest.raises(ConfigValidationError, match="server.port must be between 1 and 65535"):
            validate_server_config(config)

    def test_invalid_host_type(self):
        """Test that non-string host is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"host": 12345}}

        with pytest.raises(ConfigValidationError, match="server.host must be a string"):
            validate_server_config(config)

    def test_empty_host(self):
        """Test that empty host is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"host": ""}}

        with pytest.raises(ConfigValidationError, match="server.host cannot be empty"):
            validate_server_config(config)

        config = {"server": {"host": "   "}}

        with pytest.raises(ConfigValidationError, match="server.host cannot be empty"):
            validate_server_config(config)

    def test_invalid_debug_type(self):
        """Test that non-boolean debug is rejected."""
        from potato.server_utils.config_module import validate_server_config, ConfigValidationError

        config = {"server": {"debug": "true"}}

        with pytest.raises(ConfigValidationError, match="server.debug must be a boolean"):
            validate_server_config(config)


class TestQualityControlConfigValidation:
    """Tests for quality control configuration validation."""

    def test_valid_attention_checks_config(self):
        """Test that valid attention checks config is accepted."""
        from potato.server_utils.config_module import validate_quality_control_config

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": 10,
                "min_response_time": 3.0,
                "failure_handling": {
                    "warn_threshold": 2,
                    "block_threshold": 5
                }
            }
        }

        # Should not raise
        validate_quality_control_config(config)

    def test_attention_checks_missing_items_file(self):
        """Test that enabled attention checks require items_file."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "attention_checks": {
                "enabled": True,
                "frequency": 10
            }
        }

        with pytest.raises(ConfigValidationError, match="attention_checks.items_file is required"):
            validate_quality_control_config(config)

    def test_attention_checks_both_frequency_and_probability(self):
        """Test that specifying both frequency and probability is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": 10,
                "probability": 0.1
            }
        }

        with pytest.raises(ConfigValidationError, match="specify either 'frequency' or 'probability', not both"):
            validate_quality_control_config(config)

    def test_attention_checks_invalid_frequency(self):
        """Test that invalid frequency is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": -1
            }
        }

        with pytest.raises(ConfigValidationError, match="frequency must be a positive integer"):
            validate_quality_control_config(config)

    def test_attention_checks_invalid_probability(self):
        """Test that invalid probability is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "probability": 1.5
            }
        }

        with pytest.raises(ConfigValidationError, match="probability must be a number between 0 and 1"):
            validate_quality_control_config(config)

    def test_attention_checks_block_must_be_greater_than_warn(self):
        """Test that block threshold must be greater than warn threshold."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "attention_checks": {
                "enabled": True,
                "items_file": "attention.json",
                "frequency": 10,
                "failure_handling": {
                    "warn_threshold": 5,
                    "block_threshold": 3  # Less than warn
                }
            }
        }

        with pytest.raises(ConfigValidationError, match="block_threshold must be greater than warn_threshold"):
            validate_quality_control_config(config)

    def test_valid_gold_standards_config(self):
        """Test that valid gold standards config is accepted."""
        from potato.server_utils.config_module import validate_quality_control_config

        config = {
            "gold_standards": {
                "enabled": True,
                "items_file": "gold.json",
                "mode": "mixed",
                "frequency": 20,
                "accuracy": {
                    "min_threshold": 0.8,
                    "evaluation_count": 10
                }
            }
        }

        # Should not raise
        validate_quality_control_config(config)

    def test_gold_standards_missing_items_file(self):
        """Test that enabled gold standards require items_file."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "gold_standards": {
                "enabled": True,
                "mode": "mixed"
            }
        }

        with pytest.raises(ConfigValidationError, match="gold_standards.items_file is required"):
            validate_quality_control_config(config)

    def test_gold_standards_invalid_mode(self):
        """Test that invalid mode is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "gold_standards": {
                "enabled": True,
                "items_file": "gold.json",
                "mode": "invalid_mode"
            }
        }

        with pytest.raises(ConfigValidationError, match="gold_standards.mode must be one of"):
            validate_quality_control_config(config)

    def test_gold_standards_invalid_threshold(self):
        """Test that invalid accuracy threshold is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "gold_standards": {
                "enabled": True,
                "items_file": "gold.json",
                "accuracy": {
                    "min_threshold": 1.5  # Invalid: > 1
                }
            }
        }

        with pytest.raises(ConfigValidationError, match="min_threshold must be between 0 and 1"):
            validate_quality_control_config(config)

    def test_valid_pre_annotation_config(self):
        """Test that valid pre-annotation config is accepted."""
        from potato.server_utils.config_module import validate_quality_control_config

        config = {
            "pre_annotation": {
                "enabled": True,
                "field": "predictions",
                "highlight_low_confidence": 0.5
            }
        }

        # Should not raise
        validate_quality_control_config(config)

    def test_pre_annotation_empty_field(self):
        """Test that empty field name is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "pre_annotation": {
                "enabled": True,
                "field": ""
            }
        }

        with pytest.raises(ConfigValidationError, match="field must be a non-empty string"):
            validate_quality_control_config(config)

    def test_pre_annotation_invalid_threshold(self):
        """Test that invalid confidence threshold is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "pre_annotation": {
                "enabled": True,
                "highlight_low_confidence": -0.5
            }
        }

        with pytest.raises(ConfigValidationError, match="highlight_low_confidence must be between 0 and 1"):
            validate_quality_control_config(config)

    def test_valid_agreement_metrics_config(self):
        """Test that valid agreement metrics config is accepted."""
        from potato.server_utils.config_module import validate_quality_control_config

        config = {
            "agreement_metrics": {
                "enabled": True,
                "min_overlap": 3,
                "refresh_interval": 60
            }
        }

        # Should not raise
        validate_quality_control_config(config)

    def test_agreement_metrics_invalid_min_overlap(self):
        """Test that min_overlap < 2 is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "agreement_metrics": {
                "min_overlap": 1
            }
        }

        with pytest.raises(ConfigValidationError, match="min_overlap must be an integer >= 2"):
            validate_quality_control_config(config)

    def test_agreement_metrics_invalid_refresh_interval(self):
        """Test that refresh_interval < 10 is rejected."""
        from potato.server_utils.config_module import validate_quality_control_config, ConfigValidationError

        config = {
            "agreement_metrics": {
                "refresh_interval": 5
            }
        }

        with pytest.raises(ConfigValidationError, match="refresh_interval must be an integer >= 10"):
            validate_quality_control_config(config)