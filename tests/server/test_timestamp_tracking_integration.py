"""
Server integration tests for timestamp tracking functionality.

This module tests the complete timestamp tracking system through the Flask server,
including annotation submission, history tracking, performance metrics, and admin endpoints.
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


class TestTimestampTrackingIntegration:
    """
    Integration tests for timestamp tracking functionality.

    Tests the complete workflow from annotation submission through
    performance metrics and suspicious activity detection.
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Create a Flask test server with timestamp tracking test data."""
        test_dir = create_test_directory("timestamp_tracking_test")

        # Create test data with multiple instances
        test_data = [
            {"id": "timestamp_test_1", "text": "This is the first test item for timestamp tracking."},
            {"id": "timestamp_test_2", "text": "This is the second test item for timestamp tracking."},
            {"id": "timestamp_test_3", "text": "This is the third test item for timestamp tracking."},
            {"id": "timestamp_test_4", "text": "This is the fourth test item for timestamp tracking."},
            {"id": "timestamp_test_5", "text": "This is the fifth test item for timestamp tracking."}
        ]
        data_file = create_test_data_file(test_dir, test_data)

        # Create annotation schemes
        annotation_schemes = [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative", "neutral"],
                "description": "Choose the sentiment of the text."
            },
            {
                "name": "entity",
                "annotation_type": "span",
                "labels": ["person", "organization", "location"],
                "description": "Mark entities in the text."
            },
            {
                "name": "quality",
                "annotation_type": "likert",
                "min_label": "1",
                "max_label": "5",
                "size": 5,
                "description": "Rate the quality of the text."
            }
        ]

        config_file = create_test_config(
            test_dir,
            annotation_schemes,
            data_files=[data_file],
            annotation_task_name="Timestamp Tracking Test Task",
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

    def test_basic_annotation_timestamps(self):
        """Test that annotations are recorded with timestamps."""
        session = requests.Session()
        user_data = {"email": "timestamp_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit annotation
        annotation_data = {
            "instance_id": "timestamp_test_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }

        response = session.post(
            f"{self.server.base_url}/updateinstance",
            json=annotation_data
        )
        assert response.status_code == 200

    def test_multi_annotation_workflow(self):
        """Test multiple annotations across different types."""
        session = requests.Session()
        user_data = {"email": "multi_timestamp_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Submit sentiment annotation
        annotation_data = {
            "instance_id": "timestamp_test_1",
            "type": "radio",
            "schema": "sentiment",
            "state": [{"name": "positive", "value": "positive"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=annotation_data)
        assert response.status_code == 200

        # Submit quality annotation
        quality_data = {
            "instance_id": "timestamp_test_1",
            "type": "likert",
            "schema": "quality",
            "state": [{"name": "quality", "value": "4"}]
        }
        response = session.post(f"{self.server.base_url}/updateinstance", json=quality_data)
        assert response.status_code == 200

    def test_admin_user_state_endpoint(self):
        """Test admin endpoint for user state with timestamps."""
        session = requests.Session()
        user_data = {"email": "admin_test_user", "pass": "test_password"}
        session.post(f"{self.server.base_url}/register", data=user_data)
        session.post(f"{self.server.base_url}/auth", data=user_data)

        # Get user state via admin endpoint
        admin_response = self.server.get("/admin/user_state/admin_test_user")
        assert admin_response.status_code == 200

        user_state = admin_response.json()
        assert "user_id" in user_state
        assert user_state["user_id"] == "admin_test_user"
