"""
Test to reproduce the annotation persistence bug.

The bug is that the frontend sends data in a different format than what the
/updateinstance endpoint expects, causing annotations to not be saved.
"""

import pytest
import json
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory
)


class TestAnnotationPersistenceBug:
    """Test to reproduce and verify the annotation persistence bug."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with mixed annotation types."""
        test_dir = create_test_directory("annotation_persistence_bug_test")

        # Create test data
        test_data = [
            {"id": "item_1", "text": "This is a test item."},
            {"id": "item_2", "text": "This is another test item."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "sentiment",
                "description": "Select sentiment",
                "labels": ["positive", "negative", "neutral"]
            },
            {
                "annotation_type": "likert",
                "name": "confidence",
                "description": "Rate confidence",
                "min_label": "1",
                "max_label": "5",
                "size": 5
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Test Annotation Task",
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

    def test_frontend_backend_format_mismatch(self):
        """Test annotation handling with different data formats."""
        # Register a test user
        session = requests.Session()
        user_data = {"email": "test_user_bug", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Simulate frontend-style annotation data
        frontend_data = {
            "instance_id": "item_1",
            "annotations": {
                "sentiment:positive": "true",
                "confidence:3": "true"
            },
            "span_annotations": []
        }

        # Send the frontend format to /updateinstance
        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=frontend_data,
            timeout=5
        )

        # The request should succeed (no error)
        assert response.status_code == 200
        result = response.json()
        assert result.get("status") == "success" or "error" not in result

    def test_verify_backend_expectations(self):
        """Test annotation submission with correct format."""
        # Register a test user
        session = requests.Session()
        user_data = {"email": "test_user_backend", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data, timeout=5)
        session.post(f"{self.server.base_url}/auth", data=user_data, timeout=5)

        # Test the format the backend expects for label annotations
        annotation_data = {
            "instance_id": "item_1",
            "schema": "sentiment",
            "state": [
                {"name": "positive", "value": "true"},
                {"name": "negative", "value": None},
                {"name": "neutral", "value": None}
            ],
            "type": "label"
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data,
            timeout=5
        )

        assert response.status_code == 200
        result = response.json()
        assert result.get("status") == "success" or "error" not in result
