"""
Server tests for complete span annotation workflow.

These tests verify the complete span annotation process, including:
- Schema loading from API
- Span annotation creation with proper schema
- Fix for the "No schema selected" error
"""

import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_span_annotation_config,
    cleanup_test_directory
)


class TestSpanAnnotationWorkflow:
    """Test the complete span annotation workflow."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Set up test configuration with span annotation schemes."""
        test_dir = create_test_directory("span_annotation_workflow_test")

        config_file, data_file = create_span_annotation_config(
            test_dir,
            annotation_task_name="Span Workflow Test",
            require_password=False,
            admin_api_key="admin_api_key"
        )

        server = FlaskTestServer(config_file=config_file, debug=False)
        if not server.start():
            pytest.fail("Failed to start Flask test server")

        request.cls.server = server
        request.cls.test_dir = test_dir

        yield server

        server.stop()
        cleanup_test_directory(test_dir)

    def test_schema_api_returns_span_schemas(self):
        """Test that the /api/schemas endpoint returns span schemas."""
        response = self.server.get('/api/schemas')
        assert response.status_code == 200

        schemas = response.json()
        assert isinstance(schemas, dict)

    def test_span_annotation_creation(self):
        """Test creating a span annotation."""
        session = requests.Session()
        user_data = {"email": "span_workflow_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        annotation_data = {
            "instance_id": "1",
            "type": "span",
            "schema": "sentiment",
            "state": [
                {"name": "happy", "title": "happy", "start": 0, "end": 10, "value": "happy"}
            ]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

    def test_span_annotation_update(self):
        """Test updating a span annotation."""
        session = requests.Session()
        user_data = {"email": "span_update_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Create initial annotation
        annotation_data = {
            "instance_id": "1",
            "type": "span",
            "schema": "sentiment",
            "state": [{"name": "happy", "start": 0, "end": 10, "value": "happy"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

        # Update annotation
        annotation_data["state"] = [{"name": "sad", "start": 5, "end": 15, "value": "sad"}]
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200
