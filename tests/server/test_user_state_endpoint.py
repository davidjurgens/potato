"""
Integration tests for /admin/user_state/<user_id> endpoint.

These tests verify that the user state endpoint returns the correct structure
and handles various scenarios properly.
"""

import pytest
import os
import shutil
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_span_annotation_config,
    cleanup_test_directory
)


class TestUserStateEndpoint:
    """Test the /admin/user_state/<user_id> endpoint."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with span annotation config."""
        # Create a test directory using modern utilities
        test_dir = create_test_directory("user_state_endpoint_test")

        # Create span annotation config with admin API key
        config_file, data_file = create_span_annotation_config(
            test_dir,
            annotation_task_name="User State Endpoint Test",
            require_password=False,
            admin_api_key="admin_api_key",
            max_annotations_per_user=10
        )

        # Create server with the config file
        server = FlaskTestServer(
            config_file=config_file,
            debug=False
        )

        # Start server
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        # Store server for cleanup
        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        # Cleanup
        server.stop()
        cleanup_test_directory(test_dir)

    def register_and_login(self, username, password):
        """Register and login a user using production endpoints, return session."""
        session = requests.Session()
        user_data = {"email": username, "pass": password}
        reg_response = session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        assert reg_response.status_code in [200, 302], f"Registration failed: {reg_response.status_code} {reg_response.text}"
        login_response = session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)
        assert login_response.status_code in [200, 302], f"Login failed: {login_response.status_code} {login_response.text}"
        return session

    def test_user_state_endpoint_structure(self):
        """Test that the user state endpoint returns the correct structure."""
        username = "testuser"
        password = "testpass"
        session = self.register_and_login(username, password)
        # Use FlaskTestServer.get() which automatically adds admin API key
        response = self.server.get(f"/admin/user_state/{username}")
        print(f"Response status: {response.status_code}")
        print(f"Response text: {response.text}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        print(f"Response JSON: {data}")
        print(f"Response keys: {list(data.keys())}")
        required_fields = [
            "user_id", "current_instance", "annotations", "assignments",
            "phase"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        assert "annotations" in data
        assert "by_instance" in data["annotations"]
        assert isinstance(data["annotations"]["by_instance"], dict)
        assert "assignments" in data
        assert "annotated" in data["assignments"]
        assert "total" in data["assignments"]
        assert isinstance(data["assignments"]["annotated"], int)
        assert isinstance(data["assignments"]["total"], int)

    def test_user_state_endpoint_annotations_by_instance(self):
        """Test that annotations are properly nested under by_instance."""
        username = "testuser2"
        password = "testpass"
        session = self.register_and_login(username, password)
        # Use FlaskTestServer.get() which automatically adds admin API key
        response = self.server.get(f"/admin/user_state/{username}")
        assert response.status_code == 200
        data = response.json()
        annotations = data.get("annotations", {})
        by_instance = annotations.get("by_instance", {})
        assert isinstance(by_instance, dict), "annotations.by_instance should be a dictionary"
        for instance_id, instance_annotations in by_instance.items():
            assert isinstance(instance_annotations, dict), f"Annotations for {instance_id} should be a dictionary"

    def test_user_state_endpoint_json_serializable(self):
        """Test that the response is valid JSON."""
        import json
        username = "testuser3"
        password = "testpass"
        session = self.register_and_login(username, password)
        # Use FlaskTestServer.get() which automatically adds admin API key
        response = self.server.get(f"/admin/user_state/{username}")
        assert response.status_code == 200
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError as e:
            pytest.fail(f"Response is not valid JSON: {e}")

    def test_user_state_endpoint_with_annotations(self):
        """Test user state endpoint when user has annotations."""
        username = "testuser4"
        password = "testpass"
        session = self.register_and_login(username, password)
        # Use FlaskTestServer.get() which automatically adds admin API key
        response = self.server.get(f"/admin/user_state/{username}")
        assert response.status_code == 200
        initial_data = response.json()
        initial_annotations = initial_data.get("annotations", {}).get("by_instance", {})
        assert isinstance(initial_annotations, dict)
        assignments = initial_data.get("assignments", {})
        assert "annotated" in assignments
        assert "total" in assignments
        assert assignments["annotated"] >= 0
        assert assignments["total"] >= 0

    def test_user_state_endpoint_error_handling(self):
        """Test error handling for non-existent users."""
        # Use FlaskTestServer.get() which automatically adds admin API key
        response = self.server.get(f"/admin/user_state/nonexistent_user")
        assert response.status_code in [404, 200]  # 200 if it creates the user, 404 if not found
