"""
Integration tests for display logic (conditional schema branching).

Tests server startup and validation with display_logic configurations.
"""

import pytest
import requests
import os
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestDisplayLogicServerIntegration:
    """Test display_logic with a running server."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start a Flask server with conditional schema configuration."""
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "main_question",
                "description": "Main question",
                "labels": [
                    {"name": "Yes", "key_binding": "y"},
                    {"name": "No", "key_binding": "n"}
                ]
            },
            {
                "annotation_type": "text",
                "name": "followup_text",
                "description": "Please explain:",
                "display_logic": {
                    "show_when": [
                        {"schema": "main_question", "operator": "equals", "value": "Yes"}
                    ]
                }
            },
            {
                "annotation_type": "slider",
                "name": "confidence",
                "description": "Confidence level",
                "min_value": 1,
                "max_value": 10,
                "starting_value": 5,
                "display_logic": {
                    "show_when": [
                        {"schema": "main_question", "operator": "equals", "value": "No"}
                    ]
                }
            },
            {
                "annotation_type": "text",
                "name": "low_confidence_reason",
                "description": "Why low confidence?",
                "display_logic": {
                    "show_when": [
                        {"schema": "confidence", "operator": "in_range", "value": [1, 3]}
                    ]
                }
            }
        ]

        with TestConfigManager("display_logic_test", annotation_schemes) as test_config:
            server = FlaskTestServer(port=9021, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start Flask server")
            yield server
            server.stop()

    def test_server_health(self, flask_server):
        """Test that the server starts and is healthy."""
        # Test root page loads (doesn't require auth)
        response = requests.get(f"{flask_server.base_url}/")
        assert response.status_code == 200

    def test_annotate_page_contains_display_logic(self, flask_server):
        """Test that the annotate page includes display_logic data attributes."""
        session = requests.Session()

        # Register and login
        session.post(f"{flask_server.base_url}/register", data={
            "email": "test_display_logic@test.com",
            "pass": "password123"
        })
        session.post(f"{flask_server.base_url}/auth", data={
            "email": "test_display_logic@test.com",
            "pass": "password123"
        })

        # Get the annotate page
        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200

        # Check that display logic elements are present
        content = response.text
        assert "data-display-logic" in content
        assert "display-logic-container" in content
        assert "display-logic-hidden" in content  # Initially hidden

    def test_annotation_with_conditional_schemas(self, flask_server):
        """Test submitting annotations with conditional schemas."""
        session = requests.Session()

        # Register and login
        session.post(f"{flask_server.base_url}/register", data={
            "email": "test_conditional@test.com",
            "pass": "password123"
        })
        session.post(f"{flask_server.base_url}/auth", data={
            "email": "test_conditional@test.com",
            "pass": "password123"
        })

        # Visit annotate page first to get assigned an instance
        response = session.get(f"{flask_server.base_url}/annotate")
        assert response.status_code == 200

        # Get current instance
        response = session.get(f"{flask_server.base_url}/api/current_instance")
        assert response.status_code == 200
        instance_data = response.json()
        instance_id = instance_data.get("instance_id")

        # Submit annotation with "Yes" selection (should trigger followup_text)
        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json={
                "instance_id": instance_id,
                "annotations": {
                    "main_question:Yes": True
                }
            },
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200


class TestDisplayLogicConfigValidation:
    """Test configuration validation for display_logic."""

    def test_invalid_operator_fails_validation(self, tmp_path):
        """Test that invalid operators cause config validation to fail."""
        from potato.server_utils.config_module import validate_yaml_structure, ConfigValidationError

        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "test1", "description": "Test", "labels": ["A", "B"]},
                {
                    "annotation_type": "text",
                    "name": "test2",
                    "description": "Test",
                    "display_logic": {
                        "show_when": [
                            {"schema": "test1", "operator": "invalid_op", "value": "A"}
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "invalid_op" in str(exc_info.value)

    def test_missing_referenced_schema_fails_validation(self, tmp_path):
        """Test that referencing a non-existent schema fails validation."""
        from potato.server_utils.config_module import validate_yaml_structure, ConfigValidationError

        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {
                    "annotation_type": "text",
                    "name": "test_schema",
                    "description": "Test",
                    "display_logic": {
                        "show_when": [
                            {"schema": "nonexistent_schema", "operator": "equals", "value": "A"}
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "nonexistent_schema" in str(exc_info.value)

    def test_circular_dependency_fails_validation(self, tmp_path):
        """Test that circular dependencies fail validation."""
        from potato.server_utils.config_module import validate_yaml_structure, ConfigValidationError

        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "schema_a",
                    "description": "A",
                    "labels": ["X", "Y"],
                    "display_logic": {
                        "show_when": [
                            {"schema": "schema_b", "operator": "not_empty"}
                        ]
                    }
                },
                {
                    "annotation_type": "radio",
                    "name": "schema_b",
                    "description": "B",
                    "labels": ["X", "Y"],
                    "display_logic": {
                        "show_when": [
                            {"schema": "schema_a", "operator": "not_empty"}
                        ]
                    }
                }
            ]
        }

        with pytest.raises(ConfigValidationError) as exc_info:
            validate_yaml_structure(config, str(tmp_path), str(tmp_path))

        assert "Circular" in str(exc_info.value)

    def test_valid_display_logic_passes_validation(self, tmp_path):
        """Test that valid display_logic configurations pass validation."""
        from potato.server_utils.config_module import validate_yaml_structure

        config = {
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_files": [{"path": "test.json", "format": "json"}],
            "task_dir": str(tmp_path),
            "output_annotation_dir": "output",
            "annotation_task_name": "Test",
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "main", "description": "Main", "labels": ["Yes", "No"]},
                {
                    "annotation_type": "text",
                    "name": "detail",
                    "description": "Details",
                    "display_logic": {
                        "show_when": [
                            {"schema": "main", "operator": "equals", "value": "Yes"}
                        ]
                    }
                }
            ]
        }

        # Should not raise
        validate_yaml_structure(config, str(tmp_path), str(tmp_path))
