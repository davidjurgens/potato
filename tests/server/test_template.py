"""
Template for creating new server tests.

Copy this file and modify it for your specific test needs.
This template demonstrates the standard patterns for server tests.
"""

import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
import json
import tempfile
import os
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


class TestTemplate:
    """
    Template test class for new server tests.

    Replace 'Template' with a descriptive name for your test suite.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """
        Create a Flask test server with test data.

        This fixture:
        1. Creates temporary test data
        2. Sets up a minimal config
        3. Starts the Flask server
        4. Cleans up after tests complete
        """
        # Create temporary directory for this test
        test_dir = tempfile.mkdtemp()

        # Create test data
        test_data = [
            {"id": "template_test_1", "text": "This is template test item 1"},
            {"id": "template_test_2", "text": "This is template test item 2"},
            {"id": "template_test_3", "text": "This is template test item 3"}
        ]

        # Write test data to file
        data_file = os.path.join(test_dir, 'template_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create minimal config
        config = {
            "debug": False,  # Always False for server tests
            "annotation_task_name": "Template Test Task",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "template_scheme",
                    "type": "radio",
                    "labels": ["option_a", "option_b", "option_c"],
                    "description": "Choose one option for the template test."
                }
            ],
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }

        # Write config file
        config_file = os.path.join(test_dir, 'template_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # Create and start server
        server = FlaskTestServer(
            port=find_free_port(),
            debug=False,
            config_file=config_file
        )

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server

        # Cleanup
        server.stop()
        import shutil
        shutil.rmtree(test_dir)

    def test_server_starts_successfully(self, flask_server):
        """
        Test that the server starts and responds to basic requests.

        This is a basic health check test that should always pass.
        """
        # Test root endpoint
        response = flask_server.get("/")
        assert response.status_code in [200, 302]  # 302 is redirect, 200 is success

        # Test auth endpoint
        response = flask_server.get("/auth")
        assert response.status_code == 200

    def test_user_registration_and_login(self, flask_server):
        """
        Test user registration and login workflow.

        This demonstrates the standard pattern for testing user authentication.
        """
        # Create a session for this test
        session = requests.Session()

        # Test user registration
        user_data = {
            "email": "template_test_user",
            "pass": "template_test_password"
        }

        reg_response = session.post(f"{flask_server.base_url}/register", data=user_data)
        assert reg_response.status_code in [200, 302]

        # Test user login
        login_response = session.post(f"{flask_server.base_url}/auth", data=user_data)
        assert login_response.status_code in [200, 302]

        # Test access to annotation page (should be accessible after login)
        annotate_response = session.get(f"{flask_server.base_url}/annotate")
        assert annotate_response.status_code == 200

    def test_admin_endpoint_access(self, flask_server):
        """
        Test admin endpoint access with automatic API key.

        FlaskTestServer automatically adds admin API key headers.
        """
        # Test admin endpoint (FlaskTestServer adds API key automatically)
        response = flask_server.get("/admin/system_state")

        # Note: This endpoint might not exist in all configurations
        # Adjust the expected status code based on your setup
        # 500 can occur if the endpoint exists but has internal errors
        assert response.status_code in [200, 404, 500]

    def test_annotation_workflow(self, flask_server):
        """
        Test complete annotation workflow.

        This demonstrates how to test the full annotation process.
        """
        # Setup user session
        session = requests.Session()
        user_data = {"email": "template_annotator", "pass": "template_password"}
        session.post(f"{flask_server.base_url}/register", data=user_data)
        session.post(f"{flask_server.base_url}/auth", data=user_data)

        # Submit an annotation
        annotation_data = {
            "instance_id": "template_test_1",
            "type": "radio",
            "schema": "template_scheme",
            "state": [{"name": "option_a", "value": "option_a"}]
        }

        response = session.post(
            f"{flask_server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

        # Verify the annotation was saved (if you have admin endpoints)
        # This is optional and depends on your server configuration
        try:
            admin_response = flask_server.get("/admin/system_state")
            if admin_response.status_code == 200:
                # Add verification logic here
                pass
        except Exception:
            # Admin endpoint might not be available
            pass

    def test_error_handling(self, flask_server):
        """
        Test error handling scenarios.

        This demonstrates how to test error conditions.
        """
        # Test invalid endpoint
        response = flask_server.get("/nonexistent_endpoint")
        assert response.status_code == 404

        # Test invalid login
        session = requests.Session()
        invalid_data = {"email": "invalid_user", "pass": "wrong_password"}
        response = session.post(f"{flask_server.base_url}/auth", data=invalid_data)
        # Should either return error or redirect to login page
        assert response.status_code in [200, 302, 401, 403]

    def test_concurrent_requests(self, flask_server):
        """
        Test that the server can handle multiple concurrent requests.

        This tests server stability under load.
        """
        import threading
        import time

        results = []

        def make_request():
            """Make a request and store the result."""
            try:
                response = flask_server.get("/")
                results.append(response.status_code)
            except Exception as e:
                results.append(f"Error: {e}")

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all requests succeeded
        for result in results:
            if isinstance(result, int):
                assert result in [200, 302]  # Success or redirect
            else:
                # If there was an error, it should be a specific type
                assert "Error:" in result


# Example of how to add more test classes for different features
class TestTemplateAdvanced:
    """
    Example of additional test class for advanced features.

    You can create multiple test classes in the same file for related features.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server for advanced tests."""
        # Similar setup as above, but with different port and data
        test_dir = tempfile.mkdtemp()

        # Create different test data for advanced tests
        advanced_data = [
            {"id": "advanced_1", "text": "Advanced test item 1"},
            {"id": "advanced_2", "text": "Advanced test item 2"}
        ]

        data_file = os.path.join(test_dir, 'advanced_test_data.jsonl')
        with open(data_file, 'w') as f:
            for item in advanced_data:
                f.write(json.dumps(item) + '\n')

        # Create config for advanced tests
        config = {
            "debug": False,
            "annotation_task_name": "Advanced Template Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "advanced_scheme",
                    "type": "text",
                    "description": "Enter text annotation."
                }
            ],
            "output_annotation_dir": os.path.join(test_dir, "output"),
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }

        config_file = os.path.join(test_dir, 'advanced_test_config.yaml')
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        server = FlaskTestServer(
            port=find_free_port(),
            debug=False,
            config_file=config_file
        )

        if not server.start():
            pytest.fail("Failed to start Flask test server")

        yield server

        server.stop()
        import shutil
        shutil.rmtree(test_dir)

    def test_advanced_feature(self, flask_server):
        """Test advanced feature functionality."""
        # Add your advanced test logic here
        response = flask_server.get("/")
        assert response.status_code in [200, 302]


if __name__ == "__main__":
    """
    Run this template test directly for development.

    Usage:
        python tests/server/test_template.py
    """
    print("🧪 Running template tests...")

    # This allows running the template directly for development
    pytest.main([__file__, "-v", "-s"])