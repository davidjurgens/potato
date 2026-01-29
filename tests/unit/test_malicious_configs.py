"""
Tests for malicious configuration files to verify security measures.

This module tests that malicious configuration files are properly rejected
by the security validation system.
"""

import pytest
import yaml
import os
import tempfile
import shutil

# Import the validation functions
from potato.server_utils.config_module import (
    load_and_validate_config,
    ConfigValidationError,
    ConfigSecurityError
)


class TestMaliciousConfigFiles:
    """Test that malicious configuration files are properly rejected."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory for testing."""
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

    def test_malicious_path_traversal_config(self, temp_project):
        """Test that config with path traversal attempts is rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-path-traversal.yaml")

        # Copy the malicious config file
        source_file = os.path.join(os.path.dirname(__file__), "../configs/malicious-path-traversal.yaml")
        shutil.copy2(source_file, config_file)

        # Should raise ConfigSecurityError due to excessive path traversal
        with pytest.raises(ConfigSecurityError, match="Excessive path traversal detected"):
            load_and_validate_config(config_file, temp_project)

    def test_malicious_invalid_structure_config(self, temp_project):
        """Test that config with invalid structure is rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-invalid-structure.yaml")

        # Copy the malicious config file
        source_file = os.path.join(os.path.dirname(__file__), "../configs/malicious-invalid-structure.yaml")
        shutil.copy2(source_file, config_file)

        # Should raise ConfigValidationError due to invalid structure
        with pytest.raises(ConfigValidationError):
            load_and_validate_config(config_file, temp_project)

    def test_malicious_absolute_path_escape(self, temp_project):
        """Test that config with absolute paths outside project is rejected."""
        # Create a config file with absolute path outside project
        config_file = os.path.join(temp_project, "configs", "malicious-absolute.yaml")

        config_content = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["/etc/passwd"],  # Absolute path outside project
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

        # Should raise ConfigSecurityError due to path outside project
        with pytest.raises(ConfigSecurityError, match="outside the project directory"):
            load_and_validate_config(config_file, temp_project)

    def test_malicious_symlink_traversal(self, temp_project):
        """Test that config with symlink traversal is rejected."""
        # Create a symlink that points outside the project
        outside_dir = tempfile.mkdtemp()
        symlink_path = os.path.join(temp_project, "data", "malicious_symlink")

        try:
            os.symlink(outside_dir, symlink_path)

            # Create the file that the symlink points to
            sensitive_file = os.path.join(outside_dir, "sensitive_file.txt")
            with open(sensitive_file, 'w') as f:
                f.write("sensitive data")

            config_file = os.path.join(temp_project, "configs", "malicious-symlink.yaml")

            # Note: task_dir is resolved relative to config file directory (configs/)
            # So "../output" resolves to temp_project/output
            # And "../data/malicious_symlink/sensitive_file.txt" from temp_project/output
            # resolves to temp_project/data/malicious_symlink/sensitive_file.txt
            config_content = {
                "item_properties": {
                    "id_key": "id",
                    "text_key": "text"
                },
                "data_files": ["../data/malicious_symlink/sensitive_file.txt"],
                "task_dir": "../output",  # Relative to configs/, resolves to temp_project/output
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

            # Should raise ConfigSecurityError due to symlink traversal
            with pytest.raises(ConfigSecurityError, match="outside the project directory"):
                load_and_validate_config(config_file, temp_project)
        finally:
            shutil.rmtree(outside_dir)
            if os.path.exists(symlink_path):
                os.unlink(symlink_path)

    def test_malicious_encoded_traversal(self, temp_project):
        """Test that encoded path traversal attempts are rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-encoded.yaml")

        config_content = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [
                "data/....//sensitive_file.txt",  # Encoded traversal
                "data/..%2F..%2Fetc%2Fpasswd",   # URL encoded traversal
                "data/..%5C..%5Cwindows%5Csystem32%5Cconfig%5Csam"  # Windows encoded
            ],
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

        # Should raise ConfigSecurityError due to encoded path traversal
        with pytest.raises(ConfigSecurityError, match="Encoded path traversal detected"):
            load_and_validate_config(config_file, temp_project)

    def test_malicious_invalid_yaml(self, temp_project):
        """Test that invalid YAML files are rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-invalid.yaml")

        # Create invalid YAML content
        invalid_yaml_content = """
        annotation_task_name: "Test"
        item_properties: {
        data_files: [
        annotation_schemes: [
        """  # Malformed YAML

        with open(config_file, 'w') as f:
            f.write(invalid_yaml_content)

        # Should raise ConfigValidationError due to invalid YAML
        with pytest.raises(ConfigValidationError, match="Invalid YAML format"):
            load_and_validate_config(config_file, temp_project)

    def test_malicious_missing_required_files(self, temp_project):
        """Test that configs referencing non-existent files are rejected."""
        config_file = os.path.join(temp_project, "configs", "malicious-missing.yaml")

        config_content = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": ["data/non_existent_file.json"],
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

        # Should raise ConfigValidationError due to missing file
        with pytest.raises(ConfigValidationError, match="Data file not found"):
            load_and_validate_config(config_file, temp_project)


class TestSecurityErrorMessages:
    """Test that security error messages are informative."""

    def test_path_traversal_error_message(self):
        """Test that path traversal error messages are helpful."""
        from potato.server_utils.config_module import validate_path_security

        with pytest.raises(ConfigSecurityError) as exc_info:
            validate_path_security("../../../etc/passwd", "/tmp/test")

        error_msg = str(exc_info.value)
        assert "Excessive path traversal detected" in error_msg
        assert "Too many '..' components for security reasons" in error_msg
        assert "../../../etc/passwd" in error_msg

    def test_outside_directory_error_message(self):
        """Test that outside directory error messages are helpful."""
        from potato.server_utils.config_module import validate_path_security

        # Create a directory outside the test directory
        outside_dir = tempfile.mkdtemp()
        try:
            with pytest.raises(ConfigSecurityError) as exc_info:
                validate_path_security(outside_dir, "/tmp/test")

            error_msg = str(exc_info.value)
            assert "outside the project directory" in error_msg
            assert outside_dir in error_msg
        finally:
            shutil.rmtree(outside_dir)

    def test_validation_error_message(self):
        """Test that validation error messages are helpful."""
        from potato.server_utils.config_module import validate_yaml_structure

        invalid_config = {
            "item_properties": "not_a_dict",
            "data_files": "not_a_list"
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(invalid_config)

        error_msg = str(exc_info.value)
        assert "Missing required configuration fields" in error_msg
        assert "task_dir" in error_msg
        assert "output_annotation_dir" in error_msg