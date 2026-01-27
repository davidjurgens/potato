"""
Template for creating new server tests.

Copy this file and modify it for your specific test needs.
This template demonstrates the standard patterns for server tests.
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestTemplate:
    """
    Template test class for new server tests.

    Replace 'Template' with a descriptive name for your test suite.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with test data."""
        test_dir = create_test_directory("template_test")

        # Create test data
        test_data = [
            {"id": "template_test_1", "text": "This is template test item 1"},
            {"id": "template_test_2", "text": "This is template test item 2"},
            {"id": "template_test_3", "text": "This is template test item 3"}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "name": "template_scheme",
                "annotation_type": "radio",
                "labels": ["option_a", "option_b", "option_c"],
                "description": "Choose one option for the template test."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Template Test Task",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_server_starts_successfully(self):
        """Test that the server starts and responds to basic requests."""
        response = self.server.get("/")
        assert response.status_code in [200, 302]

    def test_user_registration_and_login(self):
        """Test user registration and login workflow."""
        session = requests.Session()
        user_data = {"email": "template_test_user", "pass": "template_test_password"}

        reg_response = session.post(f"{self.server.base_url}/register", data=user_data)
        assert reg_response.status_code in [200, 302]

        login_response = session.post(f"{self.server.base_url}/auth", data=user_data)
        assert login_response.status_code in [200, 302]

        annotate_response = session.get(f"{self.server.base_url}/annotate")
        assert annotate_response.status_code == 200

    def test_annotation_workflow(self):
        """Test complete annotation workflow."""
        session = requests.Session()
        user_data = {"email": "template_annotator", "pass": "template_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "template_test_1",
            "type": "radio",
            "schema": "template_scheme",
            "state": [{"name": "option_a", "value": "option_a"}]
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

    def test_error_handling(self):
        """Test error handling scenarios."""
        response = self.server.get("/nonexistent_endpoint")
        assert response.status_code == 404


class TestTemplateAdvanced:
    """Example of additional test class for advanced features."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for advanced tests."""
        test_dir = create_test_directory("advanced_template_test")

        test_data = [
            {"id": "advanced_1", "text": "Advanced test item 1"},
            {"id": "advanced_2", "text": "Advanced test item 2"}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        annotation_schemes = [
            {
                "name": "advanced_scheme",
                "annotation_type": "text",
                "description": "Enter text annotation."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Advanced Template Test",
            require_password=False
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_advanced_feature(self):
        """Test advanced feature functionality."""
        response = self.server.get("/")
        assert response.status_code in [200, 302]
